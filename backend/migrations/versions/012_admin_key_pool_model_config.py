"""admin key pool model config

Revision ID: 012
Revises: 011
Create Date: 2026-05-12 22:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'admin_key_pool' not in inspector.get_table_names():
        return

    cols = {c['name'] for c in inspector.get_columns('admin_key_pool')}
    if 'model_name' not in cols:
        op.add_column('admin_key_pool', sa.Column('model_name', sa.String(length=255), nullable=True))
    if 'custom_endpoint' not in cols:
        op.add_column('admin_key_pool', sa.Column('custom_endpoint', sa.String(length=500), nullable=True))
    if 'custom_headers' not in cols:
        op.add_column('admin_key_pool', sa.Column('custom_headers', sa.Text(), nullable=True))
    if 'temperature' not in cols:
        op.add_column(
            'admin_key_pool',
            sa.Column('temperature', sa.Float(), server_default='0.2', nullable=False),
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'admin_key_pool' not in inspector.get_table_names():
        return

    cols = {c['name'] for c in inspector.get_columns('admin_key_pool')}
    for col in ['temperature', 'custom_headers', 'custom_endpoint', 'model_name']:
        if col in cols:
            op.drop_column('admin_key_pool', col)
