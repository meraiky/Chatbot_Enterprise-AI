import json
import re
import csv
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import fitz  # PyMuPDF
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from app.services.rag.document_registry import (
    build_document_id,
    delete_existing_document,
    utc_now,
)
from app.core.config import settings
from app.services.usage_tracker import estimate_tokens, new_request_id, record_usage
from app.services.rag.vector_store import get_vector_store
from app.services.rag.cache_service import cache_service
from app.services.rag.document_mirror import mirror_document_chunks
from app.services.rag.injection_scanner import sanitize_chunk, scan_chunk


INDEX_BATCH_SIZE = 20
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".csv", ".xlsx"}


def _pdf_documents(file_path: str, doc_id: str, doc_type: str, source_name: str, checksum: str, uploaded_at: str) -> list[Document]:
    pages: list[Document] = []
    try:
        with fitz.open(file_path) as doc:
            for page_number, page in enumerate(doc, start=1):
                page_text = page.get_text().strip()
                page_text = re.sub(r"\s+", " ", page_text).strip()

                if page_text:
                    pages.append(
                        Document(
                            page_content=page_text,
                            metadata={
                                "doc_id": doc_id,
                                "source": source_name,
                                "type": doc_type,
                                "page": page_number,
                                "checksum": checksum,
                                "uploaded_at": uploaded_at,
                                "file_type": "pdf",
                            },
                        )
                    )
    except Exception as e:
        raise ValueError(f"Failed to read PDF: {e}")
    return pages


def _docx_documents(file_path: str, doc_id: str, doc_type: str, source_name: str, checksum: str, uploaded_at: str) -> list[Document]:
    try:
        with zipfile.ZipFile(file_path) as archive:
            xml_bytes = archive.read("word/document.xml")
    except Exception as exc:
        raise ValueError(f"Failed to read DOCX: {exc}") from exc

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    root = ET.fromstring(xml_bytes)
    blocks: list[str] = []

    for paragraph in root.findall(".//w:p", namespace):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace)).strip()
        if text:
            blocks.append(text)

    text = "\n".join(blocks).strip()
    if not text:
        return []

    return [
        Document(
            page_content=text,
            metadata={
                "doc_id": doc_id,
                "source": source_name,
                "type": doc_type,
                "page": 1,
                "checksum": checksum,
                "uploaded_at": uploaded_at,
                "file_type": "docx",
            },
        )
    ]


def _csv_documents(file_path: str, doc_id: str, doc_type: str, source_name: str, checksum: str, uploaded_at: str) -> list[Document]:
    encodings = ("utf-8-sig", "utf-8", "cp1258", "latin-1")
    rows: list[list[str]] | None = None
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            with open(file_path, newline="", encoding=encoding) as handle:
                rows = list(csv.reader(handle))
            break
        except Exception as exc:
            last_error = exc

    if rows is None:
        raise ValueError(f"Failed to read CSV: {last_error}")

    lines = [" | ".join(cell.strip() for cell in row if cell is not None).strip() for row in rows]
    text = "\n".join(line for line in lines if line).strip()
    if not text:
        return []

    return [
        Document(
            page_content=text,
            metadata={
                "doc_id": doc_id,
                "source": source_name,
                "type": doc_type,
                "page": 1,
                "checksum": checksum,
                "uploaded_at": uploaded_at,
                "file_type": "csv",
            },
        )
    ]


def _xlsx_documents(file_path: str, doc_id: str, doc_type: str, source_name: str, checksum: str, uploaded_at: str) -> list[Document]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise ValueError("openpyxl is not installed. Install backend requirements to upload Excel files.") from exc

    try:
        workbook = load_workbook(file_path, read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError(f"Failed to read XLSX: {exc}") from exc

    documents: list[Document] = []
    try:
        for sheet_index, sheet in enumerate(workbook.worksheets, start=1):
            lines: list[str] = [f"Sheet: {sheet.title}"]
            for row in sheet.iter_rows(values_only=True):
                values = [str(value).strip() for value in row if value is not None and str(value).strip()]
                if values:
                    lines.append(" | ".join(values))
            text = "\n".join(lines).strip()
            if len(lines) > 1:
                documents.append(
                    Document(
                        page_content=text,
                        metadata={
                            "doc_id": doc_id,
                            "source": source_name,
                            "type": doc_type,
                            "page": sheet_index,
                            "sheet": sheet.title,
                            "checksum": checksum,
                            "uploaded_at": uploaded_at,
                            "file_type": "xlsx",
                        },
                    )
                )
    finally:
        workbook.close()

    return documents


def _load_documents(file_path: str, doc_type: str, source_name: str, checksum: str, uploaded_at: str) -> list[Document]:
    doc_id = build_document_id(source_name, doc_type, checksum)
    suffix = Path(source_name).suffix.lower()
    if suffix == ".pdf":
        return _pdf_documents(file_path, doc_id, doc_type, source_name, checksum, uploaded_at)
    if suffix == ".docx":
        return _docx_documents(file_path, doc_id, doc_type, source_name, checksum, uploaded_at)
    if suffix == ".csv":
        return _csv_documents(file_path, doc_id, doc_type, source_name, checksum, uploaded_at)
    if suffix == ".xlsx":
        return _xlsx_documents(file_path, doc_id, doc_type, source_name, checksum, uploaded_at)
    if suffix == ".doc":
        raise ValueError("Legacy .doc files are not supported. Please save the file as .docx and upload again.")
    if suffix == ".xls":
        raise ValueError("Legacy .xls files are not supported. Please save the file as .xlsx or .csv and upload again.")
    raise ValueError(f"Unsupported file type: {suffix or 'unknown'}")


def process_and_index_file(file_path: str, doc_type: str, source_name: str, checksum: str):
    """
    Reads supported document types, splits to chunks, and saves to VectorDB.
    doc_type: 'Internal' or 'External'
    """
    doc_id = build_document_id(source_name, doc_type, checksum)
    uploaded_at = utc_now()
    pages = _load_documents(file_path, doc_type, source_name, checksum, uploaded_at)

    if not pages:
        raise ValueError("Document does not contain extractable text.")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=100,
        length_function=len
    )

    documents = text_splitter.split_documents(pages)
    documents = [doc for doc in documents if doc.page_content.strip()]
    for document in documents:
        scan = scan_chunk(document.page_content)
        if scan["risk_score"] > 0:
            document.page_content = sanitize_chunk(document.page_content)
            document.metadata["injection_sanitized"] = True
            document.metadata["injection_findings"] = ",".join(scan["findings"])

    if not documents:
        raise ValueError("PDF text was extracted, but no indexable chunks were created.")

    vector_store = get_vector_store()
    replaced_chunks = delete_existing_document(doc_id)
    all_ids = []
    for start in range(0, len(documents), INDEX_BATCH_SIZE):
        batch = documents[start : start + INDEX_BATCH_SIZE]
        ids = [
            f"{doc_id}:chunk-{start + index + 1}"
            for index in range(len(batch))
        ]
        all_ids.extend(ids)
        vector_store.add_documents(batch, ids=ids)

    mirror_document_chunks(documents=documents, ids=all_ids)

    request_id = new_request_id()
    embedding_tokens = sum(estimate_tokens(document.page_content) for document in documents)
    usage = record_usage(
        request_id=request_id,
        operation="document_embedding",
        mode=doc_type,
        model=settings.EMBEDDING_MODEL,
        input_tokens=embedding_tokens,
        estimated=True,
        metadata=json.dumps({"doc_id": doc_id, "source": source_name}),
    )
    
    # Invalidate semantic cache for this mode since context has changed
    cache_service.clear_cache_by_mode(doc_type)
    
    return {
        "doc_id": doc_id,
        "chunks_indexed": len(documents),
        "replaced_chunks": replaced_chunks,
        "usage": usage,
        "uploaded_at": uploaded_at,
    }


def process_and_index_pdf(file_path: str, doc_type: str, source_name: str, checksum: str):
    return process_and_index_file(file_path, doc_type, source_name, checksum)
