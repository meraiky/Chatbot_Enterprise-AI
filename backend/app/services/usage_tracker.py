from __future__ import annotations

import contextlib
import json
import logging
import math
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg2.extras

from app.core.config import settings
from app.core.database import get_conn

logger = logging.getLogger(__name__)

# Module-level flag to ensure DDL runs only once per process
_postgres_table_ready = False


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4)) if text else 0


def new_request_id() -> str:
    return str(uuid.uuid4())


def _db_path() -> Path:
    path = Path(settings.TOKEN_USAGE_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect_sqlite() -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path())
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            request_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            mode TEXT,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            duration REAL NOT NULL DEFAULT 0.0,
            estimated INTEGER NOT NULL DEFAULT 0,
            metadata TEXT NOT NULL DEFAULT '{}',
            conversation_id TEXT
        )
        """
    )
    with contextlib.suppress(sqlite3.OperationalError):
        connection.execute("ALTER TABLE token_usage ADD COLUMN conversation_id TEXT")
    return connection


def _ensure_postgres_table() -> None:
    """Ensure token_usage table exists. Uses module-level flag to run DDL only once per process.
    
    CRITICAL FIX (C-1): Previously ran 6 DDL statements on EVERY record_usage() call.
    Now runs only once per process lifetime using _postgres_table_ready flag.
    """
    global _postgres_table_ready
    if _postgres_table_ready:
        return
    
    with get_conn() as connection, connection.cursor() as cur:
        cur.execute(
            """
                CREATE TABLE IF NOT EXISTS token_usage (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    request_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    mode TEXT,
                    provider TEXT NOT NULL DEFAULT 'google',
                    model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    duration DOUBLE PRECISION NOT NULL DEFAULT 0,
                    estimated BOOLEAN NOT NULL DEFAULT FALSE,
                    metadata JSON NOT NULL DEFAULT '{}'::json,
                    conversation_id TEXT
                )
                """
        )
        # N-7: Removed ALTER TABLE here — schema migration belongs in Alembic (003_qa_cache_token_columns.py).
        # Keeping duplicate DDL in application code creates confusion about the single source of truth.
        cur.execute(
            "CREATE INDEX IF NOT EXISTS token_usage_created_at_idx ON token_usage (created_at)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS token_usage_conversation_id_idx ON token_usage (conversation_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS token_usage_request_id_idx ON token_usage (request_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS token_usage_operation_idx ON token_usage (operation)"
        )
    
    _postgres_table_ready = True
    logger.info("PostgreSQL token_usage table initialized (DDL executed once)")


def _use_postgres() -> bool:
    return bool(settings.DATABASE_URL)


def _usage_value(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int):
            return value
    return 0


def normalize_usage(usage: dict[str, Any] | None) -> dict[str, int]:
    usage = usage or {}
    input_tokens = _usage_value(usage, "input_tokens", "prompt_tokens", "prompt_token_count")
    output_tokens = _usage_value(
        usage,
        "output_tokens",
        "completion_tokens",
        "candidates_token_count",
    )
    total_tokens = _usage_value(usage, "total_tokens", "total_token_count")
    if not total_tokens:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _metadata_payload(metadata: str | dict[str, Any]) -> str:
    if isinstance(metadata, str):
        return metadata or "{}"
    return json.dumps(metadata, ensure_ascii=False)


def _record_usage_postgres(payload: dict[str, Any]) -> None:
    _ensure_postgres_table()
    with get_conn() as connection, connection.cursor() as cur:
        cur.execute(
            """
                INSERT INTO token_usage (
                    created_at, request_id, operation, mode, provider, model,
                    input_tokens, output_tokens, total_tokens, duration, estimated, metadata,
                    conversation_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::json, %s)
                """,
            (
                payload["created_at"],
                payload["request_id"],
                payload["operation"],
                payload["mode"],
                payload["provider"],
                payload["model"],
                payload["input_tokens"],
                payload["output_tokens"],
                payload["total_tokens"],
                payload["duration"],
                payload["estimated"],
                payload["metadata"],
                payload["conversation_id"],
            ),
        )


def _record_usage_sqlite(payload: dict[str, Any]) -> None:
    with _connect_sqlite() as connection:
        connection.execute(
            """
            INSERT INTO token_usage (
                created_at, request_id, operation, mode, provider, model,
                input_tokens, output_tokens, total_tokens, duration, estimated, metadata,
                conversation_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["created_at"],
                payload["request_id"],
                payload["operation"],
                payload["mode"],
                payload["provider"],
                payload["model"],
                payload["input_tokens"],
                payload["output_tokens"],
                payload["total_tokens"],
                payload["duration"],
                int(payload["estimated"]),
                payload["metadata"],
                payload["conversation_id"],
            ),
        )


def record_usage(
    *,
    request_id: str,
    operation: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    duration: float = 0.0,
    mode: str | None = None,
    provider: str = "google",
    estimated: bool = False,
    metadata: str | dict[str, Any] = "{}",
    conversation_id: str | None = None,
) -> dict[str, Any]:
    if not total_tokens:
        total_tokens = input_tokens + output_tokens

    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "request_id": request_id,
        "operation": operation,
        "mode": mode,
        "provider": provider,
        "model": model,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "total_tokens": int(total_tokens),
        "duration": float(duration),
        "estimated": bool(estimated),
        "metadata": _metadata_payload(metadata),
        "conversation_id": conversation_id,
    }

    if _use_postgres():
        try:
            _record_usage_postgres(payload)
        except Exception:
            logger.exception("Failed to write token usage to PostgreSQL; falling back to SQLite")
            _record_usage_sqlite(payload)
    else:
        _record_usage_sqlite(payload)

    return {k: v for k, v in payload.items() if k != "metadata"}


def _get_usage_summary_postgres() -> dict[str, Any]:
    _ensure_postgres_table()
    with get_conn() as connection, connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
                SELECT
                    COUNT(*) AS records,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(CASE WHEN estimated THEN total_tokens ELSE 0 END), 0)
                        AS estimated_tokens,
                    COALESCE(SUM(CASE WHEN NOT estimated THEN total_tokens ELSE 0 END), 0)
                        AS actual_tokens
                FROM token_usage
                """
        )
        row = cur.fetchone()
        cur.execute(
            """
                SELECT operation, model, estimated, COUNT(*) AS records,
                       COALESCE(SUM(total_tokens), 0) AS total_tokens
                FROM token_usage
                GROUP BY operation, model, estimated
                ORDER BY total_tokens DESC
                """
        )
        by_operation = cur.fetchall()

    return {
        "records": int(row["records"]),
        "input_tokens": int(row["input_tokens"]),
        "output_tokens": int(row["output_tokens"]),
        "total_tokens": int(row["total_tokens"]),
        "actual_tokens": int(row["actual_tokens"]),
        "estimated_tokens": int(row["estimated_tokens"]),
        "by_operation": [dict(item) for item in by_operation],
    }


def _get_usage_summary_sqlite() -> dict[str, Any]:
    with _connect_sqlite() as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS records,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(CASE WHEN estimated = 1 THEN total_tokens ELSE 0 END), 0)
                    AS estimated_tokens,
                COALESCE(SUM(CASE WHEN estimated = 0 THEN total_tokens ELSE 0 END), 0)
                    AS actual_tokens
            FROM token_usage
            """
        ).fetchone()
        by_operation = connection.execute(
            """
            SELECT operation, model, estimated, COUNT(*) AS records,
                   COALESCE(SUM(total_tokens), 0) AS total_tokens
            FROM token_usage
            GROUP BY operation, model, estimated
            ORDER BY total_tokens DESC
            """
        ).fetchall()

    return {
        "records": row["records"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "total_tokens": row["total_tokens"],
        "actual_tokens": row["actual_tokens"],
        "estimated_tokens": row["estimated_tokens"],
        "by_operation": [dict(item) for item in by_operation],
    }


def get_usage_summary() -> dict[str, Any]:
    if _use_postgres():
        try:
            return _get_usage_summary_postgres()
        except Exception:
            logger.exception("Failed to read token usage from PostgreSQL; falling back to SQLite")
    return _get_usage_summary_sqlite()


def _list_usage_records_postgres(limit: int) -> list[dict[str, Any]]:
    _ensure_postgres_table()
    with get_conn() as connection, connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
                SELECT created_at, request_id, operation, mode, provider, model,
                       input_tokens, output_tokens, total_tokens, estimated, metadata,
                       conversation_id
                FROM token_usage
                ORDER BY id DESC
                LIMIT %s
                """,
            (limit,),
        )
        rows = cur.fetchall()
    return [
        {
            **dict(row),
            "metadata": row["metadata"] or {},
            "created_at": row["created_at"].isoformat()
            if hasattr(row["created_at"], "isoformat")
            else str(row["created_at"]),
        }
        for row in rows
    ]


def _list_usage_records_sqlite(limit: int) -> list[dict[str, Any]]:
    with _connect_sqlite() as connection:
        rows = connection.execute(
            """
            SELECT created_at, request_id, operation, mode, provider, model,
                   input_tokens, output_tokens, total_tokens, estimated, metadata,
                   conversation_id
            FROM token_usage
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_usage_records(limit: int = 50) -> list[dict[str, Any]]:
    limit = min(max(limit, 1), 500)
    if _use_postgres():
        try:
            return _list_usage_records_postgres(limit)
        except Exception:
            logger.exception("Failed to list token usage from PostgreSQL; falling back to SQLite")
    return _list_usage_records_sqlite(limit)


def _reset_usage_postgres() -> int:
    _ensure_postgres_table()
    with get_conn() as connection, connection.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM token_usage")
        count = cur.fetchone()[0]
        cur.execute("DELETE FROM token_usage")
    return int(count)


def _reset_usage_sqlite() -> int:
    with _connect_sqlite() as connection:
        count = connection.execute("SELECT COUNT(*) AS count FROM token_usage").fetchone()["count"]
        connection.execute("DELETE FROM token_usage")
    return int(count)


def reset_usage() -> int:
    if _use_postgres():
        try:
            return _reset_usage_postgres()
        except Exception:
            logger.exception("Failed to reset token usage in PostgreSQL; falling back to SQLite")
    return _reset_usage_sqlite()
