import json
import logging
import re
import unicodedata
from typing import List, Dict, Optional, Any
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

from app.services.rag.vector_store import get_vector_store
from app.services.rag.bm25_search import BM25Searcher
from app.services.rag.reranker import reranker
from app.services.llm_service import get_llm
from app.core.config import settings
from app.services.usage_tracker import (
    estimate_tokens,
    new_request_id,
    normalize_usage,
    record_usage,
)
from app.services.chat_audit_service import record_chat_audit
from app.services.rag.cache_service import cache_service
from app.services.rag.document_images import list_document_images
from app.services.topic_guard_service import check_topic_guard
from app.core.observability import trace_span
from langchain_core.prompts import ChatPromptTemplate
from app.services.pricing_service import is_over_budget
from app.services.rag.injection_scanner import scan_chunk


NO_CONTEXT_ANSWER = (
    "I don't have enough information to answer that based on my current knowledge base."
)
NO_CONTEXT_ANSWER_VI = (
    "Mình chưa tìm thấy nội dung phù hợp trong kho tài liệu hiện tại."
)
CHIT_CHAT_REPLY = (
    "Yes. I can answer in Vietnamese or English. "
    "Ask me about a policy, process, product, or document and I will cite the sources I use."
)
OUT_OF_SCOPE_REPLY = (
    "I can only answer questions related to the indexed knowledge base. "
    "Please ask about uploaded company documents, policies, processes, or public FAQs."
)
OUT_OF_SCOPE_REPLY_VI = (
    "Mình chỉ có thể trả lời các câu hỏi liên quan đến kho tài liệu đã được tải lên, "
    "chính sách, quy trình, sản phẩm hoặc FAQ công khai."
)

_RRF_K = 60

# Normalize user intent before matching so Vietnamese accents and older mojibake
# text paths do not fall through into the expensive RAG pipeline.
_CHIT_CHAT_PATTERNS = (
    r"^\s*(hi|hello|hey|xin ch.*o|ch.*o|good morning|good afternoon|good evening)\s*[!.?]*\s*$",
    r"^\s*(thanks|thank you|cam on)\s*[!.?]*\s*$",
    r".*\b(tieng viet|vietnamese|ban la ai|who are you|what can you do|ban lam duoc gi)\b.*",
)
_OUT_OF_SCOPE_KEYWORDS = (
    "weather",
    "stock price",
    "football score",
    "recipe",
    "cook",
    "nau",
    "thoi tiet",
    "du bao thoi tiet",
    "gia vang",
    "gia do la",
    "ty gia",
    "chung khoan",
    "co phieu",
    "bong da",
    "ket qua bong da",
    "xem phim",
    "nghe nhac",
    "ke chuyen cuoi",
    "tro choi",
    "game",
)

# ---------------------------------------------------------------------------
# Module-specific system prompts (inspired by Viet-ERP ai-service pattern)
# ---------------------------------------------------------------------------
_SYSTEM_PROMPTS: Dict[str, str] = {
    "Internal": (
        "You are an Enterprise Internal AI Assistant. "
        "Help employees with company policies, HR rules, internal processes, and confidential documents. "
        "Always cite the source document when answering."
    ),
    "External": (
        "You are a Public-facing AI Assistant. "
        "Help customers with product information, public FAQs, and general enquiries. "
        "Do not reveal any internal or confidential information."
    ),
    # Extendable: add 'hr', 'erp', etc.
}
_DEFAULT_SYSTEM_PROMPT = (
    "You are an Enterprise AI Assistant. "
    "Provide accurate answers based strictly on the provided context."
)


def _search_filter(mode: str) -> dict[str, str]:
    return {"type": mode}


def _check_prompt_injection(question: str) -> None:
    """Scan user query for prompt injection attempts.
    
    CRITICAL FIX (C-4): Previously no scanning of user queries before LLM injection.
    Now scans every query and raises ValueError if injection patterns detected.
    
    Raises:
        ValueError: If prompt injection patterns are detected in the query
    """
    scan_result = scan_chunk(question)
    if not scan_result["clean"]:
        logger.warning(
            "Prompt injection detected in user query. Findings: %s",
            scan_result["findings"]
        )
        raise ValueError(
            "Your query contains patterns that may be attempting to manipulate the system. "
            "Please rephrase your question."
        )


def _normalize_for_intent(text: str) -> str:
    """
    Normalize text for intent matching by removing Vietnamese diacritics.
    Handles both decomposable marks (á, ă, ê) and non-decomposable letters (đ).
    """
    text = text.strip().lower()
    # Replace đ/Đ explicitly since it doesn't decompose with NFD
    text = text.replace("đ", "d").replace("Đ", "d")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )


def _classify_light_intent(question: str) -> str:
    """Cheap guardrail before cache/retrieval; avoids spending tokens on obvious non-RAG turns."""
    normalized = _normalize_for_intent(question)
    if not normalized:
        return "empty"
    if any(re.match(pattern, normalized, re.IGNORECASE) for pattern in _CHIT_CHAT_PATTERNS):
        return "chit_chat"
    if any(keyword in normalized for keyword in _OUT_OF_SCOPE_KEYWORDS):
        return "out_of_scope"
    return "rag"


def _prefers_vietnamese(text: str) -> bool:
    normalized = f" {_normalize_for_intent(text)} "
    return any(
        marker in normalized
        for marker in (
            " la ",
            " gi",
            " nhu the nao",
            " the nao",
            " tom tat",
            " giai thich",
            " quy trinh",
            " kiem tra",
            " tao ",
            " hoa don",
            " cong no",
            " duoc khong",
            " tieng viet",
            " hom nay",
            " bao nhieu",
            " ra sao",
        )
    )


def _no_context_answer(question: str, mode: str) -> str:
    if _prefers_vietnamese(question):
        return (
            f"{NO_CONTEXT_ANSWER_VI} Bạn đang hỏi ở chế độ {mode}; "
            "hãy kiểm tra tài liệu đã được upload đúng chế độ chưa."
        )
    return (
        f"{NO_CONTEXT_ANSWER} You are asking in {mode} mode; "
        "check that the document was uploaded to the same mode."
    )


def _out_of_scope_reply(question: str) -> str:
    """Return an out-of-scope rejection in the user's preferred language."""
    if _prefers_vietnamese(question):
        return OUT_OF_SCOPE_REPLY_VI
    return OUT_OF_SCOPE_REPLY


def _rrf_fuse_results(
    vector_results: list[tuple[Document, float]],
    bm25_docs: list[tuple[Document, float]],
    limit: int,
    rrf_k: int = _RRF_K,
) -> list[tuple[Document, float]]:
    """
    Fuse vector and BM25 rankings with Reciprocal Rank Fusion.

    Raw vector distances and BM25 scores use different scales, so rank-based
    fusion is more stable than comparing numeric scores directly.
    """
    fused_scores: dict[str, float] = {}
    docs_by_key: dict[str, Document] = {}

    def add_ranked(results: list[tuple[Document, float]]) -> None:
        seen_in_list: set[str] = set()
        for rank, (doc, _score) in enumerate(results, start=1):
            key = doc.page_content
            if not key or key in seen_in_list:
                continue
            seen_in_list.add(key)
            docs_by_key.setdefault(key, doc)
            fused_scores[key] = fused_scores.get(key, 0.0) + 1.0 / (rrf_k + rank)

    add_ranked(vector_results)
    add_ranked(bm25_docs)

    ranked_keys = sorted(fused_scores, key=fused_scores.get, reverse=True)[:limit]  # type: ignore[arg-type]
    return [(docs_by_key[key], fused_scores[key]) for key in ranked_keys]


def retrieve_context(question: str, mode: str, request_id: str, conversation_id: str | None = None):
    # Measure total retrieval time
    with trace_span("total_retrieval", request_id=request_id, mode=mode) as total_trace:
        retrieval_usage = record_usage(
            request_id=request_id,
            operation="retrieval_embedding",
            mode=mode,
            model=settings.EMBEDDING_MODEL,
            input_tokens=estimate_tokens(question),
            estimated=True,
            conversation_id=conversation_id,
        )

        vector_store = get_vector_store()
        
        # 1. Vector Search (Semantic)
        with trace_span("vector_search", request_id=request_id, mode=mode):
            vector_results = vector_store.similarity_search_with_score(
                question,
                k=settings.RETRIEVAL_CANDIDATES_K,
                filter=_search_filter(mode),
            )
        
        # 2. BM25 Search (Keyword)
        with trace_span("bm25_search", request_id=request_id, mode=mode):
            all_docs = vector_store.get_corpus(mode)
            corpus = all_docs.get("documents") or []
            metadatas = all_docs.get("metadatas") or []
            
            # Use persistent BM25 searcher with mode-specific caching
            bm25_searcher = BM25Searcher(corpus, mode=mode)
            bm25_results_indices = bm25_searcher.search(question, k=settings.RETRIEVAL_CANDIDATES_K)
            
            bm25_docs = []
            for idx, score in bm25_results_indices:
                if idx >= len(corpus):
                    continue
                bm25_docs.append((
                    Document(
                        page_content=corpus[idx],
                        metadata=metadatas[idx] if idx < len(metadatas) else {},
                    ),
                    score
                ))
        
        # 3. Reciprocal Rank Fusion (RRF) and deduplication
        fused_results = _rrf_fuse_results(
            vector_results=vector_results,
            bm25_docs=bm25_docs,
            limit=settings.RETRIEVAL_CANDIDATES_K,
        )
                
        # 4. Re-ranking using Cross-Encoder
        with trace_span("reranking", request_id=request_id, mode=mode):
            candidate_docs = [doc for doc, _score in fused_results]
            candidate_texts = [doc.page_content for doc in candidate_docs]
            
            reranked_pairs = reranker.rerank(question, candidate_texts)
    
    # Map back to Document objects
    final_results = []
    for text, score in reranked_pairs:
        doc = next((d for d in candidate_docs if d.page_content == text), None)
        if doc:
            final_results.append((doc, score))

    if final_results and float(final_results[0][1]) < settings.MIN_RERANK_SCORE:
        return "", [], retrieval_usage

    top_results = final_results[:settings.FINAL_CONTEXT_K]

    context_parts = []
    sources = []
    total_chars = 0

    for rank, (document, distance) in enumerate(top_results, start=1):
        content = document.page_content.strip()
        if not content:
            continue

        metadata = document.metadata
        source = {
            "rank": rank,
            "source": metadata.get("source", "Unknown"),
            "page": metadata.get("page"),
            "type": metadata.get("type", mode),
            "doc_id": metadata.get("doc_id", ""),
            "distance": round(float(distance), 4),
            "preview": content[:240],
        }
        sources.append(source)

        part = (
            f"[Source {rank}: {source['source']}, page {source['page'] or 'unknown'}]\n"
            f"{content}"
        )
        if total_chars + len(part) > settings.MAX_CONTEXT_CHARS:
            break
        context_parts.append(part)
        total_chars += len(part)

    return "\n\n".join(context_parts), sources, retrieval_usage


def _source_images(sources: list[dict] | None) -> list[dict[str, Any]]:
    """Attach PDF images from the same document/page as retrieved source chunks."""
    images: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources or []:
        doc_id = str(source.get("doc_id") or "")
        if not doc_id:
            continue
        source_page = source.get("page")
        for image in list_document_images(doc_id):
            image_page = image.get("page")
            if source_page is not None and image_page is not None and image_page != source_page:
                continue
            image_id = str(image.get("image_id") or "")
            if not image_id or image_id in seen:
                continue
            seen.add(image_id)
            images.append(
                {
                    "image_id": image_id,
                    "doc_id": image.get("doc_id"),
                    "source": image.get("source"),
                    "page": image_page,
                    "caption": image.get("caption"),
                    "url": f"/api/v1/document/images/{image_id}/content",
                }
            )
            if len(images) >= 6:
                return images
    return images


def _build_prompt(mode: str) -> ChatPromptTemplate:
    """Build a mode-specific prompt template."""
    system_prompt = _SYSTEM_PROMPTS.get(mode, _DEFAULT_SYSTEM_PROMPT)

    template = f"""{system_prompt}
Answer based ONLY on the following context. If the context does not contain
the answer, say "{{no_context_answer}}"

Response style:
- Reply in the same language as the user's question. For Vietnamese questions, use natural Vietnamese.
- Start with a short summary of 1-2 sentences.
- Then add only the key points needed to answer the question.
- Keep answers concise by default: usually 3-5 bullets or short paragraphs.
- If the user asks "what is/what does it mean", explain simply first, then add details.
- Do not paste long excerpts from the source.
- Cite sources compactly at the end as: "Nguon: filename, trang X" or "Source: filename, page X".
- Do not make up information.

Context:
{{context}}

Conversation History (last {settings.MAX_HISTORY_MESSAGES} turns):
{{history}}

Question:
{{question}}

Answer:"""

    return ChatPromptTemplate.from_template(template)


def _build_chain(mode: str, streaming: bool = False, user_id: int | None = None):
    return _build_prompt(mode) | get_llm(streaming=streaming, user_id=user_id)


def _prepare_history(history: Optional[List[Dict[str, str]]]) -> str:
    """
    Prepare conversation history within a token budget.
    Keeps the most recent useful turns and prunes older turns deterministically.
    """
    history = history or []
    if not history:
        return "(none)"

    recent = history[-settings.MAX_HISTORY_MESSAGES :]
    selected: list[str] = []
    budget = max(settings.MAX_HISTORY_TOKENS, 0)
    used_tokens = 0

    for message in reversed(recent):
        role = str(message.get("role", "user")).capitalize()
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        line = f"{role}: {content}"
        line_tokens = estimate_tokens(line)
        if selected and used_tokens + line_tokens > budget:
            break
        selected.append(line)
        used_tokens += line_tokens

    if not selected:
        return "(history pruned to fit token budget)"

    selected.reverse()
    if len(selected) < len(recent):
        selected.insert(0, "(earlier turns pruned to fit token budget)")
    return "\n".join(selected)


def _content_to_text(content) -> str:
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


def _usage_metadata(question: str, answer: str, sources: list[dict] | None = None) -> dict[str, object]:
    return {
        "question": question,
        "answer_preview": answer[:500],
        "sources": [
            {
                "source": source.get("source"),
                "page": source.get("page"),
                "type": source.get("type"),
            }
            for source in (sources or [])[:5]
        ],
    }


def _record_audit_from_usage(
    *,
    conversation_id: str | None,
    request_id: str,
    mode: str,
    question: str,
    answer: str,
    sources: list[dict] | None,
    usage: dict[str, object] | None,
    estimated: bool = True,
) -> None:
    if not conversation_id:
        return
    usage = usage or {}
    record_chat_audit(
        conversation_id=conversation_id,
        request_id=request_id,
        mode=mode,
        question=question,
        answer=answer,
        sources=sources or [],
        input_tokens=int(usage.get("input_tokens") or 0),  # type: ignore[arg-type]
        output_tokens=int(usage.get("output_tokens") or 0),  # type: ignore[arg-type]
        total_tokens=int(usage.get("total_tokens") or 0),  # type: ignore[arg-type]
        estimated=bool(usage.get("estimated", estimated)),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def answer_query(
    question: str,
    mode: str,
    history: Optional[List[Dict[str, str]]] = None,
    conversation_id: str | None = None,
    user_id: int | None = None,
):
    _check_prompt_injection(question)
    if is_over_budget(conversation_id):
        raise ValueError(f"Local cost budget of ${settings.LOCAL_COST_BUDGET} has been exceeded.")

    request_id = new_request_id()
    history_text = _prepare_history(history)

    intent = _classify_light_intent(question)
    if intent == "empty":
        reply = "Please enter a question."
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=reply,
            sources=[],
            usage={"total_tokens": 0, "estimated": True},
        )
        return {
            "reply": reply,
            "sources": [],
            "cache_hit": False,
            "usage": {"request_id": request_id, "records": [], "total_tokens": 0},
        }
    if intent == "chit_chat":
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=CHIT_CHAT_REPLY,
            sources=[],
            usage={"total_tokens": 0, "estimated": True},
        )
        return {
            "reply": CHIT_CHAT_REPLY,
            "sources": [],
            "cache_hit": False,
            "usage": {"request_id": request_id, "records": [], "total_tokens": 0},
        }
    if intent == "out_of_scope":
        reply = _out_of_scope_reply(question)
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=reply,
            sources=[],
            usage={"total_tokens": 0, "estimated": True},
        )
        return {
            "reply": reply,
            "sources": [],
            "cache_hit": False,
            "blocked": True,
            "guardrail": {
                "type": "out_of_scope",
                "reason": "question does not match indexed knowledge base",
            },
            "usage": {"request_id": request_id, "records": [], "total_tokens": 0},
        }

    # 0. Topic guard check - block restricted topics before any token spend
    blocked, guard_reason = check_topic_guard(question, mode)
    if blocked:
        reply = f"Blocked: {guard_reason}"
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=reply,
            sources=[],
            usage={"total_tokens": 0, "estimated": True},
        )
        return {
            "reply": reply,
            "sources": [],
            "cache_hit": False,
            "blocked": True,
            "usage": {"request_id": request_id, "records": [], "total_tokens": 0},
        }

    # 1. Semantic cache check
    cached_result = cache_service.get_cached_answer(question, mode)
    if cached_result:
        reply, sources = cached_result
        cache_usage = record_usage(
            request_id=request_id,
            operation="cache_hit",
            mode=mode,
            model="cache",
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            estimated=True,
            conversation_id=conversation_id,
        )
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=reply,
            sources=sources,
            usage=cache_usage,
        )
        return {
            "reply": reply,
            "sources": sources,
            "source_images": _source_images(sources),
            "cache_hit": True,
            "usage": {
                "request_id": request_id,
                "records": [cache_usage],
                "total_tokens": 0,
            },
        }

    usage_records = []
    with trace_span("full_retrieval_pipeline", request_id=request_id, mode=mode) as retrieval_trace:
        context, sources, retrieval_usage = retrieve_context(question, mode, request_id, conversation_id)
        
        # retrieve_context already records usage; attach the measured outer duration
        # to the in-memory response payload without writing a duplicate record.
        retrieval_usage["duration"] = retrieval_trace.get_duration()
        usage_records.append(retrieval_usage)

    if not context:
        reply = _no_context_answer(question, mode)
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=reply,
            sources=[],
            usage={"total_tokens": sum(r["total_tokens"] for r in usage_records), "estimated": True},
        )
        return {
            "reply": reply,
            "sources": [],
            "cache_hit": False,
            "usage": {
                "request_id": request_id,
                "records": usage_records,
                "total_tokens": sum(r["total_tokens"] for r in usage_records),
            },
        }

    with trace_span("llm_generation", request_id=request_id, mode=mode) as llm_trace:
        chain = _build_chain(mode, user_id=user_id)
        response = chain.invoke(
            {
                "context": context,
                "history": history_text,
                "question": question,
                "no_context_answer": _no_context_answer(question, mode),
            }
        )
        reply = response.content if hasattr(response, "content") else str(response)
        usage = normalize_usage(
            getattr(response, "usage_metadata", None)
            or getattr(response, "response_metadata", {}).get("token_usage")
        )
        estimated = False
        if not usage["total_tokens"]:
            usage = {
                "input_tokens": estimate_tokens(context) + estimate_tokens(history_text) + estimate_tokens(question),
                "output_tokens": estimate_tokens(reply),
                "total_tokens": 0,
            }
            usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
            estimated = True
        llm_usage = record_usage(
            request_id=request_id,
            operation="chat_completion",
            mode=mode,
            model=settings.CHAT_MODEL,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            total_tokens=usage["total_tokens"],
            duration=llm_trace.get_duration(),
            estimated=estimated,
            metadata=_usage_metadata(question, reply, sources),
            conversation_id=conversation_id,
        )
        usage_records.append(llm_usage)
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=reply,
            sources=sources,
            usage=llm_usage,
            estimated=estimated,
        )

    # 2. Store in cache
    cache_service.set_cached_answer(question, reply, sources, mode)

    return {
        "reply": reply,
        "sources": sources,
        "source_images": _source_images(sources),
        "cache_hit": False,
        "usage": {
            "request_id": request_id,
            "records": usage_records,
            "total_tokens": sum(r["total_tokens"] for r in usage_records),
        },
    }


def answer_query_stream(
    question: str,
    mode: str,
    history: Optional[List[Dict[str, str]]] = None,
    conversation_id: str | None = None,
    user_id: int | None = None,
):
    _check_prompt_injection(question)
    if is_over_budget(conversation_id):
        raise ValueError(f"Local cost budget of ${settings.LOCAL_COST_BUDGET} has been exceeded.")
        
    request_id = new_request_id()
    history_text = _prepare_history(history)

    intent = _classify_light_intent(question)
    if intent == "empty":
        reply = "Please enter a question."
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=reply,
            sources=[],
            usage={"total_tokens": 0, "estimated": True},
        )
        yield reply
        return
    if intent == "chit_chat":
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=CHIT_CHAT_REPLY,
            sources=[],
            usage={"total_tokens": 0, "estimated": True},
        )
        yield CHIT_CHAT_REPLY
        return
    if intent == "out_of_scope":
        reply = _out_of_scope_reply(question)
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=reply,
            sources=[],
            usage={"total_tokens": 0, "estimated": True},
        )
        yield reply
        return

    # 0. Topic guard check
    blocked, guard_reason = check_topic_guard(question, mode)
    if blocked:
        reply = f"Blocked: {guard_reason}"
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=reply,
            sources=[],
            usage={"total_tokens": 0, "estimated": True},
        )
        yield reply
        return

    # 1. Semantic cache check
    cached_result = cache_service.get_cached_answer(question, mode)
    if cached_result:
        reply, sources = cached_result
        record_usage(
            request_id=request_id,
            operation="cache_hit",
            mode=mode,
            model="cache",
            total_tokens=0,
            estimated=True,
            conversation_id=conversation_id,
        )
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=reply,
            sources=sources,
            usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "estimated": True},
        )
        yield reply
        return

    context, sources, _usage = retrieve_context(question, mode, request_id, conversation_id)
    if not context:
        reply = _no_context_answer(question, mode)
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=reply,
            sources=[],
            usage=_usage,
        )
        yield reply
        return

    chain = _build_chain(mode, streaming=True, user_id=user_id)
    full_reply: List[str] = []
    for chunk in chain.stream(
        {
            "context": context,
            "history": history_text,
            "question": question,
            "no_context_answer": _no_context_answer(question, mode),
        }
    ):
        text_chunk = _content_to_text(chunk.content if hasattr(chunk, "content") else chunk)
        full_reply.append(text_chunk)
        yield text_chunk

    # 2. Store in cache
    reply = "".join(full_reply)
    cache_service.set_cached_answer(question, reply, sources, mode)
    llm_usage = record_usage(
        request_id=request_id,
        operation="chat_completion",
        mode=mode,
        model=settings.CHAT_MODEL,
        input_tokens=estimate_tokens(context) + estimate_tokens(history_text) + estimate_tokens(question),
        output_tokens=estimate_tokens(reply),
        duration=0,
        estimated=True,
        metadata=_usage_metadata(question, reply, sources),
        conversation_id=conversation_id,
    )
    _record_audit_from_usage(
        conversation_id=conversation_id,
        request_id=request_id,
        mode=mode,
        question=question,
        answer=reply,
        sources=sources,
        usage=llm_usage,
    )


# Override Vietnamese fallback text. Python resolves globals at call time, so
# answer_query and answer_query_stream use this cleaner version too.
def _no_context_answer(question: str, mode: str) -> str:
    if _prefers_vietnamese(question):
        return (
            "Mình chưa tìm thấy nội dung phù hợp trong kho tài liệu hiện tại. "
            f"Bạn đang hỏi ở chế độ {mode}; hãy kiểm tra tài liệu đã được upload đúng chế độ chưa."
        )
    return (
        f"{NO_CONTEXT_ANSWER} You are asking in {mode} mode; "
        "check that the document was uploaded to the same mode."
    )


def _stream_token(text: str) -> dict[str, object]:
    return {"event": "token", "data": {"text": text}}


def _stream_metadata(
    *,
    request_id: str,
    conversation_id: str | None,
    sources: list[dict] | None,
    usage_records: list[dict],
    source_images: list[dict] | None = None,
    cache_hit: bool = False,
    blocked: bool = False,
    guardrail: dict[str, str] | None = None,
    source_type: str = "internal",
    external_sources: list[dict] | None = None,
    web_search_offered: bool = False,
    web_search_performed: bool = False,
    suggestion: str | None = None,
) -> dict[str, object]:
    data: dict[str, object] = {
        "request_id": request_id,
        "conversation_id": conversation_id,
        "sources": sources or [],
        "source_images": source_images if source_images is not None else _source_images(sources),
        "usage": {
            "input_tokens": _sum_tokens(usage_records, "input_tokens"),
            "output_tokens": _sum_tokens(usage_records, "output_tokens"),
            "total_tokens": _sum_tokens(usage_records, "total_tokens"),
            "cached": cache_hit,
            "estimated": any(bool(record.get("estimated")) for record in usage_records),
            "records": usage_records,
        },
        "cache_hit": cache_hit,
        "blocked": blocked,
        "source_type": source_type,
        "external_sources": external_sources or [],
        "web_search_offered": web_search_offered,
        "web_search_performed": web_search_performed,
    }
    if suggestion:
        data["suggestion"] = suggestion
    if guardrail:
        data["guardrail"] = guardrail
    return {"event": "metadata", "data": data}


def _stream_done() -> dict[str, object]:
    return {"event": "done", "data": {}}


def _sum_tokens(records: list[dict], key: str) -> int:
    """Sum token counts from a list of usage records. Handles None/missing keys safely."""
    return sum(int(r.get(key) or 0) for r in records)


def _web_search_offer(question: str) -> tuple[str, str]:
    if _prefers_vietnamese(question):
        return (
            "Mình chưa tìm thấy thông tin phù hợp trong tài liệu nội bộ.",
            "Bạn có muốn mình tìm kiếm và tham khảo thêm nguồn trên Internet không?",
        )
    return (
        "I could not find enough relevant information in the internal documents.",
        "Would you like me to search and reference external web sources?",
    )


def _format_external_sources(sources: list[dict]) -> str:
    if not sources:
        return ""
    lines = ["\n\nNguồn Internet tham khảo:"]
    for idx, source in enumerate(sources[:5], start=1):
        title = source.get("title") or "External source"
        url = source.get("url") or ""
        lines.append(f"[{idx}] {title} - {url}")
    return "\n".join(lines)


async def answer_query_hybrid(
    question: str,
    mode: str,
    history: Optional[List[Dict[str, str]]] = None,
    conversation_id: str | None = None,
    user_id: int | None = None,
    allow_web_search: bool = False,
):
    _check_prompt_injection(question)
    request_id = new_request_id()
    history_text = _prepare_history(history)
    
    logger.info(f"[HYBRID RAG] request_id={request_id} user_id={user_id} question='{question[:100]}...' allow_web_search={allow_web_search}")

    intent = _classify_light_intent(question)
    if intent in {"empty", "chit_chat", "out_of_scope"}:
        logger.info(f"[HYBRID RAG] request_id={request_id} intent={intent} -> skipping RAG, using direct answer")
        base = answer_query(question, mode, history, conversation_id, user_id)
        base.setdefault("source_type", "none")
        base.setdefault("external_sources", [])
        base.setdefault("web_search_offered", False)
        base.setdefault("web_search_performed", False)
        return base

    blocked, guard_reason = check_topic_guard(question, mode)
    if blocked:
        logger.warning(f"[HYBRID RAG] request_id={request_id} BLOCKED: {guard_reason}")
        reply = f"Blocked: {guard_reason}"
        return {
            "reply": reply,
            "sources": [],
            "external_sources": [],
            "source_type": "none",
            "cache_hit": False,
            "blocked": True,
            "web_search_offered": False,
            "web_search_performed": False,
            "usage": {"request_id": request_id, "records": [], "total_tokens": 0},
        }

    usage_records: list[dict[str, Any]] = []
    context, sources, retrieval_usage = retrieve_context(question, mode, request_id, conversation_id)
    usage_records.append(retrieval_usage)
    
    logger.info(f"[HYBRID RAG] request_id={request_id} retrieved context_length={len(context)} sources_count={len(sources)}")

    if context:
        logger.info(f"[HYBRID RAG] request_id={request_id} USING INTERNAL DOCS (found {len(sources)} sources)")
        with trace_span("hybrid_internal_generation", request_id=request_id, mode=mode) as llm_trace:
            chain = _build_chain(mode, user_id=user_id)
            
            # Log which model is being used
            try:
                from app.services.model_router_service import ModelRouter
                if user_id:
                    router = ModelRouter(user_id)
                    selection = router.select()
                    if selection:
                        logger.info(f"[HYBRID RAG] request_id={request_id} user_id={user_id} using MODEL: {selection.model_name} (provider={selection.provider}, strategy={router.strategy})")
                    else:
                        logger.warning(f"[HYBRID RAG] request_id={request_id} user_id={user_id} NO MODEL SELECTED, falling back to system default")
                else:
                    logger.info(f"[HYBRID RAG] request_id={request_id} no user_id, using system default model")
            except Exception as e:
                logger.warning(f"[HYBRID RAG] request_id={request_id} failed to log model info: {e}")
            
            response = chain.invoke(
                {
                    "context": context,
                    "history": history_text,
                    "question": question,
                    "no_context_answer": _no_context_answer(question, mode),
                }
            )
            reply = response.content if hasattr(response, "content") else str(response)
            
            # Get actual model name from response metadata if available
            actual_model = settings.CHAT_MODEL
            if hasattr(response, "response_metadata"):
                actual_model = response.response_metadata.get("model_name", actual_model)
            
            llm_usage = record_usage(
                request_id=request_id,
                operation="chat_completion",
                mode=mode,
                model=actual_model,
                input_tokens=estimate_tokens(context) + estimate_tokens(history_text) + estimate_tokens(question),
                output_tokens=estimate_tokens(reply),
                duration=llm_trace.get_duration(),
                estimated=True,
                metadata={**_usage_metadata(question, reply, sources), "source_type": "internal"},
                conversation_id=conversation_id,
            )
            usage_records.append(llm_usage)
            logger.info(f"[HYBRID RAG] request_id={request_id} internal answer generated, tokens={llm_usage.get('total_tokens')}")
        cache_service.set_cached_answer(question, reply, sources, mode)
        return {
            "reply": reply,
            "sources": sources,
            "source_images": _source_images(sources),
            "external_sources": [],
            "source_type": "internal",
            "cache_hit": False,
            "web_search_offered": False,
            "web_search_performed": False,
            "usage": {
                "request_id": request_id,
                "records": usage_records,
                "total_tokens": _sum_tokens(usage_records, "total_tokens"),
            },
        }

    if not allow_web_search:
        logger.info(f"[HYBRID RAG] request_id={request_id} NO INTERNAL CONTEXT, offering web search")
        reply, suggestion = _web_search_offer(question)
        return {
            "reply": reply,
            "sources": [],
            "external_sources": [],
            "source_type": "none",
            "cache_hit": False,
            "web_search_offered": True,
            "web_search_performed": False,
            "suggestion": suggestion,
            "usage": {
                "request_id": request_id,
                "records": usage_records,
                "total_tokens": _sum_tokens(usage_records, "total_tokens"),
            },
        }

    logger.info(f"[HYBRID RAG] request_id={request_id} NO INTERNAL CONTEXT, performing web search")
    try:
        from app.services.web_search_service import create_web_search_service

        web_service = create_web_search_service()
        web_result = await web_service.search_with_cache(question, user_id=user_id)
        external_sources = web_result.get("sources") or web_result.get("results") or []
        reply = str(web_result.get("answer") or "Không tìm thấy kết quả phù hợp trên Internet.")
        if external_sources:
            reply = reply + _format_external_sources(external_sources)
        logger.info(f"[HYBRID RAG] request_id={request_id} web search completed, found {len(external_sources)} sources, cached={web_result.get('cached')}")
        return {
            "reply": reply,
            "sources": [],
            "external_sources": external_sources,
            "source_type": "external_web",
            "cache_hit": bool(web_result.get("cached")),
            "web_search_offered": False,
            "web_search_performed": True,
            "usage": {
                "request_id": request_id,
                "records": usage_records,
                "total_tokens": _sum_tokens(usage_records, "total_tokens"),
            },
        }
    except Exception as exc:
        logger.exception(f"[HYBRID RAG] request_id={request_id} web search FAILED: {exc}")
        reply = f"Không thể tìm kiếm Internet lúc này: {exc}" if _prefers_vietnamese(question) else f"Web search is unavailable right now: {exc}"
        return {
            "reply": reply,
            "sources": [],
            "external_sources": [],
            "source_type": "none",
            "cache_hit": False,
            "web_search_offered": False,
            "web_search_performed": False,
            "usage": {
                "request_id": request_id,
                "records": usage_records,
                "total_tokens": _sum_tokens(usage_records, "total_tokens"),
            },
        }


async def answer_query_stream_events_hybrid(
    question: str,
    mode: str,
    history: Optional[List[Dict[str, str]]] = None,
    conversation_id: str | None = None,
    user_id: int | None = None,
    allow_web_search: bool = False,
):
    """Stream hybrid RAG responses while preserving internal-first retrieval.

    This intentionally does not call answer_query_hybrid(), because that function
    blocks until the full LLM answer is available. Internal-document answers must
    stream token-by-token from the selected user model/router.
    """
    _check_prompt_injection(question)
    if is_over_budget(conversation_id):
        raise ValueError(f"Local cost budget of ${settings.LOCAL_COST_BUDGET} has been exceeded.")

    request_id = new_request_id()
    history_text = _prepare_history(history)
    usage_records: list[dict[str, Any]] = []

    logger.info(
        "[HYBRID STREAM] request_id=%s user_id=%s question='%s...' allow_web_search=%s",
        request_id,
        user_id,
        question[:100],
        allow_web_search,
    )

    intent = _classify_light_intent(question)
    if intent in {"empty", "chit_chat", "out_of_scope"}:
        logger.info("[HYBRID STREAM] request_id=%s intent=%s -> using non-RAG fallback", request_id, intent)
        result = await answer_query_hybrid(question, mode, history, conversation_id, user_id, allow_web_search)
        yield _stream_token(str(result.get("reply") or ""))
        yield _stream_metadata(
            request_id=str(result.get("usage", {}).get("request_id") or request_id),
            conversation_id=conversation_id,
            sources=result.get("sources") or [],
            usage_records=result.get("usage", {}).get("records") or [],
            cache_hit=bool(result.get("cache_hit")),
            blocked=bool(result.get("blocked")),
            source_type=str(result.get("source_type") or "none"),
            external_sources=result.get("external_sources") or [],
            web_search_offered=bool(result.get("web_search_offered")),
            web_search_performed=bool(result.get("web_search_performed")),
            suggestion=result.get("suggestion"),
        )
        yield _stream_done()
        return

    blocked, guard_reason = check_topic_guard(question, mode)
    if blocked:
        reply = f"Blocked: {guard_reason}"
        logger.warning("[HYBRID STREAM] request_id=%s blocked=%s", request_id, guard_reason)
        yield _stream_token(reply)
        yield _stream_metadata(
            request_id=request_id,
            conversation_id=conversation_id,
            sources=[],
            usage_records=[],
            cache_hit=False,
            blocked=True,
            source_type="none",
            external_sources=[],
            web_search_offered=False,
            web_search_performed=False,
        )
        yield _stream_done()
        return

    cached_result = cache_service.get_cached_answer(question, mode)
    if cached_result:
        reply, sources = cached_result
        logger.info("[HYBRID STREAM] request_id=%s CACHE HIT sources_count=%s", request_id, len(sources))
        usage_records.append(
            record_usage(
                request_id=request_id,
                operation="cache_hit",
                mode=mode,
                model="cache",
                total_tokens=0,
                estimated=True,
                conversation_id=conversation_id,
            )
        )
        yield _stream_token(reply)
        yield _stream_metadata(
            request_id=request_id,
            conversation_id=conversation_id,
            sources=sources,
            usage_records=usage_records,
            cache_hit=True,
            blocked=False,
            source_type="internal",
            external_sources=[],
            web_search_offered=False,
            web_search_performed=False,
        )
        yield _stream_done()
        return

    context, sources, retrieval_usage = retrieve_context(question, mode, request_id, conversation_id)
    usage_records.append(retrieval_usage)
    logger.info(
        "[HYBRID STREAM] request_id=%s retrieved context_length=%s sources_count=%s",
        request_id,
        len(context),
        len(sources),
    )

    if context:
        logger.info("[HYBRID STREAM] request_id=%s USING INTERNAL DOCS", request_id)
        chain = _build_chain(mode, streaming=True, user_id=user_id)
        full_reply: list[str] = []
        actual_model = settings.CHAT_MODEL

        for chunk in chain.stream(
            {
                "context": context,
                "history": history_text,
                "question": question,
                "no_context_answer": _no_context_answer(question, mode),
            }
        ):
            text_chunk = _content_to_text(chunk.content if hasattr(chunk, "content") else chunk)
            if hasattr(chunk, "response_metadata"):
                actual_model = chunk.response_metadata.get("model_name", actual_model)
            if text_chunk:
                full_reply.append(text_chunk)
                yield _stream_token(text_chunk)

        reply = "".join(full_reply)
        cache_service.set_cached_answer(question, reply, sources, mode)
        llm_usage = record_usage(
            request_id=request_id,
            operation="chat_completion",
            mode=mode,
            model=actual_model,
            input_tokens=estimate_tokens(context) + estimate_tokens(history_text) + estimate_tokens(question),
            output_tokens=estimate_tokens(reply),
            duration=0,
            estimated=True,
            metadata={**_usage_metadata(question, reply, sources), "source_type": "internal"},
            conversation_id=conversation_id,
        )
        usage_records.append(llm_usage)
        logger.info("[HYBRID STREAM] request_id=%s DONE internal tokens=%s", request_id, llm_usage.get("total_tokens"))
        yield _stream_metadata(
            request_id=request_id,
            conversation_id=conversation_id,
            sources=sources,
            usage_records=usage_records,
            cache_hit=False,
            blocked=False,
            source_type="internal",
            external_sources=[],
            web_search_offered=False,
            web_search_performed=False,
        )
        yield _stream_done()
        return

    if not allow_web_search:
        logger.info("[HYBRID STREAM] request_id=%s NO INTERNAL CONTEXT -> offering web search", request_id)
        reply, suggestion = _web_search_offer(question)
        yield _stream_token(reply)
        yield _stream_metadata(
            request_id=request_id,
            conversation_id=conversation_id,
            sources=[],
            usage_records=usage_records,
            cache_hit=False,
            blocked=False,
            source_type="none",
            external_sources=[],
            web_search_offered=True,
            web_search_performed=False,
            suggestion=suggestion,
        )
        yield _stream_done()
        return

    logger.info("[HYBRID STREAM] request_id=%s NO INTERNAL CONTEXT -> web search", request_id)
    
    try:
        from app.services.web_search_service import create_web_search_service

        web_service = create_web_search_service()
        web_result = await web_service.search_with_cache(question, user_id=user_id)
        
        external_sources = web_result.get("sources") or web_result.get("results") or []
        reply = str(web_result.get("answer") or "Không tìm thấy kết quả phù hợp trên Internet.")
        if external_sources:
            reply = reply + _format_external_sources(external_sources)
        
        logger.info(f"[HYBRID STREAM] request_id={request_id} web search completed, found {len(external_sources)} sources, cached={web_result.get('cached')}")
        
        yield _stream_token(reply)
        yield _stream_metadata(
            request_id=request_id,
            conversation_id=conversation_id,
            sources=[],
            usage_records=usage_records,
            cache_hit=bool(web_result.get("cached")),
            blocked=False,
            source_type="external_web",
            external_sources=external_sources,
            web_search_offered=False,
            web_search_performed=True,
            suggestion=None,
        )
        yield _stream_done()
    except Exception as exc:
        logger.exception(f"[HYBRID STREAM] request_id={request_id} web search FAILED: {exc}")
        reply = f"Không thể tìm kiếm Internet lúc này: {exc}" if _prefers_vietnamese(question) else f"Web search is unavailable right now: {exc}"
        yield _stream_token(reply)
        yield _stream_metadata(
            request_id=request_id,
            conversation_id=conversation_id,
            sources=[],
            usage_records=usage_records,
            cache_hit=False,
            blocked=False,
            source_type="none",
            external_sources=[],
            web_search_offered=False,
            web_search_performed=False,
            suggestion=None,
        )
        yield _stream_done()


def answer_query_stream_events(
    question: str,
    mode: str,
    history: Optional[List[Dict[str, str]]] = None,
    conversation_id: str | None = None,
    user_id: int | None = None,
):
    _check_prompt_injection(question)
    request_id = new_request_id()
    history_text = _prepare_history(history)

    intent = _classify_light_intent(question)
    if intent == "empty":
        reply = "Please enter a question."
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=reply,
            sources=[],
            usage={"total_tokens": 0, "estimated": True},
        )
        yield _stream_token(reply)
        yield _stream_metadata(
            request_id=request_id,
            conversation_id=conversation_id,
            sources=[],
            usage_records=[],
        )
        yield _stream_done()
        return

    if intent == "chit_chat":
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=CHIT_CHAT_REPLY,
            sources=[],
            usage={"total_tokens": 0, "estimated": True},
        )
        yield _stream_token(CHIT_CHAT_REPLY)
        yield _stream_metadata(
            request_id=request_id,
            conversation_id=conversation_id,
            sources=[],
            usage_records=[],
        )
        yield _stream_done()
        return

    if intent == "out_of_scope":
        reply = _out_of_scope_reply(question)
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=reply,
            sources=[],
            usage={"total_tokens": 0, "estimated": True},
        )
        yield _stream_token(reply)
        yield _stream_metadata(
            request_id=request_id,
            conversation_id=conversation_id,
            sources=[],
            usage_records=[],
            blocked=True,
            guardrail={
                "type": "out_of_scope",
                "reason": "question does not match indexed knowledge base",
            },
        )
        yield _stream_done()
        return

    blocked, guard_reason = check_topic_guard(question, mode)
    if blocked:
        reply = f"Blocked: {guard_reason}"
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=reply,
            sources=[],
            usage={"total_tokens": 0, "estimated": True},
        )
        yield _stream_token(reply)
        yield _stream_metadata(
            request_id=request_id,
            conversation_id=conversation_id,
            sources=[],
            usage_records=[],
            blocked=True,
        )
        yield _stream_done()
        return

    cached_result = cache_service.get_cached_answer(question, mode)
    if cached_result:
        reply, sources = cached_result
        cache_usage = record_usage(
            request_id=request_id,
            operation="cache_hit",
            mode=mode,
            model="cache",
            total_tokens=0,
            estimated=True,
            conversation_id=conversation_id,
        )
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=reply,
            sources=sources,
            usage=cache_usage,
        )
        yield _stream_token(reply)
        yield _stream_metadata(
            request_id=request_id,
            conversation_id=conversation_id,
            sources=sources,
            usage_records=[cache_usage],
            cache_hit=True,
        )
        yield _stream_done()
        return

    context, sources, retrieval_usage = retrieve_context(question, mode, request_id, conversation_id)
    if not context:
        reply = _no_context_answer(question, mode)
        _record_audit_from_usage(
            conversation_id=conversation_id,
            request_id=request_id,
            mode=mode,
            question=question,
            answer=reply,
            sources=[],
            usage=retrieval_usage,
        )
        yield _stream_token(reply)
        yield _stream_metadata(
            request_id=request_id,
            conversation_id=conversation_id,
            sources=[],
            usage_records=[retrieval_usage],
        )
        yield _stream_done()
        return

    chain = _build_chain(mode, streaming=True, user_id=user_id)
    full_reply: list[str] = []
    for chunk in chain.stream(
        {
            "context": context,
            "history": history_text,
            "question": question,
            "no_context_answer": _no_context_answer(question, mode),
        }
    ):
        text_chunk = _content_to_text(chunk.content if hasattr(chunk, "content") else chunk)
        full_reply.append(text_chunk)
        yield _stream_token(text_chunk)

    reply = "".join(full_reply)
    cache_service.set_cached_answer(question, reply, sources, mode)
    llm_usage = record_usage(
        request_id=request_id,
        operation="chat_completion",
        mode=mode,
        model=settings.CHAT_MODEL,
        input_tokens=estimate_tokens(context) + estimate_tokens(history_text) + estimate_tokens(question),
        output_tokens=estimate_tokens(reply),
        duration=0,
        estimated=True,
        metadata=_usage_metadata(question, reply, sources),
        conversation_id=conversation_id,
    )
    _record_audit_from_usage(
        conversation_id=conversation_id,
        request_id=request_id,
        mode=mode,
        question=question,
        answer=reply,
        sources=sources,
        usage=llm_usage,
    )
    yield _stream_metadata(
        request_id=request_id,
        conversation_id=conversation_id,
        sources=sources,
        usage_records=[retrieval_usage, llm_usage],
    )
    yield _stream_done()
