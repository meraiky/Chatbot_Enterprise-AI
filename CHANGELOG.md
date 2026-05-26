# Changelog

All notable changes to this project are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [1.0.0] — 2026-05-14

### Added
- **Hybrid RAG pipeline** — pgvector semantic search + BM25 keyword retrieval with cross-encoder reranking
- **Multi-model routing** — support for Google Gemini, Anthropic Claude, and OpenAI GPT with per-user API key configuration
- **Two-layer caching** — Redis exact-match cache (L1) and PostgreSQL pgvector semantic cache (L2)
- **Topic guard** — pgvector-based out-of-scope query detection before any LLM call
- **Web search fallback** — Google, Bing, and DuckDuckGo integration for out-of-document queries
- **Admin dashboard** — user management, usage analytics, document upload, retrieval health (React UI)
- **JWT authentication** — full auth flow with rotating refresh tokens and encrypted API key storage
- **Document management** — PDF upload with async indexing (202 + poll_url pattern), Internal/External visibility
- **Streaming responses** — SSE endpoint for chunk-by-chunk answer delivery
- **React + Vite frontend** — TypeScript SPA with Zustand state management and Tailwind CSS
- **Alembic migrations** — 18 versioned schema migrations
- **GitHub Actions CI** — lint + unit tests + Docker build on every PR
- **GitHub Actions CD** — push Docker images to Docker Hub on merge to main
- **Docker Compose** — full local stack: backend + PostgreSQL + Redis + frontend
- **Observability** — structured JSON logging, per-request token and latency tracking
