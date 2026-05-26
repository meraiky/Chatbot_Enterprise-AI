"""Unit tests for document upload and admin endpoints."""

import io
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Document upload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_returns_202_and_queues(client):
    """Valid PDF upload must return 202 with doc_id and poll_url, not block."""
    pdf_bytes = b"%PDF-1.4 fake pdf content for testing"
    mock_result = {
        "message": "ok",
        "doc_id": "internal-test-abc123",
        "chunks_indexed": 10,
        "replaced_chunks": 0,
        "usage": {},
    }
    with (
        patch("app.api.v1.document.store_source_file", return_value="/tmp/stored.pdf"),
        patch("app.api.v1.document.upsert_ingestion_job"),
        patch("app.api.v1.document.update_ingestion_job"),
        patch("app.api.v1.document.build_document_id", return_value="internal-test-abc123"),
        patch("app.api.v1.document.process_and_index_file", return_value=mock_result),
        patch("app.api.v1.document.extract_and_store_pdf_images", return_value=[]),
    ):
        response = await client.post(
            "/api/v1/document/upload",
            data={"doc_type": "Internal"},
            files={"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )

    assert response.status_code == 202
    body = response.json()
    assert "doc_id" in body
    assert "poll_url" in body
    assert body["status"] == "queued"


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_extension(client):
    """Non-PDF/DOCX/CSV/XLSX files must be rejected with 400."""
    response = await client.post(
        "/api/v1/document/upload",
        data={"doc_type": "Internal"},
        files={"file": ("malware.exe", io.BytesIO(b"MZ binary"), "application/octet-stream")},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_empty_file(client):
    """Empty files must be rejected with 400."""
    with (
        patch("app.api.v1.document.store_source_file", return_value="/tmp/stored.pdf"),
        patch("app.api.v1.document.upsert_ingestion_job"),
        patch("app.api.v1.document.build_document_id", return_value="x"),
    ):
        response = await client.post(
            "/api/v1/document/upload",
            data={"doc_type": "Internal"},
            files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_invalid_pdf_magic_bytes(client):
    """File with .pdf extension but wrong magic bytes must be rejected."""
    response = await client.post(
        "/api/v1/document/upload",
        data={"doc_type": "Internal"},
        files={"file": ("fake.pdf", io.BytesIO(b"not-a-pdf-content"), "application/pdf")},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file(client):
    """Files above 50MB must be rejected with 413."""
    oversized = b"%PDF-" + b"x" * (51 * 1024 * 1024)
    response = await client.post(
        "/api/v1/document/upload",
        data={"doc_type": "Internal"},
        files={"file": ("big.pdf", io.BytesIO(oversized), "application/pdf")},
    )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_reprocess_returns_202(client):
    """/reprocess/{doc_id} must return 202 and queue the job, not block."""
    mock_job = {
        "doc_id": "internal-test-abc123",
        "source": "test.pdf",
        "mode": "Internal",
        "checksum": "abc",
        "storage_path": "/tmp/stored.pdf",
        "status": "indexed",
        "progress": 100,
    }
    with (
        patch("app.api.v1.document.get_ingestion_job", return_value=mock_job),
        patch("app.api.v1.document.source_file_exists", return_value=True),
        patch("app.api.v1.document.update_ingestion_job"),
        patch("app.api.v1.document.process_and_index_file", return_value={}),
    ):
        response = await client.post("/api/v1/document/reprocess/internal-test-abc123")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert "poll_url" in body


@pytest.mark.asyncio
async def test_reprocess_404_when_job_missing(client):
    """Reprocess must return 404 when ingestion job does not exist."""
    with patch("app.api.v1.document.get_ingestion_job", return_value=None):
        response = await client.post("/api/v1/document/reprocess/nonexistent-id")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_topic_guards(client):
    """GET /admin/topic-guards must return a list."""
    mock_guards = [
        {
            "id": 1,
            "pattern": "violence",
            "mode": None,
            "reason": None,
            "is_regex": False,
            "is_active": True,
            "created_at": "2024-01-01T00:00:00+00:00",
        }
    ]
    with patch("app.api.v1.admin.topic_guard_service.list_guards", return_value=mock_guards):
        response = await client.get("/api/v1/admin/topic-guards")
    assert response.status_code == 200
    assert isinstance(response.json().get("guards"), list)


@pytest.mark.asyncio
async def test_cache_stats_returns_data(client):
    """GET /admin/qa-cache/stats must return stats dict."""
    mock_stats = {"total_entries": 42, "total_hits": 100, "hit_rate": 0.8, "top_questions": []}
    with patch("app.api.v1.admin.cache_service.get_stats", return_value=mock_stats):
        response = await client.get("/api/v1/admin/qa-cache/stats")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ingestion_status_returns_job(client):
    """GET /document/ingestion/{doc_id} must return job status."""
    mock_job = {
        "doc_id": "internal-test-abc123",
        "source": "test.pdf",
        "mode": "Internal",
        "checksum": "abc",
        "storage_path": "/tmp/stored.pdf",
        "status": "queued",
        "progress": 10,
        "progress_message": "Queued.",
        "chunks_indexed": 0,
        "replaced_chunks": 0,
        "error_message": None,
        "created_at": None,
        "updated_at": None,
        "completed_at": None,
    }
    with patch("app.api.v1.document.get_ingestion_job", return_value=mock_job):
        response = await client.get("/api/v1/document/ingestion/internal-test-abc123")
    assert response.status_code == 200
    assert response.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_ingestion_status_404_when_missing(client):
    """GET /document/ingestion/{doc_id} must return 404 when job not found."""
    with patch("app.api.v1.document.get_ingestion_job", return_value=None):
        response = await client.get("/api/v1/document/ingestion/ghost-id")
    assert response.status_code == 404
