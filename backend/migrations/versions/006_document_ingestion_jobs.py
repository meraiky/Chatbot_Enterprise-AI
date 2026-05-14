"""add document ingestion jobs

Revision ID: 006
Revises: 005
Create Date: 2026-05-09 23:45:00.000000

"""
from alembic import op


revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS document_ingestion_jobs (
            id SERIAL PRIMARY KEY,
            doc_id TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL,
            mode TEXT NOT NULL,
            checksum TEXT NOT NULL,
            storage_path TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            progress INTEGER NOT NULL DEFAULT 0,
            progress_message TEXT,
            chunks_indexed INTEGER NOT NULL DEFAULT 0,
            replaced_chunks INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS document_ingestion_jobs_status_idx "
        "ON document_ingestion_jobs (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS document_ingestion_jobs_mode_idx "
        "ON document_ingestion_jobs (mode)"
    )


def downgrade():
    op.drop_index("document_ingestion_jobs_mode_idx", table_name="document_ingestion_jobs")
    op.drop_index("document_ingestion_jobs_status_idx", table_name="document_ingestion_jobs")
    op.drop_table("document_ingestion_jobs")
