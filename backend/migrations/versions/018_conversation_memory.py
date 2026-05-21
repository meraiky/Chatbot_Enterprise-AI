"""add conversation memory

Revision ID: 018
Revises: 017
Create Date: 2026-05-21
"""

from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_memory (
            id SERIAL PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            user_id INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        ALTER TABLE conversation_memory
        ADD COLUMN IF NOT EXISTS user_id INTEGER
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_conversation_memory_cid
        ON conversation_memory(conversation_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_conversation_memory_uid
        ON conversation_memory(user_id, created_at DESC)
        """
    )


def downgrade() -> None:
    op.drop_index("idx_conversation_memory_uid", table_name="conversation_memory")
    op.drop_index("idx_conversation_memory_cid", table_name="conversation_memory")
    op.drop_table("conversation_memory")
