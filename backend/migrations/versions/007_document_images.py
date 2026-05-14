"""add document image metadata

Revision ID: 007
Revises: 006
Create Date: 2026-05-10 00:15:00.000000

"""
from alembic import op


revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS document_images (
            id SERIAL PRIMARY KEY,
            image_id TEXT NOT NULL UNIQUE,
            doc_id TEXT NOT NULL,
            source TEXT NOT NULL,
            mode TEXT NOT NULL,
            page INTEGER,
            image_index INTEGER NOT NULL,
            storage_path TEXT NOT NULL,
            content_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            checksum TEXT NOT NULL,
            caption TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS document_images_doc_id_idx ON document_images (doc_id)")
    op.execute("CREATE INDEX IF NOT EXISTS document_images_mode_idx ON document_images (mode)")


def downgrade():
    op.drop_index("document_images_mode_idx", table_name="document_images")
    op.drop_index("document_images_doc_id_idx", table_name="document_images")
    op.drop_table("document_images")
