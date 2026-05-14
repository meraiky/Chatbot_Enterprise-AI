"""initial schema

Revision ID: 001
Revises: 
Create Date: 2026-05-07 15:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    
    # Create qa_cache table
    op.create_table(
        'qa_cache',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('sources', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('mode', sa.Text(), nullable=False),
        sa.Column('embedding', Vector(3072)),
        sa.Column('hit_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('last_hit_at', sa.DateTime(timezone=True)),
    )
    # Note: Neon.tech has a 2000-dimension limit for vector indexes (both ivfflat and hnsw)
    # Gemini embeddings are 3072 dimensions, so we skip the vector index
    # Semantic search will still work but will be slower (acceptable for development)
    # For production with large datasets, consider using a different PostgreSQL provider
    # or reducing embedding dimensions
    op.create_index('qa_cache_mode_idx', 'qa_cache', ['mode'])
    op.create_index('qa_cache_created_at_idx', 'qa_cache', ['created_at'])

    # Create topic_guard table
    op.create_table(
        'topic_guard',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('pattern', sa.Text(), nullable=False),
        sa.Column('mode', sa.Text()),
        sa.Column('reason', sa.Text()),
        sa.Column('is_regex', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('username', sa.Text(), nullable=False, unique=True),
        sa.Column('hashed_password', sa.Text(), nullable=False),
        sa.Column('role', sa.Text(), nullable=False, server_default='user'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

def downgrade():
    op.drop_table('users')
    op.drop_table('topic_guard')
    op.drop_table('qa_cache')
    op.execute("DROP EXTENSION IF EXISTS vector")
