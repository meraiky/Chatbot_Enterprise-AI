# Fresh Clone Runbook

This is the shortest safe path for a new developer who has just cloned the
project.

## 1. Clone

```powershell
git clone <repo-url> Chatbot_Enterprise-AI
cd Chatbot_Enterprise-AI
```

## 2. Choose Runtime Path

### Option A - Docker Recommended

Requires Docker Desktop.

```powershell
Copy-Item .env.example .env
```

Edit `.env`:

```env
JWT_SECRET_KEY=<generated-secret>
ENCRYPTION_KEY=<generated-32-byte-base64-key>
REDIS_PASSWORD=<generated-redis-password>
DATABASE_URL=postgresql://postgres:postgres@db:5432/aiagent_db
REDIS_URL=redis://:<generated-redis-password>@redis:6379/0
```

Generate secrets:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Start (first run downloads ~420 MB embedding model — be patient):

```powershell
docker compose up --build -d
docker compose logs -f backend   # wait for "Application startup complete"
```

Run migrations and seed demo data:

```powershell
docker compose exec backend alembic upgrade head
docker compose exec backend python -m scripts.seed_demo
```

Add an LLM API key (required to get chat answers):

Open `http://localhost:8000/docs` → Authorize as `admin / admin1234` → `POST /api/v1/admin/keys`

Open:

- Frontend: `http://localhost:3000`  (log in: `admin / admin1234`)
- Backend docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`

### Option B - Local Without Docker

Requires Python, Node.js, and a reachable PostgreSQL database with `pgvector`.
Redis is optional; the backend falls back when Redis is unavailable.

Create env:

```powershell
Copy-Item .env.example .env
```

Edit `.env`:

```env
JWT_SECRET_KEY=<generated-secret>
ENCRYPTION_KEY=<generated-32-byte-base64-key>
DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<database>
REDIS_URL=redis://localhost:6379/0
```

Backend:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r backend\requirements.txt

cd backend
..\.venv\Scripts\python -m alembic upgrade head
..\.venv\Scripts\python -m scripts.seed_demo
..\.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

If `py -3.12` is not installed, use your available Python 3 version. Python
3.14 has been smoke-tested locally, but Python 3.12 is the safer target.

Frontend:

```powershell
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 3000
```

## 3. Verify

```powershell
curl.exe http://127.0.0.1:8000/health
curl.exe http://127.0.0.1:8000/ready

cd frontend
npm run build

cd ..\backend
..\.venv\Scripts\python -m pytest tests\unit -q
..\.venv\Scripts\python -m pytest tests\integration -q
```

## 4. Do Not Commit

Never commit:

- `.env`
- `backend/.env`
- `.venv/`
- `backend/.venv/`
- `frontend/node_modules/`
- `frontend/dist/`
- `backend/storage/`
- `backend/chroma_db/`
- `*.log`
- `*.db`
