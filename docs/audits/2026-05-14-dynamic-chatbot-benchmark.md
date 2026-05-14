# Dynamic Chatbot Benchmark - 2026-05-14

## Source And Method

Primary source: GitHub repository search for `chatbot`, sorted by stars:
https://github.com/search?q=chatbot&type=repositories&s=stars&o=desc

Supplemental direct repository checks were used for major RAG/agentic chatbot platforms that do not always rank in the raw `chatbot` search despite being stronger architectural comparators.

Snapshot time: 2026-05-14 Asia/Saigon.

Weighted score:

| Criteria | Weight |
|---|---:|
| Stars | 15% |
| Recent activity | 15% |
| Architecture quality | 20% |
| Production readiness | 20% |
| Documentation quality | 10% |
| Enterprise capability | 15% |
| OSS professionalism | 5% |

Filtered out:

- Tutorials, datasets, model-training notes, and NLP resource collections.
- Archived or deprecated projects.
- Pure frontend clients without substantial backend/RAG/agent architecture.
- Rule-based or legacy chatbot frameworks without modern LLM architecture.
- SDKs and messaging libraries rather than chatbot systems.
- Low-activity projects where recent pushes are older than the 12-month threshold.

## Final Top 10 Benchmark Set

| Rank | Repository | Stars | Last Push | Benchmark Fit | Score |
|---:|---|---:|---|---|---:|
| 1 | [langgenius/dify](https://github.com/langgenius/dify) | 141,260 | 2026-05-13 | Agentic workflow and RAG platform with strong production posture. | 94 |
| 2 | [open-webui/open-webui](https://github.com/open-webui/open-webui) | 136,915 | 2026-05-13 | Self-hosted multi-model AI interface with RAG, Ollama/OpenAI support, plugins, and active community. | 91 |
| 3 | [Mintplex-Labs/anything-llm](https://github.com/Mintplex-Labs/anything-llm) | 59,989 | 2026-05-13 | Privacy-first self-hosted document chat/productivity system with strong app packaging. | 88 |
| 4 | [FlowiseAI/Flowise](https://github.com/FlowiseAI/Flowise) | 52,792 | 2026-05-12 | Visual low-code agent and RAG builder with broad integrations. | 87 |
| 5 | [pathwaycom/llm-app](https://github.com/pathwaycom/llm-app) | 59,745 | 2026-01-07 | Enterprise RAG templates for live data, cloud deployment, and data integrations. | 85 |
| 6 | [danny-avila/LibreChat](https://github.com/danny-avila/LibreChat) | 36,958 | 2026-05-13 | Self-hosted multi-provider ChatGPT-style app with agents, MCP, auth, presets, and strong UX. | 84 |
| 7 | [QuivrHQ/quivr](https://github.com/QuivrHQ/quivr) | 39,151 | 2025-07-09 | Opinionated RAG integration platform with multi-LLM and multi-vector-store support. | 80 |
| 8 | [Cinnamon/kotaemon](https://github.com/Cinnamon/kotaemon) | 25,378 | 2026-04-03 | Focused RAG document-chat tool, useful as a retrieval UX comparator. | 78 |
| 9 | [chatchat-space/Langchain-Chatchat](https://github.com/chatchat-space/Langchain-Chatchat) | 38,015 | 2025-11-10 | Local knowledge-base RAG and agent app with strong self-hosted orientation. | 77 |
| 10 | [1Panel-dev/MaxKB](https://github.com/1Panel-dev/MaxKB) | 20,958 | 2026-05-13 | Enterprise-grade open-source agent platform, strong operational fit. | 76 |

Near misses:

| Repository | Reason |
|---|---|
| [lm-sys/FastChat](https://github.com/lm-sys/FastChat) | Excellent LLM serving/evaluation system, but less directly comparable to enterprise RAG chatbot products. |
| [botpress/botpress](https://github.com/botpress/botpress) | Strong agent builder, but lower GitHub traction than the selected RAG/product platforms in this snapshot. |
| [RasaHQ/rasa](https://github.com/RasaHQ/rasa) | Mature conversational AI framework, but not primarily a modern LLM/RAG architecture. |
| [vercel/chatbot](https://github.com/vercel/chatbot) | High-quality full-stack AI chatbot template, but less enterprise/RAG complete than selected systems. |
| [coze-dev/coze-studio](https://github.com/coze-dev/coze-studio) | Strong agent platform candidate, but scored just below the Top 10 on maturity and benchmark fit. |
| [dataelement/bisheng](https://github.com/dataelement/bisheng) | Very relevant enterprise AI platform; lower current star/community signal than selected comparators. |
| [Tencent/WeKnora](https://github.com/Tencent/WeKnora) | Strong knowledge/RAG platform candidate; kept as a watchlist item because it is newer relative to the leaders. |

## Current Project Position

Project: `F:\Chatbot_Enterprise-AI`

Observed local architecture (updated 2026-05-14 post-migration):

- FastAPI backend with chat, auth, document, usage, and admin endpoints.
- React + Vite frontend; Streamlit retained as optional secondary client only.
- Hybrid retrieval: pgvector semantic search, BM25, RRF rank fusion, and cross-encoder reranking — all in one PostgreSQL database.
- Two-layer cache: Redis exact cache (L1) plus pgvector semantic cache (L2, cosine similarity).
- Topic guard backed by pgvector similarity check.
- Single storage backend: PostgreSQL + pgvector for document chunks, semantic cache, topic guard, and history. ChromaDB removed.
- Local sentence-transformers/all-mpnet-base-v2 embeddings (768 dims, no external API call, fits Neon HNSW index limit).
- Docker Compose, GitHub Actions CI/CD, security notes, architecture docs, and audit docs exist.

Estimated score against the same weighted model:

| Criteria | Weight | Score | Notes |
|---|---:|---:|---|
| Stars | 15% | 0 | Local/unpublished repo, no community signal yet. |
| Recent activity | 15% | 95 | Active local work and recent docs/code updates. |
| Architecture quality | 20% | 88 | +6 from ChromaDB removal: single-backend pgvector, no dual-store inconsistency, HNSW indexes, vendor-independent embeddings. |
| Production readiness | 20% | 76 | +8 from ChromaDB removal (no local disk vector store) and multi-stage Docker. Missing eval, load testing, and monitoring remain blockers. |
| Documentation quality | 10% | 82 | +4: Design Decisions section added, architecture diagram updated, setup docs reorganised. |
| Enterprise capability | 15% | 72 | Auth, admin, RAG, audit/security direction are present; needs RBAC depth, tenancy, SSO, retention, and governed ingestion. |
| OSS professionalism | 5% | 78 | +3: License, contributing, security, changelog, CI, and consistent tech stack. |

Weighted score excluding public popularity: 82/100.

Weighted score including public popularity: 70/100.

## Gap Analysis Against Top Benchmarks

Highest-value gaps:

1. ~~Replace or production-harden local Chroma.~~ **DONE (2026-05-14)**
   - Resolved: ChromaDB removed. All document chunks, semantic cache, and topic guard now live in PostgreSQL/pgvector. Single operational surface, one backup strategy, HNSW indexes enabled. Embeddings generated locally via sentence-transformers/all-mpnet-base-v2 (768 dims, no API dependency).

2. Add retrieval evaluation as a first-class subsystem.
   - Current risk: retrieval quality is described but not continuously measured.
   - Benchmark pattern: stronger projects expose evaluation, traces, datasets, or repeatable quality checks.
   - Recommended target: golden Q&A set, recall@k, MRR, answer faithfulness, negative/out-of-scope tests, and CI report.

3. Expand enterprise identity and access control.
   - Current risk: JWT exists, but enterprise adoption usually needs richer auth boundaries.
   - Benchmark pattern: LibreChat, Dify, Open WebUI, and AnythingLLM emphasize multi-user, workspace, provider, or admin controls.
   - Recommended target: RBAC enforcement matrix, per-document ACLs, workspace/org scope, OAuth2/OIDC/SSO.

4. Add model/provider routing as a product feature.
   - Current risk: multi-model support exists in documentation, but benchmark leaders expose model/provider selection and policy controls as core UX/admin features.
   - Recommended target: provider registry, fallback policy, per-role model access, cost caps, and usage attribution.

5. Strengthen observability and operations.
   - Current risk: health endpoints and logs exist, but production comparators trend toward tracing, metrics, dashboards, and deployment recipes.
   - Recommended target: OpenTelemetry traces, Prometheus metrics, structured audit retention, load testing, alerting, backup/restore runbooks.

6. Improve app packaging and onboarding.
   - Current risk: local setup is documented, but benchmark leaders reduce first-run friction.
   - Recommended target: one-command seed/demo mode, sample docs, admin bootstrap, scripted health check, and screenshots/GIFs in README.

## Recommended Roadmap To Reach Benchmark Parity

### Phase 1 - Production RAG Core

- ~~Implement a vector backend abstraction.~~ **DONE** — PgVectorStore class wraps all pgvector access with a stable interface.
- ~~Migrate primary retrieval to pgvector.~~ **DONE** — ChromaDB removed, pgvector is the sole vector backend.
- Add ingestion consistency checks to CI or admin health.
- Add retrieval eval dataset and CLI. *(see `docs/audits/retrieval-eval-plan.md`)*

### Phase 2 - Enterprise Controls

- Add workspace/org model.
- Add document-level ACLs.
- Add RBAC policy matrix tests.
- Add OAuth2/OIDC/SSO integration.
- Add audit retention and export policy.

### Phase 3 - Product Maturity

- Add provider/model registry in admin UI.
- Add routing policy, fallback policy, and cost controls.
- Add usage analytics by user/workspace/provider/model.
- Add polished onboarding: screenshots, seed data, demo script, deployment guide.

### Phase 4 - OSS Benchmark Readiness

- Publish architecture diagrams and screenshots in README.
- Add public roadmap and issue labels.
- Add example deployment profiles: local, single VM, Docker Compose, cloud.
- Add benchmark/eval reports under `docs/audits/`.

## Watchlist For Future Benchmark Refreshes

- [coze-dev/coze-studio](https://github.com/coze-dev/coze-studio)
- [dataelement/bisheng](https://github.com/dataelement/bisheng)
- [Tencent/WeKnora](https://github.com/Tencent/WeKnora)
- [botpress/botpress](https://github.com/botpress/botpress)
- [vercel/chatbot](https://github.com/vercel/chatbot)
- [lm-sys/FastChat](https://github.com/lm-sys/FastChat)

