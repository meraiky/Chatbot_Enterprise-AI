from __future__ import annotations

from typing import Any

import psycopg2.extras

from app.core.config import settings
from app.core.database import get_conn


def _enabled() -> bool:
    return bool(settings.DATABASE_URL)


def ensure_ingestion_jobs_table() -> None:
    if not _enabled():
        return
    with get_conn() as connection, connection.cursor() as cur:
        cur.execute(
            """
                CREATE TABLE IF NOT EXISTS document_ingestion_jobs (
                    id SERIAL PRIMARY KEY,
                    doc_id TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    storage_path TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    progress INTEGER NOT NULL DEFAULT 0,
                    progress_message TEXT,
                    chunks_indexed INTEGER NOT NULL DEFAULT 0,
                    replaced_chunks INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ
                )
                """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS document_ingestion_jobs_status_idx "
            "ON document_ingestion_jobs (status)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS document_ingestion_jobs_mode_idx "
            "ON document_ingestion_jobs (mode)"
        )


def upsert_ingestion_job(
    *,
    doc_id: str,
    source: str,
    mode: str,
    checksum: str,
    storage_path: str | None = None,
    status: str = "pending",
    progress: int = 0,
    progress_message: str | None = None,
) -> None:
    if not _enabled():
        return
    ensure_ingestion_jobs_table()
    with get_conn() as connection, connection.cursor() as cur:
        cur.execute(
            """
                INSERT INTO document_ingestion_jobs (
                    doc_id, source, mode, checksum, storage_path, status,
                    progress, progress_message
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (doc_id) DO UPDATE SET
                    source = EXCLUDED.source,
                    mode = EXCLUDED.mode,
                    checksum = EXCLUDED.checksum,
                    storage_path = COALESCE(EXCLUDED.storage_path, document_ingestion_jobs.storage_path),
                    status = EXCLUDED.status,
                    progress = EXCLUDED.progress,
                    progress_message = EXCLUDED.progress_message,
                    error_message = NULL,
                    updated_at = NOW(),
                    completed_at = NULL
                """,
            (
                doc_id,
                source,
                mode,
                checksum,
                storage_path,
                status,
                progress,
                progress_message,
            ),
        )


def update_ingestion_job(
    *,
    doc_id: str,
    status: str,
    progress: int,
    progress_message: str | None = None,
    chunks_indexed: int | None = None,
    replaced_chunks: int | None = None,
    error_message: str | None = None,
) -> None:
    if not _enabled():
        return
    ensure_ingestion_jobs_table()
    completed_sql = ", completed_at = NOW()" if status in {"indexed", "failed"} else ""
    with get_conn() as connection, connection.cursor() as cur:
        cur.execute(
            f"""
                UPDATE document_ingestion_jobs
                SET status = %s,
                    progress = %s,
                    progress_message = %s,
                    chunks_indexed = COALESCE(%s, chunks_indexed),
                    replaced_chunks = COALESCE(%s, replaced_chunks),
                    error_message = %s,
                    updated_at = NOW()
                    {completed_sql}
                WHERE doc_id = %s
                """,
            (
                status,
                progress,
                progress_message,
                chunks_indexed,
                replaced_chunks,
                error_message,
                doc_id,
            ),
        )


def get_ingestion_job(doc_id: str) -> dict[str, Any] | None:
    if not _enabled():
        return None
    ensure_ingestion_jobs_table()
    with get_conn() as connection, connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
                SELECT doc_id, source, mode, checksum, storage_path, status,
                       progress, progress_message, chunks_indexed, replaced_chunks,
                       error_message, created_at, updated_at, completed_at
                FROM document_ingestion_jobs
                WHERE doc_id = %s
                """,
            (doc_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def delete_ingestion_job(doc_id: str) -> int:
    if not _enabled():
        return 0
    ensure_ingestion_jobs_table()
    with get_conn() as connection, connection.cursor() as cur:
        cur.execute("DELETE FROM document_ingestion_jobs WHERE doc_id = %s", (doc_id,))
        return int(cur.rowcount or 0)
