# Infrastructure & Operations

## 1. Deployment Architecture
The system is containerized using Docker to ensure environment consistency across development, staging, and production.

### 1.1 Container Orchestration
The system uses `docker-compose` to manage a multi-container stack:
- **Backend**: FastAPI application running in a Python 3.11+ environment.
- **Frontend**: Streamlit client in `frontend/app.py` and React application served via Vite in `frontend/src/`.
- **Database**: PostgreSQL with the `pgvector` extension for vector similarity search.
- **Cache**: Redis for L1 exact-match Q&A caching.
- **Vector Store**: ChromaDB for document indexing and semantic retrieval.

### 1.2 Environment Configuration
Configuration is managed via environment variables (defined in `.env`), allowing local and deployed environments to supply `GEMINI_API_KEY`, `DATABASE_URL`, `REDIS_URL`, CORS origins, and related runtime settings.

## 2. CI/CD Pipeline
The project utilizes GitHub Actions for automated quality assurance and deployment.

### 2.1 Continuous Integration (CI)
Triggered on every push or pull request to `main` and `develop` branches:
- **Linting**: Code style checks using `ruff`.
- **Testing**: Execution of unit and integration tests using `pytest`.
- **Build Check**: Verification that the Docker images build successfully.

### 2.2 Continuous Deployment (CD)
Triggered on merges to `main` or version tags:
- **Image Push**: Builds the production image and pushes it to the Docker Registry.
- **Deployment**: Automated rollout to the target environment (placeholders provided in `cd.yml`).

### 2.3 Security Scanning
A dedicated security workflow runs weekly:
- **Bandit**: Scans Python code for common security issues.
- **Safety**: Checks dependencies for known vulnerabilities.
- **Trivy**: Scans Docker images for OS-level vulnerabilities.

## 3. Observability & Monitoring
The system implements a "Lean Observability" stack:
- **Structured Logging**: Uses `structlog` to produce JSON logs, making them easily searchable in log aggregators (e.g., ELK or Grafana Loki).
- **Performance Tracing**: Custom `Trace` spans measure the latency of retrieval, reranking, and LLM generation.
- **Usage Tracking**: A dedicated SQLite database records every token spent and the duration of every operation, enabling precise cost and performance analysis.

## 4. Maintenance
- **Database Migrations**: Managed via `Alembic`. Schema changes are versioned and applied incrementally.
- **Cache Management**: Admin endpoints allow for clearing the Redis L1 and PostgreSQL L2 caches to force re-indexing or update answers.
