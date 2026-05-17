"""
vector_store.py — pgvector-backed document chunk store.

Replaces ChromaDB. Embeddings are generated locally via sentence-transformers
(all-mpnet-base-v2, 768 dims) — no external API call, no vendor lock-in.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.documents import Document
from sentence_transformers import SentenceTransformer

from app.core.config import settings
from app.core.database import get_conn

logger = logging.getLogger(__name__)

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("Loading embedding model: %s", settings.EMBEDDING_MODEL)
        _model = SentenceTransformer(settings.EMBEDDING_MODEL)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    return _get_model().encode(texts, normalize_embeddings=True).tolist()


def embed_query(text: str) -> list[float]:
    return embed_texts([text.strip()])[0]


def get_embedding_function():
    """Compatibility wrapper used by cache_service."""

    class _EmbeddingWrapper:
        def embed_query(self, text: str) -> list[float]:
            return embed_query(text)

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return embed_texts(texts)

    return _EmbeddingWrapper()


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(str(v) for v in vec) + "]"


class PgVectorStore:
    """
    Document chunk store backed by PostgreSQL + pgvector (document_chunks table).

    Public interface is a superset of the old LangChain Chroma wrapper so that
    call-sites in query_engine and document_registry need minimal changes.
    """

    # ── Write ──────────────────────────────────────────────────────────────────

    def add_documents(self, documents: list[Document], ids: list[str]) -> None:
        embeddings = embed_texts([d.page_content for d in documents])
        with get_conn() as conn:
            with conn.cursor() as cur:
                for doc, emb, chunk_id in zip(documents, embeddings, ids):
                    m = doc.metadata
                    doc_type = m.get("type") or m.get("mode") or "Internal"
                    cur.execute(
                        """
                        INSERT INTO document_chunks
                            (chunk_id, doc_id, content, metadata, embedding,
                             source, mode, doc_type, page, checksum, uploaded_at)
                        VALUES (%s, %s, %s, %s::jsonb, %s::vector, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (chunk_id) DO UPDATE SET
                            content   = EXCLUDED.content,
                            metadata  = EXCLUDED.metadata,
                            embedding = EXCLUDED.embedding,
                            source = EXCLUDED.source,
                            mode = EXCLUDED.mode,
                            doc_type = EXCLUDED.doc_type,
                            page = EXCLUDED.page,
                            checksum = EXCLUDED.checksum,
                            uploaded_at = EXCLUDED.uploaded_at
                        """,
                        (
                            chunk_id,
                            m.get("doc_id"),
                            doc.page_content,
                            json.dumps(m),
                            _vec_literal(emb),
                            m.get("source"),
                            doc_type,
                            doc_type,
                            m.get("page"),
                            m.get("checksum"),
                            m.get("uploaded_at"),
                        ),
                    )

    # ── Read ───────────────────────────────────────────────────────────────────

    def similarity_search_with_score(
        self,
        query: str,
        k: int = 5,
        filter: dict | None = None,
    ) -> list[tuple[Document, float]]:
        q_vec = _vec_literal(embed_query(query))
        doc_type = (filter or {}).get("type")

        with get_conn() as conn:
            with conn.cursor() as cur:
                if doc_type:
                    cur.execute(
                        """
                        SELECT content, metadata,
                               1 - (embedding <=> %s::vector) AS score
                        FROM   document_chunks
                        WHERE  doc_type = %s
                        ORDER  BY embedding <=> %s::vector
                        LIMIT  %s
                        """,
                        (q_vec, doc_type, q_vec, k),
                    )
                else:
                    cur.execute(
                        """
                        SELECT content, metadata,
                               1 - (embedding <=> %s::vector) AS score
                        FROM   document_chunks
                        ORDER  BY embedding <=> %s::vector
                        LIMIT  %s
                        """,
                        (q_vec, q_vec, k),
                    )
                rows = cur.fetchall()

        return [
            (
                Document(
                    page_content=row[0],
                    metadata=row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}"),
                ),
                float(row[2]),
            )
            for row in rows
        ]

    def get_corpus(self, doc_type: str) -> dict[str, list]:
        """
        Return all chunks for a doc_type as a dict compatible with the old
        ChromaDB _collection.get() return format used by BM25Searcher.

        Returns: {"documents": [str, ...], "metadatas": [dict, ...]}
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT content, metadata FROM document_chunks WHERE doc_type = %s",
                    (doc_type,),
                )
                rows = cur.fetchall()

        return {
            "documents": [r[0] for r in rows],
            "metadatas": [
                r[1] if isinstance(r[1], dict) else json.loads(r[1] or "{}") for r in rows
            ],
        }

    def get_all_metadatas(self) -> dict[str, list]:
        """
        Return metadata for every chunk — used by document_registry.list_indexed_documents.

        Returns: {"metadatas": [dict, ...]}
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT metadata FROM document_chunks ORDER BY id")
                rows = cur.fetchall()

        return {
            "metadatas": [
                r[0] if isinstance(r[0], dict) else json.loads(r[0] or "{}") for r in rows
            ]
        }

    def count(self, doc_type: str | None = None) -> int:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if doc_type:
                    cur.execute(
                        "SELECT COUNT(*) FROM document_chunks WHERE doc_type = %s",
                        (doc_type,),
                    )
                else:
                    cur.execute("SELECT COUNT(*) FROM document_chunks")
                row = cur.fetchone()
                return int(row[0]) if row else 0

    # ── Delete ─────────────────────────────────────────────────────────────────

    def delete_by_doc_id(self, doc_id: str) -> int:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM document_chunks WHERE doc_id = %s", (doc_id,)
                )
                return cur.rowcount

    def delete_by_source_type(self, source: str, doc_type: str) -> int:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM document_chunks WHERE source = %s AND doc_type = %s",
                    (source, doc_type),
                )
                return cur.rowcount


_store: PgVectorStore | None = None


def get_vector_store() -> PgVectorStore:
    global _store
    if _store is None:
        _store = PgVectorStore()
    return _store


def vector_store_health() -> dict[str, Any]:
    try:
        store = get_vector_store()
        return {
            "available": True,
            "backend": "pgvector",
            "embedding_model": settings.EMBEDDING_MODEL,
            "count": store.count(),
        }
    except Exception as exc:
        return {
            "available": False,
            "backend": "pgvector",
            "embedding_model": settings.EMBEDDING_MODEL,
            "count": 0,
            "error": str(exc),
        }
