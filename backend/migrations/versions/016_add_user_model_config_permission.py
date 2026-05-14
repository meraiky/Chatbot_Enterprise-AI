"""add can_manage_models permission to users

Revision ID: 016
Revises: 015
Create Date: 2026-05-14
"""

from alembic import op
import sqlalchemy as sa


revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add the column with default False
    op.add_column(
        "users",
        sa.Column("can_manage_models", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    
    # 2. Grant permission to existing admin users
    op.execute("UPDATE users SET can_manage_models = true WHERE role = 'admin'")


def downgrade() -> None:
    op.drop_column("users", "can_manage_models")
