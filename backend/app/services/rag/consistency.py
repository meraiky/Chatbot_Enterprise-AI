from __future__ import annotations

import logging

from app.core.config import settings
from app.core.database import get_conn

logger = logging.getLogger(__name__)


def check_vector_consistency(auto_rebuild: bool = False) -> dict:
    """Check document_chunks table integrity against pgvector store.

    Reports total chunk/document counts, per-type breakdown, and any chunks
    that are missing their embedding vector (which would break similarity search).
    """
    if not settings.DATABASE_URL:
        return {
            "ok": True,
            "total_chunks": 0,
            "total_documents": 0,
            "by_type": [],
            "issues": [],
            "rebuilt": None,
            "note": "DATABASE_URL not configured",
        }

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM document_chunks")
        total_chunks = int((cur.fetchone() or (0,))[0])

        cur.execute(
            "SELECT COUNT(DISTINCT doc_id) FROM document_chunks WHERE doc_id IS NOT NULL"
        )
        total_docs = int((cur.fetchone() or (0,))[0])

        cur.execute("SELECT COUNT(*) FROM document_chunks WHERE embedding IS NULL")
        missing_embedding = int((cur.fetchone() or (0,))[0])

        cur.execute(
            """
                SELECT COALESCE(doc_type, 'unknown'), COUNT(*), COUNT(DISTINCT doc_id)
                FROM document_chunks
                GROUP BY doc_type
                ORDER BY doc_type
                """
        )
        by_type = [
            {"doc_type": row[0], "chunks": int(row[1]), "documents": int(row[2])}
            for row in cur.fetchall()
        ]

    issues = []
    if missing_embedding > 0:
        issues.append(
            {
                "type": "missing_embeddings",
                "count": missing_embedding,
                "fix": "Re-upload affected documents to regenerate embeddings",
            }
        )

    rebuilt = None
    if auto_rebuild and missing_embedding > 0:
        try:
            from app.services.rag.document_mirror import rebuild_vector_from_mirror
            rebuilt = rebuild_vector_from_mirror()
        except Exception as exc:
            logger.exception("auto_rebuild failed")
            rebuilt = {"error": str(exc)}

    return {
        "ok": not issues,
        "total_chunks": total_chunks,
        "total_documents": total_docs,
        "by_type": by_type,
        "issues": issues,
        "rebuilt": rebuilt,
    }
