from __future__ import annotations

import json
from typing import Any

import psycopg2.extras
from langchain_core.documents import Document

from app.core.config import settings
from app.core.database import get_conn
from app.services.rag.vector_store import get_vector_store


def _metadata_json(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata or {}, ensure_ascii=False)


def _ensure_document_chunks_table() -> None:
    with get_conn() as connection, connection.cursor() as cur:
        cur.execute(
            """
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id SERIAL PRIMARY KEY,
                    chunk_id TEXT NOT NULL UNIQUE,
                    doc_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    page INTEGER,
                    checksum TEXT,
                    uploaded_at TIMESTAMPTZ,
                    content TEXT NOT NULL,
                    metadata JSON NOT NULL DEFAULT '{}'::json,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS document_chunks_doc_id_idx ON document_chunks (doc_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS document_chunks_mode_idx ON document_chunks (mode)")
        cur.execute("CREATE INDEX IF NOT EXISTS document_chunks_source_idx ON document_chunks (source)")


def mirror_document_chunks(
    *,
    documents: list[Document],
    ids: list[str],
) -> int:
    """Persist indexed chunks to PostgreSQL so the vector store can be rebuilt."""
    if not settings.DATABASE_URL or not documents:
        return 0

    _ensure_document_chunks_table()
    rows = []
    for chunk_id, document in zip(ids, documents, strict=False):
        metadata = document.metadata or {}
        rows.append(
            (
                chunk_id,
                metadata.get("doc_id", ""),
                metadata.get("source", "Unknown"),
                metadata.get("type", "Internal"),
                metadata.get("page"),
                metadata.get("checksum", ""),
                metadata.get("uploaded_at"),
                document.page_content,
                _metadata_json(metadata),
            )
        )

    with get_conn() as connection, connection.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
                INSERT INTO document_chunks (
                    chunk_id, doc_id, source, mode, page, checksum, uploaded_at,
                    content, metadata
                )
                VALUES %s
                ON CONFLICT (chunk_id) DO UPDATE SET
                    doc_id = EXCLUDED.doc_id,
                    source = EXCLUDED.source,
                    mode = EXCLUDED.mode,
                    page = EXCLUDED.page,
                    checksum = EXCLUDED.checksum,
                    uploaded_at = EXCLUDED.uploaded_at,
                    content = EXCLUDED.content,
                    metadata = EXCLUDED.metadata
                """,
            rows,
            template="(%s, %s, %s, %s, %s, %s, %s::timestamptz, %s, %s::json)",
        )
    return len(rows)


def delete_mirrored_document(doc_id: str) -> int:
    if not settings.DATABASE_URL:
        return 0
    _ensure_document_chunks_table()
    with get_conn() as connection, connection.cursor() as cur:
        cur.execute("DELETE FROM document_chunks WHERE doc_id = %s", (doc_id,))
        return int(cur.rowcount or 0)


def rebuild_vector_from_mirror(doc_id: str | None = None, mode: str | None = None) -> dict[str, int]:
    """Rehydrate pgvector from PostgreSQL mirrored chunks."""
    if not settings.DATABASE_URL:
        return {"chunks": 0, "documents": 0}

    _ensure_document_chunks_table()
    where = []
    params: list[Any] = []
    if doc_id:
        where.append("doc_id = %s")
        params.append(doc_id)
    if mode:
        where.append("mode = %s")
        params.append(mode)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    with get_conn() as connection, connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
                SELECT chunk_id, doc_id, content, metadata
                FROM document_chunks
                {where_sql}
                ORDER BY doc_id, chunk_id
                """,
            params,
        )
        rows = cur.fetchall()

    if not rows:
        return {"chunks": 0, "documents": 0}

    vector_store = get_vector_store()
    doc_ids = sorted({row["doc_id"] for row in rows})
    for current_doc_id in doc_ids:
        vector_store.delete_by_doc_id(current_doc_id)

    documents = [
        Document(page_content=row["content"], metadata=row["metadata"] or {})
        for row in rows
    ]
    ids = [row["chunk_id"] for row in rows]
    for start in range(0, len(documents), 20):
        vector_store.add_documents(
            documents[start : start + 20],
            ids=ids[start : start + 20],
        )
    return {"chunks": len(rows), "documents": len(doc_ids)}
