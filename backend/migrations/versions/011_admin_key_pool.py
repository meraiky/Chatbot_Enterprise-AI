"""admin key pool management

Revision ID: 011_admin_key_pool
Revises: 010
Create Date: 2026-05-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # --- admin_key_pool ---
    if 'admin_key_pool' not in existing_tables:
        op.create_table(
            'admin_key_pool',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('mode', sa.String(length=20), nullable=False),
            sa.Column('provider', sa.String(length=30), nullable=False),
            sa.Column('api_key_enc', sa.Text(), nullable=False),
            sa.Column('label', sa.String(length=100), nullable=True),
            sa.Column('rotation_strategy', sa.String(length=20), server_default='random', nullable=False),
            sa.Column('priority', sa.Integer(), server_default='0', nullable=False),
            sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('idx_akp_mode_provider_active', 'admin_key_pool', ['mode', 'provider', 'is_active'])

    # --- key_health_cache ---
    if 'key_health_cache' not in existing_tables:
        op.create_table(
            'key_health_cache',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('key_type', sa.String(length=20), nullable=False),
            sa.Column('key_id', sa.Integer(), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False),
            sa.Column('checked_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
            sa.Column('retry_after', sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('key_type', 'key_id', name='uq_key_health_type_id'),
        )
        op.create_index('idx_khc_type_id', 'key_health_cache', ['key_type', 'key_id'])

    # --- user_admin_quota ---
    if 'user_admin_quota' not in existing_tables:
        op.create_table(
            'user_admin_quota',
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('daily_token_limit', sa.Integer(), server_default='50000', nullable=False),
            sa.Column('monthly_token_limit', sa.Integer(), server_default='500000', nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('user_id'),
        )

    # --- user_quota_usage ---
    if 'user_quota_usage' not in existing_tables:
        op.create_table(
            'user_quota_usage',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('day_bucket', sa.Date(), nullable=False),
            sa.Column('month_bucket', sa.String(length=7), nullable=False),
            sa.Column('tokens_used', sa.Integer(), server_default='0', nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'day_bucket', name='uq_quota_usage_user_day'),
        )
        op.create_index('idx_uqu_user_day', 'user_quota_usage', ['user_id', 'day_bucket'])

    # --- key_usage_log ---
    if 'key_usage_log' not in existing_tables:
        op.create_table(
            'key_usage_log',
            sa.Column('id', sa.BigInteger(), nullable=False),
            sa.Column('key_type', sa.String(length=20), nullable=False),
            sa.Column('key_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=True),
            sa.Column('request_id', sa.String(length=64), nullable=True),
            sa.Column('mode', sa.String(length=20), nullable=True),
            sa.Column('provider', sa.String(length=30), nullable=True),
            sa.Column('tokens_used', sa.Integer(), server_default='0', nullable=False),
            sa.Column('outcome', sa.String(length=20), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('idx_kul_created', 'key_usage_log', [sa.text('created_at DESC')])
        op.create_index('idx_kul_key', 'key_usage_log', ['key_type', 'key_id'])

    # --- ALTER user_model_configs: add key_mode ---
    if 'user_model_configs' in existing_tables:
        cols = [c['name'] for c in inspector.get_columns('user_model_configs')]
        if 'key_mode' not in cols:
            op.add_column(
                'user_model_configs',
                sa.Column('key_mode', sa.String(length=20), server_default='user_then_admin', nullable=False),
            )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if 'user_model_configs' in existing_tables:
        cols = [c['name'] for c in inspector.get_columns('user_model_configs')]
        if 'key_mode' in cols:
            op.drop_column('user_model_configs', 'key_mode')

    for tbl, idx_list in [
        ('key_usage_log', ['idx_kul_key', 'idx_kul_created']),
        ('user_quota_usage', ['idx_uqu_user_day']),
        ('key_health_cache', ['idx_khc_type_id']),
        ('admin_key_pool', ['idx_akp_mode_provider_active']),
    ]:
        if tbl in existing_tables:
            for idx in idx_list:
                try:
                    op.drop_index(idx, table_name=tbl)
                except Exception:
                    pass
            op.drop_table(tbl)

    if 'user_admin_quota' in existing_tables:
        op.drop_table('user_admin_quota')
