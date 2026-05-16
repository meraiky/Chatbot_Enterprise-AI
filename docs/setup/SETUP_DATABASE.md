# Database Setup

The project uses PostgreSQL 16 + pgvector for everything: document chunks, semantic cache, topic guard, and user data.

---

## Option 1: Docker Compose (automatic)

If you use `docker compose up`, a `pgvector/pgvector:pg16` container starts automatically. No manual setup needed.

---

## Option 2: Neon (free hosted Postgres)

[Neon](https://neon.tech) provides a free PostgreSQL instance with pgvector pre-installed.

1. Sign up at [neon.tech](https://neon.tech)
2. Create a project → choose the region nearest to you
3. Copy the **Connection String** from the dashboard:
   ```
   postgresql://user:password@ep-xyz.region.aws.neon.tech/neondb?sslmode=require
   ```
4. Set it in `.env`:
   ```env
   DATABASE_URL=postgresql://user:password@ep-xyz.region.aws.neon.tech/neondb?sslmode=require
   ```

---

## Option 3: Local PostgreSQL

1. Install PostgreSQL 16: [postgresql.org/download](https://www.postgresql.org/downloads/)
2. Install pgvector: [github.com/pgvector/pgvector](https://github.com/pgvector/pgvector#installation)
3. Create database and enable extension:
   ```bash
   psql -U postgres -c "CREATE DATABASE aiagent_db;"
   psql -U postgres -d aiagent_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
   ```
4. Connection string:
   ```env
   DATABASE_URL=postgresql://postgres:postgres@localhost:5432/aiagent_db
   ```

---

## Running Migrations

After setting `DATABASE_URL`, run the 11 Alembic migrations to create all tables:

```bash
# Docker
make migrate

# Manual
cd backend && alembic upgrade head
```

This creates: `qa_cache`, `topic_guard`, `users`, `document_chunks`, and all supporting tables + HNSW indexes.

---

## Verifying the Schema

Connect with any PostgreSQL client (psql, DBeaver, pgAdmin) and run:

```sql
\dt                          -- list all tables
SELECT COUNT(*) FROM users;  -- should be 0 (or 3 after make seed)
SELECT * FROM pg_extension WHERE extname = 'vector';  -- confirm pgvector is installed
```

---

## Redis (optional)

Redis is used for L1 exact-match cache. The app works without it, falling back to L2 pgvector semantic cache.

- Docker: included in `docker-compose.yml`
- Local Windows: download from [github.com/tporadowski/redis/releases](https://github.com/tporadowski/redis/releases)
- Local Linux/macOS: `apt install redis` or `brew install redis`
- `.env`: set `REDIS_PASSWORD`, then use `REDIS_URL=redis://:<same-password>@localhost:6379/0`
