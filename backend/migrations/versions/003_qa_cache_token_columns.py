"""add token columns to qa cache

Revision ID: 003
Revises: 002
Create Date: 2026-05-09 02:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "qa_cache",
        sa.Column("question_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "qa_cache",
        sa.Column("answer_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "qa_cache",
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("qa_cache_total_tokens_idx", "qa_cache", ["total_tokens"])


def downgrade():
    op.drop_index("qa_cache_total_tokens_idx", table_name="qa_cache")
    op.drop_column("qa_cache", "total_tokens")
    op.drop_column("qa_cache", "answer_tokens")
    op.drop_column("qa_cache", "question_tokens")
