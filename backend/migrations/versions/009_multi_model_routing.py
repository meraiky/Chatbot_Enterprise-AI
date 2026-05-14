"""multi-model routing

Revision ID: 009
Revises: 008
Create Date: 2026-05-10 16:21:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    # --- 1. Replace single-model user_agent_config with multi-model table ---
    op.drop_table('user_agent_config')

    op.create_table(
        'user_model_configs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('provider', sa.String(50), nullable=False),
        sa.Column('model_name', sa.String(255)),
        sa.Column('api_key_encrypted', sa.Text()),
        sa.Column('custom_endpoint', sa.String(500)),
        sa.Column('custom_headers', sa.Text()),  # JSON string for extra headers
        sa.Column('temperature', sa.Float(), server_default='0.2'),
        sa.Column('system_prompt', sa.Text()),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('priority', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )
    op.create_unique_constraint(
        'uq_user_model_name', 'user_model_configs', ['user_id', 'name']
    )
    op.create_index(
        'ix_user_model_configs_user_id', 'user_model_configs', ['user_id']
    )

    # --- 2. Routing config table ---
    op.create_table(
        'user_routing_config',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), nullable=False, unique=True),
        sa.Column('routing_strategy', sa.String(50), server_default='random'),
        sa.Column('enabled_model_ids', sa.Text()),   # JSON array
        sa.Column('fallback_order', sa.Text()),       # JSON array
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )

    # --- 3. Migrate existing user_credentials rows into user_model_configs ---
    #     Each credential becomes a model config entry so we don't lose data.
    op.execute("""
        INSERT INTO user_model_configs (user_id, name, provider, api_key_encrypted, is_active)
        SELECT user_id,
               provider || ' (migrated)' AS name,
               provider,
               api_key_enc,
               true
        FROM user_credentials
    """)

    # Drop legacy credentials table (keys are now inside user_model_configs)
    op.drop_table('user_credentials')


def downgrade():
    # Recreate legacy tables
    op.create_table(
        'user_credentials',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(50), nullable=False),
        sa.Column('api_key_enc', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'provider', name='user_credentials_user_provider_uc'),
    )

    op.create_table(
        'user_agent_config',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), nullable=False, unique=True),
        sa.Column('preferred_model', sa.String(50), server_default='gemini'),
        sa.Column('model_name', sa.String(200)),
        sa.Column('temperature', sa.Float(), server_default='0.2'),
        sa.Column('system_prompt', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )

    op.drop_table('user_routing_config')
    op.drop_table('user_model_configs')
