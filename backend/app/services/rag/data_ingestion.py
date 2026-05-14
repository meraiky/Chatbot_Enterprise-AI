import json

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


def process_and_index_pdf(file_path: str, doc_type: str, source_name: str, checksum: str):
    """
    Reads PDF, splits to chunks, and saves to VectorDB.
    doc_type: 'Internal' or 'External'
    """
    doc_id = build_document_id(source_name, doc_type, checksum)
    uploaded_at = utc_now()
    pages = []
    try:
        with fitz.open(file_path) as doc:
            for page_number, page in enumerate(doc, start=1):
                page_text = page.get_text().strip()
                # Lean Prompt Strategy: Basic text cleaning to remove redundant whitespace/newlines
                import re
                page_text = re.sub(r'\s+', ' ', page_text).strip()
                
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
                            },
                        )
                    )
    except Exception as e:
        raise ValueError(f"Failed to read PDF: {e}")

    if not pages:
        raise ValueError("PDF does not contain extractable text.")

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
