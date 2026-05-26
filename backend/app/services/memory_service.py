"""
memory_service.py — AgentMemory integration for conversation persistence.

Provides PostgreSQL-based conversation memory with recall/store/clear operations.
Integrates with query_engine to provide conversation context for RAG queries.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.core.database import get_conn

logger = logging.getLogger(__name__)


def store_conversation_turn(
    conversation_id: str, role: str, content: str, user_id: int | None = None
) -> None:
    if not conversation_id or not settings.DATABASE_URL:
        logger.debug("Skipping memory storage: no conversation_id or DATABASE_URL")
        return

    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO conversation_memory (conversation_id, role, content, user_id)
                VALUES (%s, %s, %s, %s)
                """,
                (conversation_id, role, content, user_id),
            )
        logger.debug("Stored %s message in conversation %s", role, conversation_id)
    except Exception as e:
        logger.error("Failed to store memory: %s", e)


def recall_conversation_context(
    conversation_id: str,
    user_id: int,
    limit: int = 5,
) -> str:
    if not conversation_id or not settings.DATABASE_URL:
        return ""

    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT role, content FROM conversation_memory
                WHERE conversation_id = %s AND user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (conversation_id, user_id, limit),
            )
            rows = cursor.fetchall()

        if not rows:
            return ""

        lines = ["Recent conversation:"]
        for role, content in reversed(rows):
            preview = content[:100]
            suffix = "..." if len(content) > 100 else ""
            lines.append(f"• {role}: {preview}{suffix}")

        context = "\n".join(lines)
        logger.debug("Recalled %d chars of context for conversation %s", len(context), conversation_id)
        return context
    except Exception as e:
        logger.error("Failed to recall memory: %s", e)
        return ""


def clear_conversation_memory(conversation_id: str | None = None) -> int:
    if not settings.DATABASE_URL:
        return 0

    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            if conversation_id:
                cursor.execute(
                    "DELETE FROM conversation_memory WHERE conversation_id = %s",
                    (conversation_id,),
                )
            else:
                cursor.execute("DELETE FROM conversation_memory")
            deleted = cursor.rowcount

        logger.info("Cleared %d memory records for conversation_id=%s", deleted, conversation_id or "ALL")
        return deleted
    except Exception as e:
        logger.error("Failed to clear memory: %s", e)
        return 0


def get_conversation_history(conversation_id: str, user_id: int, limit: int = 100) -> list[dict[str, Any]]:
    """Return messages for a conversation, scoped to the owning user."""
    if not conversation_id or not settings.DATABASE_URL:
        return []

    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT role, content, created_at FROM conversation_memory
                WHERE conversation_id = %s AND user_id = %s
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (conversation_id, user_id, limit),
            )
            rows = cursor.fetchall()

        return [
            {
                "role": role,
                "content": content,
                "timestamp": timestamp.isoformat() if timestamp else None,
            }
            for role, content, timestamp in rows
        ]
    except Exception as e:
        logger.error("Failed to get conversation history: %s", e)
        return []


def list_user_conversations(user_id: int, limit: int = 30) -> list[dict[str, Any]]:
    """
    Return the most recent conversations for a user.
    Each item has: conversation_id, title (first user message), last_at, message_count.
    """
    if not settings.DATABASE_URL:
        return []

    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    conversation_id,
                    MIN(CASE WHEN role = 'user' THEN content END) AS title,
                    MAX(created_at) AS last_at,
                    COUNT(*) AS message_count
                FROM conversation_memory
                WHERE user_id = %s
                GROUP BY conversation_id
                ORDER BY last_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
            rows = cursor.fetchall()

        return [
            {
                "conversation_id": cid,
                "title": (title or "")[:80] if title else "New conversation",
                "last_at": last_at.isoformat() if last_at else None,
                "message_count": count,
            }
            for cid, title, last_at, count in rows
        ]
    except Exception as e:
        logger.error("Failed to list conversations: %s", e)
        return []
