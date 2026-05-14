from __future__ import annotations

import json
from typing import Any

import psycopg2.extras

from app.core.config import settings
from app.core.database import get_conn
from app.services.pii_redactor import redact


def _ensure_chat_audit_table() -> None:
    with get_conn() as connection:
        with connection.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_audit (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    conversation_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    sources JSON NOT NULL DEFAULT '[]'::json,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    estimated BOOLEAN NOT NULL DEFAULT TRUE
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS chat_audit_conversation_id_idx ON chat_audit (conversation_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS chat_audit_created_at_idx ON chat_audit (created_at)")


def record_chat_audit(
    *,
    conversation_id: str,
    request_id: str,
    mode: str,
    question: str,
    answer: str,
    sources: list[dict[str, Any]] | None,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    estimated: bool,
) -> None:
    if not settings.DATABASE_URL:
        return
    _ensure_chat_audit_table()
    with get_conn() as connection:
        with connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chat_audit (
                    conversation_id, request_id, mode, question, answer, sources,
                    input_tokens, output_tokens, total_tokens, estimated
                )
                VALUES (%s, %s, %s, %s, %s, %s::json, %s, %s, %s, %s)
                """,
                (
                    conversation_id,
                    request_id,
                    mode,
                    question,
                    answer,
                    json.dumps(sources or [], ensure_ascii=False),
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    estimated,
                ),
            )


def list_conversation_summaries(limit: int = 100) -> list[dict[str, Any]]:
    if not settings.DATABASE_URL:
        return []
    _ensure_chat_audit_table()
    limit = min(max(limit, 1), 500)
    with get_conn() as connection:
        with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    conversation_id,
                    COUNT(*) AS turns,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    MIN(created_at) AS started_at,
                    MAX(created_at) AS last_at
                FROM chat_audit
                GROUP BY conversation_id
                ORDER BY last_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    return [
        {
            **dict(row),
            "started_at": row["started_at"].isoformat(),
            "last_at": row["last_at"].isoformat(),
        }
        for row in rows
    ]


def export_chat_audit(
    conversation_id: str | None = None,
    limit: int = 1000,
    redact_pii: bool = True,
) -> list[dict[str, Any]]:
    if not settings.DATABASE_URL:
        return []
    _ensure_chat_audit_table()
    limit = min(max(limit, 1), 5000)
    params: list[Any] = []
    where_sql = ""
    if conversation_id:
        where_sql = "WHERE conversation_id = %s"
        params.append(conversation_id)
    params.append(limit)

    with get_conn() as connection:
        with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT created_at, conversation_id, request_id, mode, question, answer,
                       sources, input_tokens, output_tokens, total_tokens, estimated
                FROM chat_audit
                {where_sql}
                ORDER BY id DESC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()
    records = [
        {
            **dict(row),
            "created_at": row["created_at"].isoformat(),
            "sources": row["sources"] or [],
        }
        for row in rows
    ]
    if redact_pii:
        for record in records:
            record["question"] = redact(record.get("question", ""))
            record["answer"] = redact(record.get("answer", ""))
    return records
