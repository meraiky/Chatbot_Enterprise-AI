"""redact usage and search cache content

Revision ID: 017
Revises: 016
Create Date: 2026-05-18
"""

from alembic import op


revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE token_usage
        SET metadata = (metadata::jsonb - 'question' - 'answer_preview')::json
        WHERE metadata::jsonb ? 'question'
           OR metadata::jsonb ? 'answer_preview'
        """
    )
    op.execute("UPDATE external_search_cache SET search_query = '' WHERE search_query <> ''")


def downgrade() -> None:
    # Redacted prompt/answer text cannot be reconstructed.
    pass
