"""add revoked token blacklist

Revision ID: 015_revoked_tokens
Revises: 014_pgvector_document_chunks
Create Date: 2026-05-14
"""

from alembic import op
import sqlalchemy as sa


revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.String(length=64), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("revoked_tokens_expires_at_idx", "revoked_tokens", ["expires_at"])


def downgrade() -> None:
    op.drop_index("revoked_tokens_expires_at_idx", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
