import logging

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Dict, Any
from app.core.auth import get_current_admin, TokenData

logger = logging.getLogger(__name__)

from app.services.usage_tracker import (
    get_usage_summary,
    list_usage_records,
    reset_usage,
)
from app.services.chat_audit_service import export_chat_audit, list_conversation_summaries
from app.services.pricing_service import get_session_cost


router = APIRouter()


class UsageSummaryResponse(BaseModel):
    """Summary of token usage across all operations."""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_requests": 150,
                "total_tokens": 45000,
                "by_operation": {
                    "chat_completion": {"requests": 100, "tokens": 35000},
                    "document_embedding": {"requests": 50, "tokens": 10000}
                },
                "by_model": {
                    "gemini-1.5-flash": {"requests": 100, "tokens": 35000},
                    "text-embedding-004": {"requests": 50, "tokens": 10000}
                }
            }
        }
    )

    records: int = Field(..., description="Total number of usage records tracked")
    input_tokens: int = Field(..., description="Total input tokens")
    output_tokens: int = Field(..., description="Total output tokens")
    total_tokens: int = Field(..., description="Total tokens consumed across all operations")
    actual_tokens: int = Field(..., description="Tokens reported by providers")
    estimated_tokens: int = Field(..., description="Tokens estimated locally")
    by_operation: List[Dict[str, Any]] = Field(..., description="Token usage grouped by operation/model")
    

class UsageRecord(BaseModel):
    """Individual usage record for a single operation."""
    created_at: str
    request_id: str
    conversation_id: str | None = None
    operation: str
    mode: str | None
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated: bool
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UsageRecordsResponse(BaseModel):
    """List of usage records."""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "records": [
                    {
                        "request_id": "req_abc123",
                        "operation": "chat_completion",
                        "mode": "Internal",
                        "model": "gemini-1.5-flash",
                        "input_tokens": 250,
                        "output_tokens": 100,
                        "total_tokens": 350,
                        "estimated": False,
                        "timestamp": "2024-05-01T10:00:00Z",
                        "metadata": "{}"
                    }
                ]
            }
        }
    )

    records: List[UsageRecord]


class ClearUsageResponse(BaseModel):
    """Response for clearing usage records."""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "Usage records cleared",
                "deleted_records": 150
            }
        }
    )

    message: str
    deleted_records: int


class ConversationSummary(BaseModel):
    conversation_id: str
    turns: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    started_at: str
    last_at: str


class ConversationSummaryResponse(BaseModel):
    conversations: List[ConversationSummary]


class AuditExportResponse(BaseModel):
    records: List[Dict[str, Any]]


class SessionCostResponse(BaseModel):
    conversation_id: str
    total_cost_usd: float
    total_cost_vnd: int
    breakdown: List[Dict[str, Any]]


@router.get("/summary", response_model=UsageSummaryResponse)
async def usage_summary(current_user: TokenData = Depends(get_current_admin)):
    """
    Get aggregated token usage statistics.
    
    Returns a summary of total requests, total tokens, and breakdowns by operation type and model.
    """
    return get_usage_summary()


@router.get("/records", response_model=UsageRecordsResponse)
async def usage_records(
    limit: int = Query(50, ge=1, le=500, description="Maximum number of records to return"),
    current_user: TokenData = Depends(get_current_admin)
):
    """
    Retrieve recent usage records.
    
    Returns a list of individual usage records with token counts and metadata.
    """
    return {"records": list_usage_records(limit)}


@router.get("/conversations", response_model=ConversationSummaryResponse)
async def usage_conversations(
    limit: int = Query(100, ge=1, le=500, description="Maximum number of sessions to return"),
    current_user: TokenData = Depends(get_current_admin)
):
    """List token cost grouped by conversation/session."""
    return {"conversations": list_conversation_summaries(limit)}


@router.get("/audit/export", response_model=AuditExportResponse)
async def audit_export(
    conversation_id: str | None = Query(None, description="Optional conversation id filter"),
    limit: int = Query(1000, ge=1, le=5000, description="Maximum number of audit rows to return"),
    redact_pii: bool = Query(True, description="Redact common PII patterns from question and answer"),
    current_user: TokenData = Depends(get_current_admin)
):
    """Export question/answer audit log with token totals."""
    return {
        "records": export_chat_audit(
            conversation_id=conversation_id,
            limit=limit,
            redact_pii=redact_pii,
        )
    }


@router.get("/conversations/{conversation_id}/cost", response_model=SessionCostResponse)
async def conversation_cost(
    conversation_id: str,
    current_user: TokenData = Depends(get_current_admin)
):
    """Estimate token cost for one conversation based on editable model_pricing rows."""
    return get_session_cost(conversation_id)


@router.delete("", response_model=ClearUsageResponse)
async def clear_usage(current_user: TokenData = Depends(get_current_admin)):
    """
    Clear all usage tracking records.
    
    This operation permanently deletes all usage history from the database.
    """
    try:
        deleted_records = reset_usage()
    except Exception:
        logger.exception("Failed to clear usage records")
        raise HTTPException(status_code=500, detail="Failed to clear usage records.")
    return {"message": "Usage records cleared", "deleted_records": deleted_records}
