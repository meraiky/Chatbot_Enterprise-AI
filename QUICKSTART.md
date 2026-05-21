# 🚀 Quick Start Guide

Get the Enterprise AI Chatbot running in **5 minutes**.

---

## Prerequisites

- **Docker** + **Docker Compose** (recommended)
- OR: **Python 3.12**, **Node.js 20**, **PostgreSQL 16**, **Redis 7**

---

## Option 1: Docker (Recommended)

### 1. Clone and Setup

```bash
git clone <repository-url>
cd Chatbot_Enterprise-AI
cp .env.example .env
```

### 2. Generate Secrets

Run this command and copy the output into your `.env` file:

```bash
python -c "import base64, secrets; print(f'JWT_SECRET_KEY={secrets.token_hex(32)}\nENCRYPTION_KEY={base64.b64encode(secrets.token_bytes(32)).decode()}\nREDIS_PASSWORD={secrets.token_urlsafe(16)}\nPOSTGRES_PASSWORD={secrets.token_urlsafe(16)}')"
```

### 3. Start Everything

```bash
docker compose up --build -d
```

Wait 1–3 minutes for the backend to become healthy (first run downloads the ~420 MB embedding model).

```bash
# Check when ready
docker compose logs -f backend
# Look for: "Application startup complete"
```

### 4. Seed Demo Users

> **Migrations run automatically** when the backend starts — no manual step needed.
> Once you see "Application startup complete" in the logs, the schema is ready.

```bash
# Seed demo users + topic guard patterns
make seed

# If you do not have make:
docker compose exec backend python -m scripts.seed_demo
```

**Copy the generated credentials from the terminal output!**

### 5. Open the App

Go to **http://localhost:3000**

Login with the credentials from step 4.

### 6. Add an LLM API Key

1. Click **Admin** → **API Keys**
2. Add your Gemini, OpenAI, or Anthropic API key
3. Start chatting!

---

## Option 2: Local Development (No Docker)

### 1. Setup Backend

```bash
# Clone and setup
git clone <repository-url>
cd Chatbot_Enterprise-AI
cp backend/.env.example backend/.env

# Generate secrets (copy output to backend/.env)
python -c "import base64, secrets; print(f'JWT_SECRET_KEY={secrets.token_hex(32)}\nENCRYPTION_KEY={base64.b64encode(secrets.token_bytes(32)).decode()}')"

# For local demo seeding, keep ENVIRONMENT=development.

# Install dependencies
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Setup database (PostgreSQL 16 + pgvector must be running)
# Update DATABASE_URL in backend/.env first
alembic upgrade head

# Seed demo users
python -m scripts.seed_demo

# Start backend
uvicorn main:app --reload
```

Backend runs at **http://localhost:8000**

### 2. Setup Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at **http://localhost:3000**

### 3. Login and Add API Key

Same as Docker steps 5-6 above.

---

## 🔒 Security Checklist

Before deploying to production:

- [ ] Change `POSTGRES_PASSWORD` to a strong password
- [ ] Change `REDIS_PASSWORD` to a strong password
- [ ] Set `ENVIRONMENT=production` in `.env`
- [ ] Set `ALLOW_DEV_AUTH_BYPASS=false` (critical!)
- [ ] Change admin password after first login
- [ ] Review `CORS_ORIGINS` and restrict to your domain
- [ ] Enable HTTPS and set `ENABLE_HSTS=true`
- [ ] Review [`SECURITY.md`](SECURITY.md) for full security model

---

## 📚 Next Steps

- **Upload Documents**: Admin → Documents → Upload PDF
- **Configure Models**: Admin → Model Config
- **View Usage**: Admin → Token Usage
- **Topic Guards**: Admin → Topic Guards (block unwanted topics)

---

## 🐛 Troubleshooting

**"DATABASE_URL is not set"**
→ Check that `.env` exists and `DATABASE_URL` is filled in

**"relation 'document_chunks' does not exist"**
→ Migrations run automatically on startup. If you see this, the backend may have started before the DB was ready. Run `make migrate` or restart the backend container.

**Backend hangs on startup**
→ First run downloads ~420MB embedding model. Wait 1-3 minutes.

**"Too many login attempts"**
→ Wait 5 minutes. Rate limit: 5 attempts per 5 minutes per IP.

**CORS error in browser**
→ Add your frontend URL to `CORS_ORIGINS` in `.env`

**Can't upload PDF**
→ Max file size is 50MB. Check file size and MIME type.

---

## 📖 Full Documentation

- [`README.md`](README.md) - Full project overview
- [`docs/setup/FRESH_CLONE.md`](docs/setup/FRESH_CLONE.md) - Detailed setup guide
- [`docs/setup/RUN_LOCAL.md`](docs/setup/RUN_LOCAL.md) - Local development guide
- [`SECURITY.md`](SECURITY.md) - Security model and best practices
- [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md) - System architecture

---

## 🆘 Need Help?

- Check [`docs/setup/RUN_LOCAL.md`](docs/setup/RUN_LOCAL.md) for detailed troubleshooting
- Review logs: `docker compose logs -f backend`
- Open an issue on GitHub
