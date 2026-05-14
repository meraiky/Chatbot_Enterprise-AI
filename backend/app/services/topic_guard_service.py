"""
topic_guard_service.py — Admin-managed topic blocking.

Checks user questions against active patterns BEFORE any LLM call.
Supports plain substring match and full Python regex.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional, Tuple

from app.core.database import get_conn
from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public check API
# ---------------------------------------------------------------------------

def check_topic_guard(question: str, mode: str) -> Tuple[bool, Optional[str]]:
    """
    Return (blocked, reason).

    Checks active rules where mode matches or mode IS NULL (applies to both).
    Short-circuits on first match.
    """
    try:
        sql = """
            SELECT pattern, reason, is_regex
            FROM   topic_guard
            WHERE  is_active = TRUE
              AND  (mode IS NULL OR mode = %s)
            ORDER  BY id
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (mode,))
                rows = cur.fetchall()

        q_lower = question.lower()
        for pattern, reason, is_regex in rows:
            if is_regex:
                try:
                    if re.search(pattern, question, re.IGNORECASE):
                        logger.info("Topic blocked (regex): %.50s", question)
                        return True, reason or "This topic is restricted."
                except re.error:
                    logger.warning("Invalid regex in topic_guard: %s", pattern)
            else:
                if pattern.lower() in q_lower:
                    logger.info("Topic blocked (keyword): %.50s", question)
                    return True, reason or "This topic is restricted."

        return False, None

    except Exception:
        logger.exception("Error checking topic_guard")
        if settings.TOPIC_GUARD_FAIL_CLOSED:
            return True, "Policy guard temporarily unavailable. Please try again later."
        return False, None  # legacy fail-open for explicit override


# ---------------------------------------------------------------------------
# CRUD (used by admin API)
# ---------------------------------------------------------------------------

def list_guards() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, pattern, mode, reason, is_regex, is_active, created_at "
                "FROM topic_guard ORDER BY id"
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def add_guard(
    pattern: str,
    mode: Optional[str],
    reason: Optional[str],
    is_regex: bool,
) -> dict:
    sql = """
        INSERT INTO topic_guard (pattern, mode, reason, is_regex)
        VALUES (%s, %s, %s, %s)
        RETURNING id, pattern, mode, reason, is_regex, is_active, created_at
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (pattern, mode or None, reason or None, is_regex))
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
    return dict(zip(cols, row))


def toggle_guard(guard_id: int, is_active: bool) -> Optional[dict]:
    sql = """
        UPDATE topic_guard SET is_active = %s
        WHERE id = %s
        RETURNING id, pattern, mode, reason, is_regex, is_active, created_at
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (is_active, guard_id))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def delete_guard(guard_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM topic_guard WHERE id = %s RETURNING id", (guard_id,))
            return cur.fetchone() is not None
