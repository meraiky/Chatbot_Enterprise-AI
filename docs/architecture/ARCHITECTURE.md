# System Architecture: Enterprise AI Chatbot

## 1. Overview
The Enterprise AI Chatbot is a hybrid-retrieval RAG system designed to answer questions from internal and external document collections. The current codebase supports one FastAPI backend and two local clients: a Streamlit app and a React + Vite app.

## 2. High-Level Architecture
The system follows a decoupled client-server architecture:

- **Client A**: Streamlit in `frontend/app.py` for chat, document management, and usage visibility.
- **Client B**: React + Vite in `frontend/src/` for chat and admin workflows.
- **Backend**: FastAPI in `backend/` providing chat, document, usage, auth, and admin endpoints.
- **AI Layer**:
  - **LLM**: Google Gemini for answer generation.
  - **Embeddings**: Gemini embeddings for vectorization.
  - **Reranker**: Cross-encoder reranking over merged retrieval candidates.
- **Storage Layer**:
  - **Vector Store**: ChromaDB for document chunks and semantic search.
  - **Relational DB**: PostgreSQL with `pgvector` for topic guards and semantic cache.
  - **Cache**: Redis for exact-match answer caching.
  - **Usage DB**: SQLite for local token and latency tracking.

## 3. Core Request Flow
1. **Request**: A user sends a question from either the Streamlit or React client.
2. **Guardrail**: The backend checks topic guard rules before any LLM call.
3. **L1 Cache**: Redis is checked for an exact cached answer.
4. **L2 Cache / Retrieval Prep**: PostgreSQL-backed semantic cache and usage tracking are prepared.
5. **Retrieval**:
   - Chroma semantic search retrieves top candidates.
   - BM25 retrieval finds keyword-heavy matches.
   - Results are merged and deduplicated.
   - A reranker reorders candidates for final context selection.
6. **Generation**: The backend builds a mode-specific prompt and calls Gemini.
7. **Persistence**: The final reply and source list are cached for future requests.
8. **Observability**: Token usage and timing data are recorded for each request.

## 4. Design Notes
- **Two local clients** exist in the repo. Documentation and local setup should treat both as supported entrypoints until one is intentionally retired.
- **Hybrid retrieval** balances semantic recall with exact keyword matching.
- **Two-layer caching** reduces repeated LLM calls and improves response latency.
- **Stateless API layer** keeps the FastAPI service horizontally scalable.

## 5. Component Map
| Component | Technology | Responsibility |
|-----------|-------------|----------------|
| Streamlit client | Streamlit | Local chat/admin client |
| React client | React + Vite + TypeScript | Browser chat/admin client |
| API Gateway | FastAPI | Routing, auth, rate limiting |
| Vector DB | ChromaDB | Semantic indexing and search |
| Cache L1 | Redis | Exact-match Q&A cache |
| Cache L2 | PostgreSQL + pgvector | Semantic cache and guard data |
| LLM | Gemini | Response generation |
| Reranker | Cross-Encoder | Candidate ranking |
| Observability | Custom tracing + SQLite | Latency and token tracking |
