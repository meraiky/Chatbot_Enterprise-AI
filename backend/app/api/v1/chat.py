from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import hashlib
import json
import logging
import time
from uuid import uuid4
from typing import Literal, List, Optional

import redis
from pydantic import BaseModel, ConfigDict, Field
from app.services.rag.query_engine import (
    answer_query,
    answer_query_stream_events,
    answer_query_hybrid,
    answer_query_stream_events_hybrid,
)
from app.core.config import settings
from app.core.auth import get_current_user, TokenData
from fastapi import Depends

router = APIRouter()
logger = logging.getLogger(__name__)

# Simple in-memory rate limiter fallback (per process)
_last_request_time: dict[str, float] = {}
_rate_limit_client: redis.Redis | None = None


def _public_chat_error(error: Exception) -> str:
    message = str(error)
    lower_message = message.lower()
    if "api key not valid" in lower_message or "api_key_invalid" in lower_message:
        return "Gemini API key is invalid. Update GEMINI_API_KEY in backend/.env and restart the backend."
    if "gemini_api_key is not configured" in lower_message:
        return "GEMINI_API_KEY is not configured in backend/.env."
    if "model" in lower_message and ("not found" in lower_message or "not supported" in lower_message):
        return "Gemini model is not available for this API key. Check CHAT_MODEL and EMBEDDING_MODEL in backend/.env."
    return "Internal server error. Please try again later."


def _chunk_to_text(chunk) -> str:
    content = chunk.content if hasattr(chunk, "content") else chunk
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            elif hasattr(item, "text"):
                parts.append(str(item.text))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def _sse(event: str, data: dict) -> str:
    # SSE spec: each data field must be a single line - no embedded newlines
    payload = json.dumps(data, ensure_ascii=False).replace('\n', ' ').replace('\r', '')
    return f"event: {event}\ndata: {payload}\n\n"


class HistoryMessage(BaseModel):
    """Represents a single message in the conversation history."""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"role": "user", "content": "What is the company leave policy?"}
        }
    )

    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, description="The content of the message")


class ChatRequest(BaseModel):
    """Request body for chat queries."""
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "question": "How do I apply for annual leave?",
                "mode": "Internal",
                "history": [
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hello! How can I help you today?"}
                ]
            }
        },
    )

    question: str = Field(..., min_length=1, max_length=4000, description="The user's question or prompt")
    mode: Literal["Internal", "External"] = Field("Internal", description="Search mode: Internal for employees, External for public")
    history: Optional[List[HistoryMessage]] = Field(default_factory=list, description="Previous conversation turns for context")
    conversation_id: Optional[str] = Field(None, description="Stable client conversation/session id")

    allow_web_search: bool = Field(False, description="Allow fallback to external web search when internal documents do not contain enough information")


def _get_rate_limit_client() -> redis.Redis | None:
    global _rate_limit_client
    if _rate_limit_client is not None:
        return _rate_limit_client
    try:
        client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()
        _rate_limit_client = client
        return _rate_limit_client
    except Exception:
        logger.warning("Redis unavailable for rate limiting; using process-local fallback")
        _rate_limit_client = None
        return None


def _rate_limit_key(mode: str, question: str) -> str:
    digest_input = f"{mode}:{question[:40].strip().lower()}"
    digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    return f"rate_limit:{digest}"


def _rate_limit_check(mode: str, question: str) -> None:
    """Raise 429 if the same question was sent too recently.

    Rate limiting is enforced at the chat endpoint level (not as a global
    middleware) because only chat requests are expensive. Auth and admin
    endpoints do not need per-question deduplication.
    Uses Redis when available; falls back to a process-local dict.
    Configurable via RATE_LIMIT_SECONDS in .env.
    """
    key = _rate_limit_key(mode, question)
    client = _get_rate_limit_client()

    if client is not None:
        try:
            if not client.set(key, "1", nx=True, ex=settings.RATE_LIMIT_SECONDS):
                raise HTTPException(
                    status_code=429,
                    detail=f"Please wait {settings.RATE_LIMIT_SECONDS}s before repeating the same request.",
                )
            return
        except HTTPException:
            raise
        except Exception:
            logger.warning("Redis rate limit failed; using process-local fallback")

    now = time.monotonic()
    last = _last_request_time.get(key, 0)
    if now - last < settings.RATE_LIMIT_SECONDS:
        raise HTTPException(
            status_code=429,
            detail=f"Please wait {settings.RATE_LIMIT_SECONDS}s before repeating the same request.",
        )
    _last_request_time[key] = now


class UsageRecord(BaseModel):
    request_id: str
    conversation_id: Optional[str] = None
    operation: str
    mode: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated: bool

class ChatUsage(BaseModel):
    request_id: str
    conversation_id: Optional[str] = None
    records: List[UsageRecord]
    total_tokens: int

class SourceInfo(BaseModel):
    rank: int
    source: str
    page: Optional[int]
    type: str
    doc_id: str
    distance: float
    preview: str

class ExternalSourceInfo(BaseModel):
    url: str
    title: str
    snippet: str


class ChatResponse(BaseModel):
    """Standard response for non-streaming chat queries."""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "reply": "You can apply for annual leave via the HR portal.",
                "sources": [
                    {
                        "rank": 1,
                        "source": "HR_Policy_2024.pdf",
                        "page": 12,
                        "type": "Internal",
                        "doc_id": "doc_123",
                        "distance": 0.1234,
                        "preview": "Annual leave requests must be submitted 2 weeks in advance..."
                    }
                ],
                "cache_hit": False,
                "blocked": False,
                "usage": {
                    "request_id": "req_abc123",
                    "records": [],
                    "total_tokens": 450
                }
            }
        }
    )

    reply: str = Field(..., description="The AI generated answer")
    sources: List[SourceInfo] = Field(default_factory=list, description="List of internal documents used to generate the answer")
    external_sources: List[ExternalSourceInfo] = Field(default_factory=list, description="External web sources used to generate the answer")
    source_type: str = Field("internal", description="internal | external_web | hybrid | none")
    web_search_offered: bool = Field(False, description="Whether the assistant is asking user permission to search the web")
    web_search_performed: bool = Field(False, description="Whether external web search was executed")
    suggestion: Optional[str] = Field(None, description="Optional follow-up suggestion shown when web search is offered")
    cache_hit: bool = Field(..., description="Whether the answer was retrieved from semantic cache")
    blocked: Optional[bool] = Field(None, description="Whether the request was blocked by the Topic Guard")
    usage: ChatUsage = Field(..., description="Token usage details for the request")

@router.post("/message", response_model=ChatResponse)
def send_message(
    request: ChatRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Send a chat message and receive a complete response.

    This endpoint uses a hybrid RAG pipeline (Vector + BM25 + Reranking) to provide
    accurate answers based on the selected mode (Internal/External).
    Declared as `def` (not `async def`) so FastAPI runs it in a threadpool,
    which is correct for a synchronous blocking RAG pipeline.
    """
    _rate_limit_check(request.mode, request.question)
    history = [m.model_dump() for m in (request.history or [])]
    conversation_id = request.conversation_id or str(uuid4())

    try:
        result = answer_query(request.question, request.mode, history, conversation_id, user_id=current_user.user_id)
        result["usage"]["conversation_id"] = conversation_id
        return result
    except Exception as e:
        logger.exception("Failed to answer chat request")
        raise HTTPException(status_code=500, detail=_public_chat_error(e))


@router.post("/message/hybrid", response_model=ChatResponse)
async def send_message_hybrid(
    request: ChatRequest,
    current_user: TokenData = Depends(get_current_user)
):
    _rate_limit_check(request.mode, request.question)
    history = [m.model_dump() for m in (request.history or [])]
    conversation_id = request.conversation_id or str(uuid4())

    try:
        result = await answer_query_hybrid(
            request.question,
            request.mode,
            history,
            conversation_id,
            user_id=current_user.user_id,
            allow_web_search=request.allow_web_search,
        )
        result["usage"]["conversation_id"] = conversation_id
        return result
    except Exception as e:
        logger.exception("Failed to answer hybrid chat request")
        raise HTTPException(status_code=500, detail=_public_chat_error(e))


@router.post("/message/hybrid/stream")
async def send_message_hybrid_stream(
    request: ChatRequest,
    current_user: TokenData = Depends(get_current_user)
):
    _rate_limit_check(request.mode, request.question)
    history = [m.model_dump() for m in (request.history or [])]
    conversation_id = request.conversation_id or str(uuid4())

    async def event_stream_hybrid():
        yielded = False
        try:
            async for item in answer_query_stream_events_hybrid(
                request.question,
                request.mode,
                history,
                conversation_id,
                user_id=current_user.user_id,
                allow_web_search=request.allow_web_search,
            ):
                if isinstance(item, dict) and "event" in item:
                    event = str(item.get("event") or "token")
                    data = item.get("data") if isinstance(item.get("data"), dict) else {}
                    if event == "token" and data.get("text"):
                        yielded = True
                    yield _sse(event, data)
                    continue

                text = _chunk_to_text(item)
                if text:
                    yielded = True
                    yield _sse("token", {"text": text})

            if not yielded:
                yield _sse("token", {"text": "Error: No response received from server."})
        except Exception as e:
            logger.exception("Failed to stream hybrid chat response")
            yield _sse("token", {"text": f"Error: {_public_chat_error(e)}"})
            yield _sse("done", {})

    return StreamingResponse(event_stream_hybrid(), media_type="text/event-stream")


@router.post("/message/stream")
async def send_message_stream(
    request: ChatRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Send a chat message and receive a streaming response via Server-Sent Events (SSE).
    
    Ideal for long responses to improve perceived latency.
    """
    _rate_limit_check(request.mode, request.question)
    history = [m.model_dump() for m in (request.history or [])]
    conversation_id = request.conversation_id or str(uuid4())

    def event_stream():
        yielded = False
        try:
            for item in answer_query_stream_events(request.question, request.mode, history, conversation_id, user_id=current_user.user_id):
                if isinstance(item, dict) and "event" in item:
                    event = str(item.get("event") or "token")
                    data = item.get("data") if isinstance(item.get("data"), dict) else {}
                    if event == "token" and data.get("text"):
                        yielded = True
                    yield _sse(event, data)
                    continue

                text = _chunk_to_text(item)
                if text:
                    yielded = True
                    yield _sse("token", {"text": text})

            if not yielded:
                yield _sse("token", {"text": "Error: No response received from server."})
        except Exception as e:
            logger.exception("Failed to stream chat response")
            yield _sse("token", {"text": f"Error: {_public_chat_error(e)}"})
            yield _sse("done", {})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
