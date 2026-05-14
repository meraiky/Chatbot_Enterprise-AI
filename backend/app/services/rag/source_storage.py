from __future__ import annotations

import os
import shutil
from pathlib import Path

from app.core.config import settings


def _safe_filename(filename: str) -> str:
    return Path(filename or "document.pdf").name.replace("\\", "-").replace("/", "-")


def store_source_file(
    *,
    temp_file_path: str,
    doc_id: str,
    source_name: str,
    checksum: str,
) -> str:
    """Persist the original uploaded file so indexes can be rebuilt from source."""
    storage_root = Path(settings.DOCUMENT_STORAGE_DIR).resolve()
    target_dir = storage_root / doc_id
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _safe_filename(source_name)
    suffix = Path(safe_name).suffix or ".pdf"
    target_path = target_dir / f"source-{checksum[:12]}{suffix}"
    shutil.copy2(temp_file_path, target_path)
    return str(target_path)


def get_document_storage_dir(doc_id: str) -> Path:
    storage_root = Path(settings.DOCUMENT_STORAGE_DIR).resolve()
    target_dir = (storage_root / doc_id).resolve()
    if storage_root not in target_dir.parents and target_dir != storage_root:
        raise ValueError("Document storage path is outside configured storage directory.")
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def delete_source_files(doc_id: str) -> int:
    storage_root = Path(settings.DOCUMENT_STORAGE_DIR).resolve()
    target_dir = (storage_root / doc_id).resolve()
    if storage_root not in target_dir.parents and target_dir != storage_root:
        raise ValueError("Refusing to delete outside document storage directory.")
    if not target_dir.exists():
        return 0
    count = sum(1 for path in target_dir.rglob("*") if path.is_file())
    shutil.rmtree(target_dir)
    return count


def source_file_exists(path: str | None) -> bool:
    return bool(path) and os.path.exists(path)
