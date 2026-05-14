# Running Locally Without Docker

Use this guide when Docker is not available. You will manage PostgreSQL and Redis yourself.

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.12 | [python.org](https://www.python.org/downloads/) |
| Node.js | 20 | [nodejs.org](https://nodejs.org/) |
| PostgreSQL | 16 + pgvector | See Step 1 |
| Redis | 7 | Optional — app falls back to pgvector-only cache if unavailable |

---

## Step 1 — PostgreSQL with pgvector

### Option A: Neon (free hosted, recommended for quick start)

1. Sign up at [neon.tech](https://neon.tech) (free tier available)
2. Create a project, choose a region near you
3. Copy the **Connection String** — it looks like:
   ```
   postgresql://user:password@ep-xyz.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
4. pgvector is pre-installed on Neon — no extra setup needed

### Option B: Local PostgreSQL

1. Install PostgreSQL 16: [postgresql.org/download](https://www.postgresql.org/downloads/)
2. Install pgvector extension: [github.com/pgvector/pgvector](https://github.com/pgvector/pgvector#installation)
3. Create the database:
   ```bash
   psql -U postgres -c "CREATE DATABASE aiagent_db;"
   psql -U postgres -d aiagent_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
   ```
4. Connection string: `postgresql://postgres:postgres@localhost:5432/aiagent_db`

---

## Step 2 — Backend

```bash
cd backend

# Create and activate virtual environment
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
```

Edit `.env` — minimum required values:

```env
DATABASE_URL=postgresql://user:password@host/dbname   # from Step 1
JWT_SECRET_KEY=<run: python -c "import secrets; print(secrets.token_hex(32))">
ENCRYPTION_KEY=<run: python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())">
```

Optional (needed to actually chat with an LLM):

```env
GEMINI_API_KEY=your_key      # https://aistudio.google.com/app/apikey
# or
ANTHROPIC_API_KEY=your_key   # https://console.anthropic.com/
# or
# Add via Admin UI after first login (recommended)
```

```bash
# Run database migrations (creates all tables + pgvector HNSW indexes)
alembic upgrade head

# Seed demo users and topic-guard patterns
python -m scripts.seed_demo

# Start the API server
# Note: first run downloads ~420 MB sentence-transformers model
uvicorn main:app --reload --port 8000
```

Backend is ready at **http://localhost:8000/docs**

---

## Step 3 — Frontend

Open a new terminal:

```bash
cd frontend
npm install
npm run dev
```

Frontend is ready at **http://localhost:3000**

---

## Step 4 — Log in

After `seed_demo` completes, check the terminal output for the generated passwords:

```
✅ Demo seed complete
   admin: <random-password>
   alice: <random-password>
```

**To use fixed passwords for development**, set these in `.env` before running seed:
```env
SEED_ADMIN_PASSWORD=admin1234
SEED_ALICE_PASSWORD=alice1234
```

Then run `python backend/scripts/seed_demo.py` again.

> ⚠️ **Security**: Change passwords before exposing to any network. Random passwords are used by default for safety.

---

## Step 5 — Add an LLM API key

1. Log in as `admin` → Admin → API Keys
2. Add a Gemini, Anthropic, or OpenAI key
3. The key is stored encrypted in PostgreSQL — never in `.env`

---

## Troubleshooting

**`DATABASE_URL is not set`** — check that `.env` exists in `backend/` and `DATABASE_URL` is filled in.

**`relation "document_chunks" does not exist`** — migration did not run. Run `alembic upgrade head` again.

**Backend hangs on startup** — sentence-transformers is downloading the embedding model (~420 MB). Wait 1–3 minutes on first run.

**Redis unavailable** — the app logs a warning and continues with pgvector-only (L2) cache. This is fine for development.

**CORS error in browser** — add your frontend origin to `CORS_ORIGINS` in `.env`, e.g.:
```env
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

**Streamlit client (optional)**:
```bash
cd frontend
pip install -r requirements.txt
streamlit run app.py
```
