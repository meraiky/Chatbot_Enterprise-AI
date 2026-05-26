from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from app.services.rag.cache_service import cache_service
from app.services.rag.document_mirror import delete_mirrored_document
from app.services.rag.vector_store import get_vector_store


def build_document_id(source_name: str, doc_type: str, checksum: str) -> str:
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", source_name).strip("-").lower()
    digest = hashlib.sha256(f"{doc_type}:{source_name}:{checksum}".encode()).hexdigest()
    return f"{doc_type.lower()}-{safe_name[:48]}-{digest[:12]}"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _legacy_document_id(source: str, doc_type: str) -> str:
    digest = hashlib.sha256(f"{doc_type}:{source}".encode()).hexdigest()
    return f"legacy-{digest[:12]}"


def _document_from_group(doc_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    first = items[0]
    pages = sorted({item["page"] for item in items if item.get("page") is not None})
    return {
        "doc_id": doc_id,
        "source": first.get("source", "Unknown"),
        "type": first.get("type", "Unknown"),
        "chunks": len(items),
        "pages": len(pages),
        "uploaded_at": first.get("uploaded_at", ""),
        "checksum": first.get("checksum", ""),
        "legacy": first.get("legacy", False),
    }


def list_indexed_documents() -> list[dict[str, Any]]:
    vector_store = get_vector_store()
    result = vector_store.get_all_metadatas()

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for metadata in result.get("metadatas") or []:
        if not metadata:
            continue
        source = metadata.get("source", "Unknown")
        doc_type = metadata.get("type", "Unknown")
        doc_id = metadata.get("doc_id")
        normalized = {
            "source": source,
            "type": doc_type,
            "page": metadata.get("page"),
            "uploaded_at": metadata.get("uploaded_at", ""),
            "checksum": metadata.get("checksum", ""),
            "legacy": not bool(doc_id),
        }
        groups[doc_id or _legacy_document_id(source, doc_type)].append(normalized)

    documents = [_document_from_group(doc_id, items) for doc_id, items in groups.items()]
    return sorted(documents, key=lambda item: item.get("uploaded_at") or item["source"], reverse=True)


def delete_indexed_document(doc_id: str) -> int:
    documents = list_indexed_documents()
    target = next((d for d in documents if d["doc_id"] == doc_id), None)
    if not target:
        return 0

    vector_store = get_vector_store()

    if target.get("legacy"):
        deleted_count = vector_store.delete_by_source_type(target["source"], target["type"])
    else:
        deleted_count = vector_store.delete_by_doc_id(doc_id)

    if deleted_count > 0:
        cache_service.clear_cache_by_mode(target["type"])
        if not target.get("legacy"):
            delete_mirrored_document(doc_id)

    return deleted_count


def delete_existing_document(doc_id: str) -> int:
    vector_store = get_vector_store()
    deleted_count = vector_store.delete_by_doc_id(doc_id)
    delete_mirrored_document(doc_id)
    return deleted_count
