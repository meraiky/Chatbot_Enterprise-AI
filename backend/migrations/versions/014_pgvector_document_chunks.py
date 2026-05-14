"""replace ChromaDB with pgvector document_chunks table

Revision ID: 014
Revises: 013
Create Date: 2026-05-14

Drop ChromaDB as the primary vector store. All document chunks are now stored in
PostgreSQL via pgvector. The embedding dimension changes from 3072 (Gemini) to 768
(sentence-transformers/all-mpnet-base-v2), which fits within the 2000-dim HNSW index
limit and eliminates vendor lock-in on the embedding provider.

The qa_cache embedding column is also resized — existing cache entries are cleared
because their 3072-dim vectors are incompatible with the new 768-dim model.
"""
from alembic import op
import sqlalchemy as sa

revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None

EMBEDDING_DIM = 768


def _column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column}).fetchone()
    return row is not None


def upgrade():
    conn = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── document_chunks: create if not exists ─────────────────────────────────
    conn.execute(sa.text(f"""
        CREATE TABLE IF NOT EXISTS document_chunks (
            id SERIAL PRIMARY KEY,
            chunk_id TEXT NOT NULL UNIQUE,
            doc_id TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{{}}',
            embedding vector({EMBEDDING_DIM}),
            source TEXT,
            doc_type TEXT,
            page INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))

    # Ensure columns added in this migration exist on pre-existing tables.
    if not _column_exists(conn, "document_chunks", "embedding"):
        conn.execute(sa.text(f"ALTER TABLE document_chunks ADD COLUMN embedding vector({EMBEDDING_DIM})"))

    if not _column_exists(conn, "document_chunks", "doc_type"):
        conn.execute(sa.text("ALTER TABLE document_chunks ADD COLUMN doc_type TEXT"))
        # Backfill from legacy 'mode' column if present
        if _column_exists(conn, "document_chunks", "mode"):
            conn.execute(sa.text("UPDATE document_chunks SET doc_type = mode WHERE doc_type IS NULL"))

    # Indexes — safe to create with IF NOT EXISTS
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_document_chunks_doc_id ON document_chunks (doc_id)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_document_chunks_doc_type ON document_chunks (doc_type)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    ))

    # ── qa_cache: resize embedding 3072 → 768 if needed ──────────────────────
    result = conn.execute(sa.text(
        "SELECT atttypmod FROM pg_attribute "
        "WHERE attrelid = 'qa_cache'::regclass AND attname = 'embedding'"
    )).fetchone()
    current_dim = result[0] if result else None
    if current_dim != EMBEDDING_DIM:
        conn.execute(sa.text("DELETE FROM qa_cache"))
        conn.execute(sa.text("ALTER TABLE qa_cache DROP COLUMN IF EXISTS embedding"))
        conn.execute(sa.text(f"ALTER TABLE qa_cache ADD COLUMN embedding vector({EMBEDDING_DIM})"))

    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_qa_cache_embedding_hnsw "
        "ON qa_cache USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    ))


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_qa_cache_embedding_hnsw")
    op.execute("DELETE FROM qa_cache")
    op.execute("ALTER TABLE qa_cache DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE qa_cache ADD COLUMN embedding vector(3072)")

    op.execute("DROP INDEX IF EXISTS idx_document_chunks_embedding_hnsw")
    op.drop_index('idx_document_chunks_doc_type', table_name='document_chunks')
    op.drop_index('idx_document_chunks_doc_id', table_name='document_chunks')
    op.drop_table('document_chunks')
