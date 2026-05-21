# RAG Pipeline Deep Dive

## 1. Retrieval Strategy
The system uses a **Hybrid Retrieval** approach to maximize both semantic understanding and keyword precision.

Before retrieval, a lightweight intent guard handles obvious greetings, empty prompts, and out-of-scope questions without spending embedding or LLM tokens.

## 0. Document Ingestion

### Extraction Pipeline (MinerU-first with PyMuPDF fallback)

Admin document upload now uses a **dual-backend extraction strategy** for maximum quality:

`Document upload` → `save raw file under DOCUMENT_STORAGE_DIR` → `MinerU extraction (primary)` → `PyMuPDF fallback (if needed)` → `extract images/diagrams` → `document_ingestion_jobs: processing` → `chunking` → `pgvector indexing` → `document_chunks mirror` → `document_ingestion_jobs: indexed`

The raw file mirror is intentionally local-first (`./storage/documents` by default) so the deployment can later swap it for S3/MinIO without changing the chat pipeline.

Extracted document images are recorded in `document_images`. This borrows Arkon's useful document-image foundation: diagrams and screenshots are no longer lost at ingestion time. Captions can be added later with a vision model and surfaced beside citations.

### MinerU Extraction (Primary)

**Technology**: `magic-pdf` — Advanced document extraction with layout awareness.

**Capabilities**:
- Layout analysis (headers, paragraphs, lists, tables, images)
- OCR on scanned pages
- Table structure recognition
- Formula detection
- Clean Markdown output optimized for LLM consumption

**Supported formats**: `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.doc`

**Installation**: `pip install magic-pdf[full]` for full OCR support.

**Graceful degradation**: If MinerU is not installed or extraction fails, the system automatically falls back to PyMuPDF.

### PyMuPDF Extraction (Fallback)

**Technology**: `pymupdf` (fitz) — Fast, reliable plain-text extraction.

**Use case**: Fallback when MinerU is unavailable or fails, or for simple PDFs where layout awareness is not critical.

**Limitation**: No layout awareness, table structure, or formula detection.

### Extractor Metadata

Each indexed chunk includes an `extractor` metadata field (`"mineru"` or `"pymupdf"`) for observability and quality analysis.

### 1.1 Vector Search (Semantic)
- **Technology**: pgvector + sentence-transformers embeddings.
- **Mechanism**: Converts the user query into a high-dimensional vector. It then performs a cosine similarity search against the indexed document chunks.
- **Strength**: Captures conceptual meaning. For example, a query about "vacation policy" will find documents mentioning "annual leave" even if the exact words differ.

### 1.2 BM25 Search (Keyword)
- **Technology**: `rank_bm25` (Okapi BM25 algorithm).
- **Mechanism**: A probabilistic model that ranks documents based on the frequency of query terms relative to their frequency across the entire corpus.
- **Persistence**: The index is persisted to disk using `pickle` and validated via SHA-256 checksums to avoid rebuilding on every request.
- **Strength**: Captures exact matches. Essential for finding specific product IDs, technical terms, or unique identifiers that embeddings might "smooth over".

### 1.3 Rank Fusion and Deduplication
The results from Vector and BM25 search are fused with **Reciprocal Rank Fusion (RRF)**. This avoids comparing incompatible raw scores directly and rewards chunks that rank well in both semantic and keyword search. Deduplication is performed based on document content before reranking.

## 2. Precision Ranking (Reranking)
To solve the "lost in the middle" problem and improve context quality, the system employs a **Cross-Encoder Reranker**.

- **Process**: The top-K candidates from the hybrid search are passed to a Cross-Encoder model.
- **Mechanism**: Unlike Bi-Encoders (used in vector search), the Cross-Encoder processes the query and the document simultaneously, allowing for deep interaction between the two.
- **Outcome**: The candidates are re-sorted by a precise relevance score. Only the top-N most relevant chunks are passed to the LLM.

## 3. Context Construction
The final context is built by:
1. Selecting the top-N reranked documents.
2. Formatting them with source metadata (filename, page number).
3. Rejecting weak retrieval results with `MIN_RERANK_SCORE` so unrelated chunks do not reach the LLM.
4. Truncating the total context to fit within `MAX_CONTEXT_CHARS` to prevent prompt overflow and reduce token costs.

Recommended defaults for balanced quality/cost:
- `RETRIEVAL_CANDIDATES_K=10`
- `FINAL_CONTEXT_K=3`
- `MAX_CONTEXT_CHARS=8000`
- `MIN_RERANK_SCORE=0.05`
- `CACHE_SIMILARITY_THRESHOLD=0.10`

## 4. Parallel Orchestration (Orca-style)

**Technology**: `orchestrator.py` — ThreadPoolExecutor-based parallel execution.

**Capabilities**:
- Parallel retrieval (vector + BM25 + external search)
- Batch document processing
- Context isolation via deep copy
- Graceful error handling per task

**Use cases**:
- Concurrent vector and BM25 search (reduces retrieval latency)
- Batch document ingestion
- Multi-source retrieval with external APIs

**Example**:
```python
from app.services.orchestrator import parallel_retrieval

results = parallel_retrieval(
    vector_search_fn=lambda: vector_store.similarity_search(query, k=10),
    bm25_search_fn=lambda: bm25_searcher.search(query, k=10),
)
vector_docs = results['vector_results']
bm25_docs = results['bm25_results']
```

## 5. Memory Layer (AgentMemory Integration)

**Technology**: `memory_service.py` — PostgreSQL-based conversation persistence.

**Database**: `conversation_memory` table in PostgreSQL (same database as main app).

### How It Works

1. **Store**: After each successful query, the system stores both the user question and assistant reply in PostgreSQL `conversation_memory` table, keyed by `conversation_id`.

2. **Recall**: Before processing a new query, the system recalls recent conversation history (default: last 5 turns) to provide context-aware responses.

3. **Privacy**: Memory is isolated per `conversation_id`. Users can clear their own conversation history via API.

4. **Schema**: Table is managed by Alembic migration `018_conversation_memory.py`; [`database.py`](../../backend/app/core/database.py) keeps a direct-creation fallback for environments where migrations are unavailable.

### Memory Types

- **Short-term**: Last 5 turns (configurable) recalled automatically for context.
- **Long-term**: Full conversation history stored in PostgreSQL, queryable via API.

### Privacy Controls

- Memory is opt-in per conversation (requires `conversation_id`).
- Users can clear their conversation memory at any time.
- Memory is stored in PostgreSQL (same database as main app) with proper indexing for fast retrieval.
- Backed up automatically with main database (Railway/Docker deployments).

### API Functions

```python
from app.services.memory_service import (
    store_conversation_turn,
    recall_conversation_context,
    clear_conversation_memory,
    get_conversation_history,
)

# Store a turn
store_conversation_turn(conversation_id, "user", question)
store_conversation_turn(conversation_id, "assistant", reply)

# Recall context
context = recall_conversation_context(conversation_id, limit=5)

# Clear memory
deleted = clear_conversation_memory(conversation_id)

# Get full history
history = get_conversation_history(conversation_id, limit=20)
```

## 6. Summary Flow

`Query` → `Light Intent Guard` → `AgentMemory Recall` → `Vector Search` + `BM25 Search` (parallel) → `RRF Fusion` → `Cross-Encoder Rerank` → `Context Window` → `LLM` → `AgentMemory Store` → `Cache Store`

## 7. Feature Integration Summary

| Feature | Technology | Purpose | Status |
|---------|-----------|---------|--------|
| **MinerU Extraction** | magic-pdf | Layout-aware document extraction with OCR, table recognition, formula detection | ✅ Integrated |
| **AgentMemory** | PostgreSQL | Conversation persistence and context recall | ✅ Integrated |
| **Orca Orchestration** | ThreadPoolExecutor | Parallel retrieval and batch processing | ✅ Integrated |
| **Hybrid Retrieval** | pgvector + BM25 | Semantic + keyword search | ✅ Existing |
| **Reranking** | Cross-Encoder | Precision ranking | ✅ Existing |
| **Semantic Cache** | Redis | Query result caching | ✅ Existing |
| **Injection Scanner** | Pattern matching | Prompt injection defense | ✅ Existing |
| **Topic Guard** | LLM-based | Content policy enforcement | ✅ Existing |
