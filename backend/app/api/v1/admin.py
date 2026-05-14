"""Admin APIs for topic guards, QA cache, and retrieval health.

All routes in this module require a valid JWT for a user with the admin role.
"""

from typing import Literal, Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from app.core.auth import get_current_admin, TokenData

from app.services import topic_guard_service
from app.services.rag.cache_service import cache_service
from app.services.rag.bm25_search import BM25Searcher
from app.services.rag.consistency import check_vector_consistency
from app.services.rag.reranker import reranker
from app.services.rag.vector_store import vector_store_health
from app.core.config import settings

router = APIRouter()




# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class GuardCreate(BaseModel):
    """Request model for creating a new topic guard rule."""
    pattern: str = Field(..., min_length=1, description="Keyword or regex pattern to block", example="salary")
    mode: Optional[Literal["Internal", "External"]] = Field(None, description="Mode to apply the guard to. If None, applies to all modes.")
    reason: Optional[str] = Field(None, min_length=1, description="Reason shown to the user when blocked", example="This topic is restricted.")
    is_regex: bool = Field(False, description="Whether the pattern should be treated as a regular expression")

    class Config:
        json_schema_extra = {
            "example": {
                "pattern": "confidential",
                "mode": "Internal",
                "reason": "Confidential information cannot be discussed here.",
                "is_regex": False
            }
        }


class GuardToggle(BaseModel):
    """Request model for toggling a guard's active status."""
    is_active: bool = Field(..., description="Set to true to enable the guard, false to disable it")

    class Config:
        json_schema_extra = {
            "example": {"is_active": True}
        }


# ---------------------------------------------------------------------------
# Topic Guard endpoints
# ---------------------------------------------------------------------------

class GuardResponse(BaseModel):
    """Response model for a topic guard rule."""
    id: int
    pattern: str
    mode: Optional[Literal["Internal", "External"]]
    reason: Optional[str]
    is_regex: bool
    is_active: bool
    created_at: Optional[str]

    class Config:
        json_schema_extra = {
            "example": {
                "id": 1,
                "pattern": "salary",
                "mode": "Internal",
                "reason": "Restricted topic",
                "is_regex": False,
                "is_active": True,
                "created_at": "2024-05-01T10:00:00Z"
            }
        }

class GuardListResponse(BaseModel):
    """Response model for listing topic guards."""
    guards: List[GuardResponse]

@router.get("/topic-guards", response_model=GuardListResponse, dependencies=[Depends(get_current_admin)])
def list_topic_guards():
    """
    List all topic guard rules.
    
    Returns a list of all configured patterns used to block restricted topics.
    """
    guards = topic_guard_service.list_guards()
    for g in guards:
        if g.get("created_at"):
            g["created_at"] = str(g["created_at"])
    return {"guards": guards}


@router.post("/topic-guards", status_code=201, response_model=GuardResponse, dependencies=[Depends(get_current_admin)])
def create_topic_guard(body: GuardCreate):
    """
    Add a new topic guard rule.
    
    Allows administrators to define keywords or regex patterns that the AI should refuse to answer.
    """
    guard = topic_guard_service.add_guard(
        pattern=body.pattern,
        mode=body.mode,
        reason=body.reason,
        is_regex=body.is_regex,
    )
    if guard.get("created_at"):
        guard["created_at"] = str(guard["created_at"])
    return guard


@router.patch("/topic-guards/{guard_id}", response_model=GuardResponse, dependencies=[Depends(get_current_admin)])
def update_topic_guard(guard_id: int, body: GuardToggle):
    """
    Toggle a topic guard rule on or off.
    
    Updates the active status of an existing guard rule.
    """
    updated = topic_guard_service.toggle_guard(guard_id, body.is_active)
    if updated is None:
        raise HTTPException(status_code=404, detail="Guard not found")
    if updated.get("created_at"):
        updated["created_at"] = str(updated["created_at"])
    return updated


class DeleteGuardResponse(BaseModel):
    """Response model for deleting a guard."""
    deleted: int

@router.delete("/topic-guards/{guard_id}", response_model=DeleteGuardResponse, dependencies=[Depends(get_current_admin)])
def delete_topic_guard(guard_id: int):
    """
    Permanently delete a topic guard rule.
    
    Removes the rule from the database.
    """
    deleted = topic_guard_service.delete_guard(guard_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Guard not found")
    return {"deleted": guard_id}


# ---------------------------------------------------------------------------
# QA Cache endpoints
# ---------------------------------------------------------------------------

class CacheStatsResponse(BaseModel):
    """Response model for QA cache statistics."""
    total_entries: int = Field(..., description="Total number of cached Q&A pairs")
    total_hits: int = Field(..., description="Total number of times cache was hit")
    hit_rate: float = Field(..., description="Cache hit rate (0.0 to 1.0)")
    top_questions: List[Dict[str, Any]] = Field(..., description="Most frequently hit cached questions")

    class Config:
        json_schema_extra = {
            "example": {
                "total_entries": 1000,
                "total_hits": 5000,
                "hit_rate": 0.83,
                "top_questions": [
                    {"question": "What is the leave policy?", "hits": 150}
                ]
            }
        }

@router.get("/qa-cache/stats", response_model=CacheStatsResponse, dependencies=[Depends(get_current_admin)])
def get_cache_stats():
    """
    Return QA cache statistics.
    
    Provides insights into the effectiveness of the semantic cache, including total entries,
    hit rate, and the most common cached queries.
    """
    return cache_service.get_stats()


class ClearCacheResponse(BaseModel):
    """Response model for clearing the cache."""
    deleted: int = Field(..., description="Number of entries removed")
    message: str = Field(..., description="Status message")

@router.delete("/qa-cache", response_model=ClearCacheResponse, dependencies=[Depends(get_current_admin)])
def clear_cache():
    """
    Delete all entries from the QA cache.
    
    Useful when the underlying knowledge base has changed significantly and cached answers are outdated.
    """
    count = cache_service.clear_cache()
    return {"deleted": count, "message": f"Cleared {count} cache entries."}


class RevokedTokensCleanupResponse(BaseModel):
    deleted: int = Field(..., description="Number of expired token blacklist entries removed")

@router.delete("/revoked-tokens/expired", response_model=RevokedTokensCleanupResponse, dependencies=[Depends(get_current_admin)])
def cleanup_expired_revoked_tokens():
    """Remove expired entries from the revoked_tokens table."""
    from datetime import datetime, timezone
    from app.core.database import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM revoked_tokens WHERE expires_at < %s",
                (datetime.now(timezone.utc),)
            )
            deleted = cur.rowcount
    return {"deleted": deleted}


@router.get("/health/retrieval", dependencies=[Depends(get_current_admin)])
def retrieval_health():
    return {
        "reranker": reranker.health(),
        "vector_store": vector_store_health(),
        "bm25_cache": BM25Searcher.cache_status(),
        "redis": cache_service.ping(),
    }


@router.get("/health/consistency", dependencies=[Depends(get_current_admin)])
def consistency_health(auto_rebuild: bool = False):
    return check_vector_consistency(auto_rebuild=auto_rebuild)
