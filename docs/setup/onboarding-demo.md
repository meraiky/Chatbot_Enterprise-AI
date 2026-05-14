# Onboarding — Demo Mode

Get the chatbot running end-to-end in under five minutes using the bundled seed script and sample document.

---

## Prerequisites

- Docker and Docker Compose installed
- `.env` filled in (minimum: `JWT_SECRET_KEY`, `ENCRYPTION_KEY`, `DATABASE_URL`)

```bash
cp .env.example .env   # then edit JWT_SECRET_KEY and ENCRYPTION_KEY
```

---

## Step 1 — Start the stack

```bash
make dev
# or: docker compose up -d
```

Wait until `docker compose ps` shows all services healthy (postgres, redis, backend, frontend).

---

## Step 2 — Run migrations

```bash
make migrate
# or: docker compose exec backend alembic upgrade head
```

---

## Step 3 — Seed demo data

```bash
make seed
# or: docker compose exec backend python -m scripts.seed_demo
```

Output:

```
── Demo credentials ───────────────────────────────────
  username: admin        password: admin1234     role: admin
  username: alice        password: alice1234     role: user
  username: readonly     password: readonly123   role: user
────────────────────────────────────────────────────────
  API:      http://localhost:8000/docs
  Frontend: http://localhost:3000
────────────────────────────────────────────────────────
```

> Change all passwords before exposing the service to any network.

---

## Step 4 — Upload a sample document

Via the Swagger UI at `http://localhost:8000/docs`:

1. `POST /api/v1/auth/login` with `admin` / `admin1234` → copy the `access_token`.
2. Click **Authorize** (top right) and paste the token.
3. `POST /api/v1/document/upload` → upload any PDF (e.g. a company policy doc, a product spec).
4. Wait for the 200 response confirming the document was indexed.

Or via curl:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -d "username=admin&password=admin1234" | jq -r .access_token)

curl -s -X POST http://localhost:8000/api/v1/document/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/your.pdf"
```

---

## Step 5 — Ask a question

```bash
curl -s -X POST http://localhost:8000/api/v1/chat/message \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the main topic of the uploaded document?", "mode": "Internal"}' \
  | jq .answer
```

Or open `http://localhost:3000`, log in as `alice` / `alice1234`, and chat in the UI.

---

## Teardown

```bash
make stop          # stop containers, keep volumes
make clean         # stop containers AND delete volumes (wipes DB + documents)
```

---

## What the seed script does

| Action | Detail |
|---|---|
| Creates `admin` user | role = admin, bcrypt hashed password |
| Creates `alice` user | role = user |
| Creates `readonly` user | role = user |
| Seeds topic-guard patterns | 4 prompt-injection / jailbreak patterns |

It is safe to run multiple times — existing rows are skipped.
