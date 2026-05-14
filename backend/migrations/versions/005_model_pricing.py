"""add model pricing

Revision ID: 005
Revises: 004
Create Date: 2026-05-09 05:00:00.000000

"""
from alembic import op


revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS model_pricing (
            model_name TEXT PRIMARY KEY,
            input_price_per_1m_tokens NUMERIC(12, 6) NOT NULL DEFAULT 0,
            output_price_per_1m_tokens NUMERIC(12, 6) NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'USD',
            effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        INSERT INTO model_pricing (
            model_name, input_price_per_1m_tokens, output_price_per_1m_tokens, currency
        )
        VALUES
            ('gemini-3-flash-preview', 0.50, 3.00, 'USD'),
            ('models/gemini-embedding-2', 0.15, 0.00, 'USD'),
            ('cache', 0.00, 0.00, 'USD')
        ON CONFLICT (model_name) DO NOTHING
        """
    )


def downgrade():
    op.drop_table("model_pricing")

