# 🚀 Production Deployment Guide

This guide provides the architectural requirements and step-by-step instructions to deploy the Enterprise AI Chatbot into a production environment.

---

## 🏗️ Production Architecture

In production, we move away from a single-node `docker-compose` setup to a distributed architecture:

### 1. Infrastructure Components
- **Application Server**: Containerized FastAPI (Backend) and Nginx/React (Frontend) deployed on AWS ECS, Kubernetes, Railway, or Render.
- **Database**: Managed PostgreSQL 16 with `pgvector` (e.g., AWS RDS, Neon, or Supabase). **Do not run DB in a container for production.**
- **Cache**: Managed Redis (e.g., AWS ElastiCache, Upstash, or Redis Cloud).
- **Storage**: S3-compatible object storage for PDF documents (instead of local disk) for better scalability.
- **SSL/TLS**: HTTPS termination via Cloudflare, AWS ALB, or Nginx.

### 2. Request Flow
`User` $\rightarrow$ `HTTPS (Port 443)` $\rightarrow$ `Load Balancer / Nginx` $\rightarrow$ `FastAPI (Backend)` $\rightarrow$ `Managed DB/Redis`

---

## 🛠️ Step-by-Step Deployment

### Step 1: Infrastructure Provisioning
1. **Database**: Create a PostgreSQL 16 instance and enable the `pgvector` extension:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
2. **Redis**: Provision a Redis instance and note the connection URL.
3. **Storage**: Create an S3 bucket for document storage.

### Step 2: Production Environment Configuration
Create a production `.env` file (or use your platform's Secret Manager). **NEVER commit this file.**

| Variable | Production Value | Note |
|---|---|---|
| `ENVIRONMENT` | `production` | Disables Swagger UI and dev bypasses |
| `JWT_SECRET_KEY` | `(random 64+ chars)` | Use `openssl rand -base64 48` |
| `ENCRYPTION_KEY` | `(random 32-byte base64)` | Used for LLM API keys |
| `DATABASE_URL` | `postgresql://user:pass@host:5432/db?sslmode=require` | Use SSL for DB connections |
| `REDIS_URL` | `rediss://:pass@host:6379/0` | Use `rediss://` for SSL |
| `CORS_ORIGINS` | `https://chat.yourdomain.com` | Restrict to your actual domain |
| `ALLOW_DEV_AUTH_BYPASS` | `false` | **CRITICAL**: Must be false |
| `ENABLE_HSTS` | `true` | Enforce HTTPS |

### Step 3: Backend Optimization
For production, run FastAPI using **Gunicorn** with **Uvicorn workers** for better concurrency:

```bash
# Example command for 4 workers
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000
```

### Step 4: Frontend Deployment
1. Build the production bundle:
   ```bash
   npm run build
   ```
2. Serve the `dist/` folder using Nginx.
3. Ensure `VITE_API_URL` points to your production backend HTTPS URL.

---

## 🔒 Production Security Checklist

- [ ] **SSL/TLS**: All traffic is encrypted via HTTPS.
- [ ] **DB Access**: Database is in a private subnet; only the backend can access it.
- [ ] **Secrets**: No secrets are hardcoded; all are injected via environment variables.
- [ ] **Backups**: Automated daily backups for PostgreSQL are enabled.
- [ ] **Monitoring**: Sentry or Datadog integrated for error tracking.
- [ ] **Health Checks**: Load balancer is configured to check `/health` and `/ready`.
- [ ] **Rate Limiting**: Redis-backed rate limiting is active.
- [ ] **WAF**: Web Application Firewall (e.g., Cloudflare) is active to block common attacks.

---

## 📈 Scaling Strategy

### Vertical Scaling
- Increase CPU/RAM for the backend container if embedding generation (local) becomes a bottleneck.

### Horizontal Scaling
- **Backend**: Deploy multiple replicas of the backend container behind a Load Balancer.
- **Database**: Use a Read Replica for the `document_chunks` table if retrieval volume is high.
- **Cache**: Use Redis Cluster for high-availability caching.

---

## 🆘 Troubleshooting Production

**"Database connection timeout"**
$\rightarrow$ Check Security Groups/Firewall rules to ensure the backend can reach the DB port (5432).

**"502 Bad Gateway"**
$\rightarrow$ Check if the backend container crashed or is still downloading the embedding model (~420MB).

**"CORS Error"**
$\rightarrow$ Verify that `CORS_ORIGINS` in `.env` exactly matches the frontend URL (including `https://`).
