# RAG Pipeline Deep Dive

## 1. Retrieval Strategy
The system uses a **Hybrid Retrieval** approach to maximize both semantic understanding and keyword precision.

Before retrieval, a lightweight intent guard handles obvious greetings, empty prompts, and out-of-scope questions without spending embedding or LLM tokens.

## 0. Document Ingestion
Admin PDF upload now keeps both the original source file and the search index:

`PDF upload` -> `save raw PDF under DOCUMENT_STORAGE_DIR` -> `extract PDF images/diagrams` -> `document_ingestion_jobs: processing` -> `PyMuPDF text extraction` -> `chunking` -> `Chroma indexing` -> `Neon document_chunks mirror` -> `document_ingestion_jobs: indexed`

The raw file mirror is intentionally local-first (`./storage/documents` by default) so the deployment can later swap it for S3/MinIO without changing the chat pipeline.

Extracted document images are recorded in `document_images`. This borrows Arkon's useful document-image foundation: diagrams and screenshots are no longer lost at ingestion time. Captions can be added later with a vision model and surfaced beside citations.

### 1.1 Vector Search (Semantic)
- **Technology**: ChromaDB + Google Generative AI Embeddings.
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

## 4. Summary Flow
`Query` $\rightarrow$ `Light Intent Guard` $\rightarrow$ `Vector Search` + `BM25 Search` $\rightarrow$ `RRF Fusion` $\rightarrow$ `Cross-Encoder Rerank` $\rightarrow$ `Context Window` $\rightarrow$ `LLM`
