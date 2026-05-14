"""per-user agent config and credentials

Revision ID: 008
Revises: 007
Create Date: 2026-05-10 08:40:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    # Create user_agent_config table
    op.create_table(
        'user_agent_config',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), nullable=False, unique=True),
        sa.Column('preferred_model', sa.Text(), nullable=False, server_default='gemini'),
        sa.Column('model_name', sa.Text()),
        sa.Column('temperature', sa.Float(), nullable=False, server_default='0.2'),
        sa.Column('system_prompt', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )
    op.create_index('user_agent_config_user_id_idx', 'user_agent_config', ['user_id'])

    # Create user_credentials table
    op.create_table(
        'user_credentials',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.Text(), nullable=False),
        sa.Column('api_key_enc', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'provider', name='user_credentials_user_provider_uc'),
    )
    op.create_index('user_credentials_user_id_idx', 'user_credentials', ['user_id'])
    op.create_index('user_credentials_provider_idx', 'user_credentials', ['provider'])


def downgrade():
    op.drop_table('user_credentials')
    op.drop_table('user_agent_config')
