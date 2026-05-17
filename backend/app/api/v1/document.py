import os
import shutil
import tempfile
import logging
import hashlib
from pathlib import Path as FilePath
from typing import Literal, List, Dict, Any

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Path as PathParam
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from app.core.auth import get_current_admin, TokenData

from app.services.rag.data_ingestion import process_and_index_file
from app.services.rag.document_registry import (
    build_document_id,
    delete_indexed_document,
    list_indexed_documents,
)
from app.services.rag.document_mirror import rebuild_chroma_from_mirror
from app.services.rag.document_images import (
    delete_document_images,
    extract_and_store_pdf_images,
    get_document_image,
    list_document_images,
)
from app.services.rag.ingestion_jobs import (
    delete_ingestion_job,
    get_ingestion_job,
    update_ingestion_job,
    upsert_ingestion_job,
)
from app.services.rag.source_storage import (
    delete_source_files,
    source_file_exists,
    store_source_file,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _public_upload_error(error: Exception) -> str:
    message = str(error).lower()
    if "api key not valid" in message or "api_key_invalid" in message:
        return "Gemini API key is invalid. Update GEMINI_API_KEY in backend/.env and restart the backend."
    if "gemini_api_key is not configured" in message:
        return "GEMINI_API_KEY is not configured in backend/.env."
    if "permission" in message and "chroma" in message:
        return "ChromaDB storage is not writable. Check backend/chroma_db permissions."
    if "does not contain extractable text" in message:
        return "Document does not contain extractable text. For scanned PDFs, upload an OCR/text PDF."
    if "legacy .doc" in message or "legacy .xls" in message or "unsupported file type" in message:
        return str(error)
    return "Failed to process document. Please check the file and try again."


SUPPORTED_UPLOAD_EXTENSIONS = {".pdf", ".doc", ".docx", ".csv", ".xls", ".xlsx"}
SUPPORTED_UPLOAD_LABEL = "PDF, DOCX, CSV, or XLSX"

class DocumentInfo(BaseModel):
    """Information about an indexed document."""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "doc_id": "internal-policy-abc123",
                "source": "HR_Policy_2024.pdf",
                "type": "Internal",
                "chunks": 45,
                "pages": 12,
                "uploaded_at": "2024-05-01T10:00:00Z",
                "checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "legacy": False
            }
        }
    )

    doc_id: str = Field(..., description="Unique identifier of the document")
    source: str = Field(..., description="Original filename of the document")
    type: str = Field(..., description="Document mode: Internal or External")
    chunks: int = Field(..., description="Number of text chunks indexed")
    pages: int = Field(..., description="Number of pages in the document")
    uploaded_at: str = Field(..., description="ISO timestamp of upload")
    checksum: str = Field(..., description="SHA-256 checksum of the file")
    legacy: bool = Field(..., description="Whether the document was indexed using the legacy system")

class DocumentListResponse(BaseModel):
    """Response for listing all indexed documents."""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "documents": [
                    {
                        "doc_id": "internal-policy-abc123",
                        "source": "HR_Policy_2024.pdf",
                        "type": "Internal",
                        "chunks": 45,
                        "pages": 12,
                        "uploaded_at": "2024-05-01T10:00:00Z",
                        "checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                        "legacy": False
                    }
                ]
            }
        }
    )

    documents: List[DocumentInfo]


class DocumentModeSummary(BaseModel):
    """Indexed document and chunk counts for one chat mode."""
    documents: int
    chunks: int


class DocumentSummaryResponse(BaseModel):
    """Indexed document summary by mode."""
    Internal: DocumentModeSummary
    External: DocumentModeSummary


class UploadResponse(BaseModel):
    """Response for successful document upload and indexing."""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "Document uploaded and indexed successfully",
                "doc_id": "internal-policy-abc123",
                "chunks_indexed": 45,
                "replaced_chunks": 0,
                "usage": {
                    "request_id": "req_xyz789",
                    "operation": "document_embedding",
                    "total_tokens": 12000
                }
            }
        }
    )

    message: str = Field(..., description="Status message")
    doc_id: str = Field(..., description="Generated unique ID for the document")
    chunks_indexed: int = Field(..., description="Number of chunks created and indexed")
    replaced_chunks: int = Field(..., description="Number of existing chunks replaced (if any)")
    usage: Dict[str, Any] = Field(..., description="Token usage for the embedding process")

class DeleteResponse(BaseModel):
    """Response for successful document deletion."""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "Document deleted successfully",
                "deleted_chunks": 45
            }
        }
    )

    message: str = Field(..., description="Status message")
    deleted_chunks: int = Field(..., description="Number of chunks removed from the vector store")


class RebuildVectorStoreResponse(BaseModel):
    """Result of rebuilding local Chroma from durable PostgreSQL mirror."""
    chunks: int
    documents: int


class IngestionJobResponse(BaseModel):
    """Current ingestion/indexing status for a document."""
    doc_id: str
    source: str
    mode: str
    checksum: str
    storage_path: str | None = None
    status: str
    progress: int
    progress_message: str | None = None
    chunks_indexed: int = 0
    replaced_chunks: int = 0
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None


class DocumentImageResponse(BaseModel):
    """Image or diagram extracted from an uploaded document."""
    image_id: str
    doc_id: str
    source: str
    mode: str
    page: int | None = None
    image_index: int
    content_type: str
    size_bytes: int
    checksum: str
    caption: str | None = None
    created_at: str | None = None


class DocumentImagesResponse(BaseModel):
    images: list[DocumentImageResponse]


def file_checksum(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _serialize_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in job.items()
    }


@router.get("", response_model=DocumentListResponse)
async def list_documents(current_user: TokenData = Depends(get_current_admin)):
    """
    List all documents currently indexed in the vector store.
    
    Returns a sorted list of documents with their metadata, including chunk counts and upload dates.
    """
    try:
        return {"documents": list_indexed_documents()}
    except Exception:
        logger.exception("Failed to list indexed documents")
        raise HTTPException(status_code=500, detail="Failed to retrieve document list.")


@router.get("/summary", response_model=DocumentSummaryResponse)
async def document_summary(current_user: TokenData = Depends(get_current_admin)):
    """Return indexed document and chunk counts by chat mode."""
    try:
        summary = {
            "Internal": {"documents": 0, "chunks": 0},
            "External": {"documents": 0, "chunks": 0},
        }
        for document in list_indexed_documents():
            doc_type = document.get("type")
            if doc_type not in summary:
                continue
            summary[doc_type]["documents"] += 1
            summary[doc_type]["chunks"] += int(document.get("chunks") or 0)
        return summary
    except Exception:
        logger.exception("Failed to summarize indexed documents")
        raise HTTPException(status_code=500, detail="Failed to retrieve document summary.")


@router.get("/ingestion/{doc_id}", response_model=IngestionJobResponse)
async def ingestion_status(
    doc_id: str = PathParam(..., min_length=1),
    current_user: TokenData = Depends(get_current_admin),
):
    """Return persisted upload/indexing status for a document."""
    job = get_ingestion_job(doc_id)
    if not job:
        raise HTTPException(status_code=404, detail="Ingestion job was not found.")
    return _serialize_job(job)


@router.get("/{doc_id}/images", response_model=DocumentImagesResponse)
async def document_images(
    doc_id: str = PathParam(..., min_length=1),
    current_user: TokenData = Depends(get_current_admin),
):
    """List images/diagrams extracted from a document."""
    images = [
        _serialize_job({key: value for key, value in image.items() if key != "storage_path"})
        for image in list_document_images(doc_id)
    ]
    return {"images": images}


@router.get("/images/{image_id}/content")
async def document_image_content(
    image_id: str = PathParam(..., min_length=1),
    current_user: TokenData = Depends(get_current_admin),
):
    """Return an extracted PDF image file for display next to relevant answers."""
    image = get_document_image(image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Document image was not found.")
    storage_path = str(image.get("storage_path") or "")
    if not storage_path or not os.path.exists(storage_path):
        raise HTTPException(status_code=404, detail="Document image file was not found.")
    return FileResponse(
        storage_path,
        media_type=str(image.get("content_type") or "application/octet-stream"),
        filename=FilePath(storage_path).name,
    )


@router.post("/rebuild-vector-store", response_model=RebuildVectorStoreResponse)
async def rebuild_vector_store(
    doc_id: str | None = None,
    mode: Literal["Internal", "External"] | None = None,
    current_user: TokenData = Depends(get_current_admin),
):
    """Rebuild local Chroma from the durable PostgreSQL document_chunks mirror."""
    try:
        return rebuild_chroma_from_mirror(doc_id=doc_id, mode=mode)
    except Exception:
        logger.exception("Failed to rebuild vector store from mirror")
        raise HTTPException(status_code=500, detail="Failed to rebuild vector store.")


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    doc_type: Literal["Internal", "External"] = Form(..., description="The target mode for the document"),
    file: UploadFile = File(..., description="The document file to be indexed"),
    current_user: TokenData = Depends(get_current_admin)
):
    """
    Upload and index a document into the RAG system.
    
    The process includes:
    1. Text extraction from PDF, DOCX, CSV, or XLSX.
    2. Text splitting into chunks.
    3. Generating embeddings and storing them in the vector database.
    4. Invalidating the semantic cache for the specified mode.
    
    Security limits:
    - Max file size: 50MB (enforced by nginx)
    - File extension: .pdf, .docx, .csv, .xlsx
    - Legacy .doc/.xls receive a clear conversion error
    """
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    
    source_name = FilePath(file.filename or "").name
    suffix = FilePath(source_name).suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Only {SUPPORTED_UPLOAD_LABEL} files are supported.")
    
    temp_file_path = ""
    doc_id: str | None = None  # M-4 fix: Declare before try block
    try:
        # Read file and validate size
        file.file.seek(0)
        content = await file.read()
        file_size = len(content)

        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large: {file_size / (1024*1024):.1f}MB. Maximum allowed: {MAX_FILE_SIZE / (1024*1024):.0f}MB"
            )

        if file_size == 0:
            raise HTTPException(status_code=400, detail="Empty file uploaded")

        # M-8 fix: Magic-byte check for PDF, DOCX, XLSX
        if suffix == ".pdf" and not content[:5] == b"%PDF-":
            raise HTTPException(status_code=400, detail="Invalid file: not a valid PDF.")
        # DOCX/XLSX are ZIP files (PK\x03\x04 magic bytes)
        if suffix in {".docx", ".xlsx"} and not content[:4] == b"PK\x03\x04":
            raise HTTPException(status_code=400, detail=f"Invalid file: not a valid {suffix.upper()[1:]} file.")
        
        # Write to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".upload") as buffer:
            temp_file_path = buffer.name
            buffer.write(content)

        checksum = file_checksum(temp_file_path)
        doc_id = build_document_id(source_name, doc_type, checksum)
        storage_path = store_source_file(
            temp_file_path=temp_file_path,
            doc_id=doc_id,
            source_name=source_name,
            checksum=checksum,
        )
        upsert_ingestion_job(
            doc_id=doc_id,
            source=source_name,
            mode=doc_type,
            checksum=checksum,
            storage_path=storage_path,
            status="processing",
            progress=20,
            progress_message="Source file saved; indexing document.",
        )
        if suffix == ".pdf":
            extracted_images = extract_and_store_pdf_images(
                file_path=temp_file_path,
                doc_id=doc_id,
                source=source_name,
                mode=doc_type,
            )
            if extracted_images:
                update_ingestion_job(
                    doc_id=doc_id,
                    status="processing",
                    progress=35,
                    progress_message=f"Extracted {len(extracted_images)} image(s); indexing text.",
                )

        result = process_and_index_file(
            temp_file_path,
            doc_type,
            source_name,
            checksum,
        )
        update_ingestion_job(
            doc_id=doc_id,
            status="indexed",
            progress=100,
            progress_message="Document indexed successfully.",
            chunks_indexed=result.get("chunks_indexed"),
            replaced_chunks=result.get("replaced_chunks"),
        )
    except ValueError as e:
        if doc_id is not None:  # M-4 fix: Use explicit None check
            assert doc_id is not None  # Type narrowing for Pyrefly
            update_ingestion_job(
                doc_id=doc_id,
                status="failed",
                progress=100,
                progress_message="Document indexing failed.",
                error_message=_public_upload_error(e),
            )
        raise HTTPException(status_code=400, detail=_public_upload_error(e))
    except Exception as e:
        logger.exception("Failed to index uploaded document %s", source_name)
        if doc_id is not None:  # M-4 fix: Use explicit None check
            assert doc_id is not None  # Type narrowing for Pyrefly
            update_ingestion_job(
                doc_id=doc_id,
                status="failed",
                progress=100,
                progress_message="Document indexing failed.",
                error_message=_public_upload_error(e),
            )
        raise HTTPException(status_code=500, detail=_public_upload_error(e))
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        await file.close()

    return {
        "message": "Document uploaded and indexed successfully",
        **result,
    }


@router.post("/reprocess/{doc_id}", response_model=UploadResponse)
async def reprocess_document(
    doc_id: str = PathParam(..., min_length=1, description="The document ID to re-index from stored source file"),
    current_user: TokenData = Depends(get_current_admin),
):
    """
    Re-index a document from the persisted raw source file.

    This is useful when local Chroma is stale, embedding settings changed, or an
    earlier indexing run failed after the source file was saved.
    """
    job = get_ingestion_job(doc_id)
    if not job:
        raise HTTPException(status_code=404, detail="Ingestion job was not found.")

    storage_path = job.get("storage_path")
    if not source_file_exists(storage_path):
        raise HTTPException(status_code=404, detail="Stored source file was not found.")
    assert storage_path is not None  # Type narrowing for Pyrefly (already checked above)

    source_name = str(job.get("source") or "document.pdf")
    doc_type = str(job.get("mode") or "Internal")
    checksum = str(job.get("checksum") or "")

    try:
        update_ingestion_job(
            doc_id=doc_id,
            status="processing",
            progress=20,
            progress_message="Re-indexing from stored source file.",
        )
        if FilePath(source_name).suffix.lower() == ".pdf":
            assert storage_path is not None  # Type narrowing for Pyrefly
            extracted_images = extract_and_store_pdf_images(
                file_path=storage_path,
                doc_id=doc_id,
                source=source_name,
                mode=doc_type,
            )
            if extracted_images:
                update_ingestion_job(
                    doc_id=doc_id,
                    status="processing",
                    progress=35,
                    progress_message=f"Extracted {len(extracted_images)} image(s); indexing text.",
                )
        assert storage_path is not None  # Type narrowing for Pyrefly
        result = process_and_index_file(storage_path, doc_type, source_name, checksum)
        update_ingestion_job(
            doc_id=doc_id,
            status="indexed",
            progress=100,
            progress_message="Document re-indexed successfully.",
            chunks_indexed=result.get("chunks_indexed"),
            replaced_chunks=result.get("replaced_chunks"),
        )
    except ValueError as e:
        update_ingestion_job(
            doc_id=doc_id,
            status="failed",
            progress=100,
            progress_message="Document re-indexing failed.",
            error_message=_public_upload_error(e),
        )
        raise HTTPException(status_code=400, detail=_public_upload_error(e))
    except Exception as e:
        logger.exception("Failed to re-index stored document %s", doc_id)
        update_ingestion_job(
            doc_id=doc_id,
            status="failed",
            progress=100,
            progress_message="Document re-indexing failed.",
            error_message=_public_upload_error(e),
        )
        raise HTTPException(status_code=500, detail=_public_upload_error(e))

    return {
        "message": "Document re-indexed successfully",
        **result,
    }


@router.delete("/{doc_id}", response_model=DeleteResponse)
async def delete_document(
    doc_id: str = PathParam(..., min_length=1, description="The unique identifier of the document to delete"),
    current_user: TokenData = Depends(get_current_admin)
):
    """
    Delete a document and all its associated chunks from the vector store.
    
    This operation also invalidates the semantic cache for the document's mode to ensure
    that subsequent queries do not use outdated information.
    """
    try:
        deleted_chunks = delete_indexed_document(doc_id)
    except Exception:
        logger.exception("Failed to delete indexed document %s", doc_id)
        raise HTTPException(status_code=500, detail="Failed to delete document.")

    if deleted_chunks == 0:
        raise HTTPException(status_code=404, detail="Document was not found.")

    delete_document_images(doc_id)
    delete_source_files(doc_id)
    delete_ingestion_job(doc_id)

    return {
        "message": "Document deleted successfully",
        "deleted_chunks": deleted_chunks,
    }
