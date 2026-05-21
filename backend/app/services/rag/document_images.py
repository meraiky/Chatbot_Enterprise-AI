from __future__ import annotations

import hashlib
from typing import Any

import fitz
import psycopg2.extras

from app.core.config import settings
from app.core.database import get_conn
from app.services.rag.source_storage import get_document_storage_dir

MIN_IMAGE_BYTES = 2048

# Module-level flag to ensure DDL runs only once per process
_document_images_table_ready = False


def _enabled() -> bool:
    return bool(settings.DATABASE_URL)


def ensure_document_images_table() -> None:
    """Ensure document_images table exists. Uses module-level flag to run DDL only once per process.
    
    CRITICAL FIX (C-2): Previously ran 3 DDL statements on EVERY image operation.
    Now runs only once per process lifetime using _document_images_table_ready flag.
    Migrations (007_document_images.py) already handle schema creation, so this is defensive only.
    
    N-6 FIX: Also sets flag to True when DATABASE_URL is not configured (DB disabled), so that
    future calls don't repeatedly check _enabled() and return early without setting the flag.
    """
    global _document_images_table_ready
    if _document_images_table_ready:
        return

    if not _enabled():
        # Mark as "ready" even when disabled — no DDL needed and no point rechecking
        _document_images_table_ready = True
        return
    
    with get_conn() as connection, connection.cursor() as cur:
        cur.execute(
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
        cur.execute(
            "CREATE INDEX IF NOT EXISTS document_images_doc_id_idx ON document_images (doc_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS document_images_mode_idx ON document_images (mode)"
        )
    
    _document_images_table_ready = True


def _content_type(ext: str) -> str:
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "bmp": "image/bmp",
        "tiff": "image/tiff",
    }.get(ext.lower(), "image/png")


def extract_and_store_pdf_images(
    *,
    file_path: str,
    doc_id: str,
    source: str,
    mode: str,
) -> list[dict[str, Any]]:
    """Extract non-decorative PDF images and persist their metadata."""
    images_dir = get_document_storage_dir(doc_id) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    image_index = 0
    with fitz.open(file_path) as pdf:
        for page_number, page in enumerate(pdf, start=1):
            for image_ref in page.get_images(full=True):
                xref = image_ref[0]
                base_image = pdf.extract_image(xref)
                if not base_image:
                    continue
                image_bytes = base_image.get("image") or b""
                if len(image_bytes) < MIN_IMAGE_BYTES:
                    continue

                ext = str(base_image.get("ext") or "png").lower()
                checksum = hashlib.sha256(image_bytes).hexdigest()
                image_id = f"{doc_id}:image-{image_index + 1}"
                storage_path = (
                    images_dir
                    / f"page{page_number}-image{image_index + 1}-{checksum[:12]}.{ext}"
                )
                storage_path.write_bytes(image_bytes)

                rows.append(
                    {
                        "image_id": image_id,
                        "doc_id": doc_id,
                        "source": source,
                        "mode": mode,
                        "page": page_number,
                        "image_index": image_index,
                        "storage_path": str(storage_path),
                        "content_type": _content_type(ext),
                        "size_bytes": len(image_bytes),
                        "checksum": checksum,
                        "caption": None,
                    }
                )
                image_index += 1

    if rows and _enabled():
        ensure_document_images_table()
        with get_conn() as connection, connection.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO document_images (
                    image_id, doc_id, source, mode, page, image_index,
                    storage_path, content_type, size_bytes, checksum, caption
                )
                VALUES %s
                ON CONFLICT (image_id) DO UPDATE SET
                    source = EXCLUDED.source,
                    mode = EXCLUDED.mode,
                    page = EXCLUDED.page,
                    image_index = EXCLUDED.image_index,
                    storage_path = EXCLUDED.storage_path,
                    content_type = EXCLUDED.content_type,
                    size_bytes = EXCLUDED.size_bytes,
                    checksum = EXCLUDED.checksum,
                    caption = EXCLUDED.caption
                """,
                [
                    (
                        row["image_id"],
                        row["doc_id"],
                        row["source"],
                        row["mode"],
                        row["page"],
                        row["image_index"],
                        row["storage_path"],
                        row["content_type"],
                        row["size_bytes"],
                        row["checksum"],
                        row["caption"],
                    )
                    for row in rows
                ],
            )

    return rows


def list_document_images(doc_id: str) -> list[dict[str, Any]]:
    if not _enabled():
        return []
    ensure_document_images_table()
    with get_conn() as connection, connection.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    ) as cur:
        cur.execute(
            """
            SELECT image_id, doc_id, source, mode, page, image_index,
                   storage_path, content_type, size_bytes, checksum,
                   caption, created_at
            FROM document_images
            WHERE doc_id = %s
            ORDER BY page NULLS LAST, image_index
            """,
            (doc_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_document_image(image_id: str) -> dict[str, Any] | None:
    if not _enabled():
        return None
    ensure_document_images_table()
    with get_conn() as connection, connection.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    ) as cur:
        cur.execute(
            """
            SELECT image_id, doc_id, source, mode, page, image_index,
                   storage_path, content_type, size_bytes, checksum,
                   caption, created_at
            FROM document_images
            WHERE image_id = %s
            """,
            (image_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def delete_document_images(doc_id: str) -> int:
    if not _enabled():
        return 0
    ensure_document_images_table()
    with get_conn() as connection, connection.cursor() as cur:
        cur.execute("DELETE FROM document_images WHERE doc_id = %s", (doc_id,))
        return int(cur.rowcount or 0)
