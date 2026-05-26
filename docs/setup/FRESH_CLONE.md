# Fresh Clone Runbook

Shortest safe path from zero to running app.

> **Windows users:** Option A (Docker) commands below work in PowerShell or CMD.
> For Option B (local), see the Windows-specific commands in that section.
> Alternatively, run `scripts/setup.sh` inside WSL2 for the fully automated path.

---

## 1. Clone

```bash
git clone https://github.com/meraiky/Chatbot_Enterprise-AI
cd Chatbot_Enterprise-AI
```

---

## 2. Choose Runtime Path

### Option A — Docker (Recommended, all platforms)

Requires Docker Desktop.

**Linux / Mac:**
```bash
cp .env.example .env
bash scripts/setup.sh   # auto-generates secrets, builds, seeds
```

**Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

Then edit `.env` and fill in the required secrets. Generate them with:
```powershell
python -c "import secrets, base64; print('JWT_SECRET_KEY=' + secrets.token_hex(32)); print('ENCRYPTION_KEY=' + base64.b64encode(secrets.token_bytes(32)).decode()); print('REDIS_PASSWORD=' + secrets.token_urlsafe(16)); print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(16))"
```

Start (first run downloads ~420 MB embedding model — allow 3–5 minutes):
```bash
docker compose up --build -d
docker compose logs -f backend   # wait for: "Application startup complete"
```

Seed demo users (run after "Application startup complete" appears):
```bash
docker compose exec backend python -m scripts.seed_demo
```

> Migrations run automatically on backend startup — no manual Alembic step needed.

Add an LLM API key to start chatting:
open `http://localhost:3000` → log in with credentials printed by seed_demo → Admin → API Keys.

| URL | Purpose |
|---|---|
| `http://localhost:3000` | Frontend |
| `http://localhost:8000/docs` | Backend API docs |
| `http://localhost:8000/health` | Health check |

---

### Option B — Local Without Docker

Requires Python 3.12, Node.js 20, PostgreSQL 16 + pgvector, and Redis 7.

**Linux / Mac:**
```bash
cp .env.example backend/.env
# edit backend/.env: set JWT_SECRET_KEY, ENCRYPTION_KEY, DATABASE_URL, REDIS_URL

cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.seed_demo
uvicorn main:app --host 127.0.0.1 --port 8000
```

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 3000
```

**Windows (PowerShell):**
```powershell
Copy-Item .env.example backend\.env
# edit backend\.env: set JWT_SECRET_KEY, ENCRYPTION_KEY, DATABASE_URL, REDIS_URL

cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m scripts.seed_demo
.\.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 3000
```

---

## 3. Verify

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

```bash
cd backend && python -m pytest tests/unit -q
cd frontend && npm run build
```

---

## 4. Never Commit

```
.env
backend/.env
.venv/
backend/.venv/
frontend/node_modules/
frontend/dist/
backend/storage/
*.log
*.db
```
