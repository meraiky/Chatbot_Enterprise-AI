from __future__ import annotations

import psycopg2.extras

from app.core.config import settings
from app.core.database import get_conn
from app.services.rag.document_mirror import rebuild_chroma_from_mirror
from app.services.rag.vector_store import get_vector_store


def check_vector_consistency(auto_rebuild: bool = False) -> dict:
    vector_store = get_vector_store()
    chroma_result = vector_store._collection.get(include=["metadatas"])
    chroma_metadatas = chroma_result.get("metadatas") or []
    chroma_doc_ids = {
        metadata.get("doc_id")
        for metadata in chroma_metadatas
        if metadata and metadata.get("doc_id")
    }
    chroma_count = len(chroma_result.get("ids") or [])

    neon_count = 0
    neon_doc_ids: set[str] = set()
    if settings.DATABASE_URL:
        with get_conn() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT COUNT(*) AS count FROM document_chunks")
                neon_count = int(cur.fetchone()["count"])
                cur.execute("SELECT DISTINCT doc_id FROM document_chunks")
                neon_doc_ids = {row["doc_id"] for row in cur.fetchall() if row["doc_id"]}

    issues = []
    if chroma_count != neon_count:
        issues.append(
            {
                "type": "count_mismatch",
                "chroma": chroma_count,
                "neon": neon_count,
                "diff": neon_count - chroma_count,
            }
        )

    missing_in_chroma = sorted(neon_doc_ids - chroma_doc_ids)
    orphan_in_chroma = sorted(chroma_doc_ids - neon_doc_ids)
    if missing_in_chroma:
        issues.append({"type": "missing_in_chroma", "doc_ids": missing_in_chroma})
    if orphan_in_chroma:
        issues.append({"type": "orphan_in_chroma", "doc_ids": orphan_in_chroma})

    rebuilt = None
    if auto_rebuild and issues and neon_count > 0 and chroma_count < neon_count:
        rebuilt = rebuild_chroma_from_mirror()

    return {
        "ok": not issues,
        "chroma_count": chroma_count,
        "neon_count": neon_count,
        "chroma_documents": len(chroma_doc_ids),
        "neon_documents": len(neon_doc_ids),
        "issues": issues,
        "rebuilt": rebuilt,
    }

