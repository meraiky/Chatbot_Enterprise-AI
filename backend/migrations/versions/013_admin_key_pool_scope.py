"""admin key pool usage scope

Revision ID: 013
Revises: 012
Create Date: 2026-05-12 23:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'admin_key_pool' not in inspector.get_table_names():
        return

    cols = {c['name'] for c in inspector.get_columns('admin_key_pool')}
    if 'key_scope' not in cols:
        op.add_column(
            'admin_key_pool',
            sa.Column('key_scope', sa.String(length=20), server_default='chat', nullable=False),
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'admin_key_pool' not in inspector.get_table_names():
        return

    cols = {c['name'] for c in inspector.get_columns('admin_key_pool')}
    if 'key_scope' in cols:
        op.drop_column('admin_key_pool', 'key_scope')
