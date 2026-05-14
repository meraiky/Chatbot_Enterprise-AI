"""add token usage table

Revision ID: 002
Revises: 001
Create Date: 2026-05-09 02:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "token_usage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text()),
        sa.Column("provider", sa.Text(), nullable=False, server_default="google"),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration", sa.Float(), nullable=False, server_default="0"),
        sa.Column("estimated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index("token_usage_created_at_idx", "token_usage", ["created_at"])
    op.create_index("token_usage_request_id_idx", "token_usage", ["request_id"])
    op.create_index("token_usage_operation_idx", "token_usage", ["operation"])


def downgrade():
    op.drop_index("token_usage_operation_idx", table_name="token_usage")
    op.drop_index("token_usage_request_id_idx", table_name="token_usage")
    op.drop_index("token_usage_created_at_idx", table_name="token_usage")
    op.drop_table("token_usage")
