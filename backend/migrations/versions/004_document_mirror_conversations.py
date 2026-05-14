"""add document mirror and conversation audit

Revision ID: 004
Revises: 003
Create Date: 2026-05-09 03:15:00.000000

"""
from alembic import op


revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE token_usage ADD COLUMN IF NOT EXISTS conversation_id TEXT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS token_usage_conversation_id_idx "
        "ON token_usage (conversation_id)"
    )
    op.execute(
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
    op.execute("CREATE INDEX IF NOT EXISTS document_chunks_doc_id_idx ON document_chunks (doc_id)")
    op.execute("CREATE INDEX IF NOT EXISTS document_chunks_mode_idx ON document_chunks (mode)")
    op.execute("CREATE INDEX IF NOT EXISTS document_chunks_source_idx ON document_chunks (source)")
    op.execute(
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
    op.execute("CREATE INDEX IF NOT EXISTS chat_audit_conversation_id_idx ON chat_audit (conversation_id)")
    op.execute("CREATE INDEX IF NOT EXISTS chat_audit_created_at_idx ON chat_audit (created_at)")


def downgrade():
    op.drop_index("chat_audit_created_at_idx", table_name="chat_audit")
    op.drop_index("chat_audit_conversation_id_idx", table_name="chat_audit")
    op.drop_table("chat_audit")
    op.drop_index("document_chunks_source_idx", table_name="document_chunks")
    op.drop_index("document_chunks_mode_idx", table_name="document_chunks")
    op.drop_index("document_chunks_doc_id_idx", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("token_usage_conversation_id_idx", table_name="token_usage")
    op.drop_column("token_usage", "conversation_id")
