"""hybrid rag web search support

Revision ID: 010_hybrid_rag_web_search
Revises: 009_multi_model_routing
Create Date: 2026-05-10 18:41:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    # Create external_search_cache table
    op.create_table(
        'external_search_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('query_hash', sa.String(length=64), nullable=False),
        sa.Column('search_query', sa.Text(), nullable=False),
        sa.Column('search_results', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('answer', sa.Text(), nullable=True),
        sa.Column('sources', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('hit_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_accessed', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('query_hash')
    )
    op.create_index('idx_external_search_expires', 'external_search_cache', ['expires_at'])
    op.create_index('idx_external_search_query_hash', 'external_search_cache', ['query_hash'])

    # Create user_search_preferences table
    op.create_table(
        'user_search_preferences',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('allow_web_search', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('auto_web_search', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('web_search_providers', postgresql.JSONB(astext_type=sa.Text()),
                  server_default='["duckduckgo"]', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id')
    )

    # Add source_type column to qa_cache
    op.add_column('qa_cache', sa.Column('source_type', sa.String(length=20),
                                        server_default='internal', nullable=False))
    op.add_column('qa_cache', sa.Column('external_sources',
                                        postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    
    # Add source_type column to documents only if table exists
    if 'documents' in inspector.get_table_names():
        op.add_column('documents', sa.Column('source_type', sa.String(length=20),
                                             server_default='internal', nullable=False))
        op.create_index('idx_documents_source_type', 'documents', ['source_type'])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    # Drop indexes and columns from documents only if table exists
    if 'documents' in inspector.get_table_names():
        op.drop_index('idx_documents_source_type', table_name='documents')
        op.drop_column('documents', 'source_type')
    
    # Drop indexes
    op.drop_index('idx_external_search_query_hash', table_name='external_search_cache')
    op.drop_index('idx_external_search_expires', table_name='external_search_cache')
    
    # Drop columns
    op.drop_column('qa_cache', 'external_sources')
    op.drop_column('qa_cache', 'source_type')
    
    # Drop tables
    op.drop_table('user_search_preferences')
    op.drop_table('external_search_cache')
