# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| 1.x (latest) | Yes |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Send a private report to the maintainers:
1. Use GitHub's [private security advisory](https://github.com/YOUR_USERNAME/Chatbot_Enterprise-AI/security/advisories/new) feature, or
2. Email the maintainer directly with subject line: `[SECURITY] Chatbot_Enterprise-AI — <brief description>`

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- (Optional) Suggested fix

You will receive a response within **48 hours**. We aim to release a patch within **7 days** for critical issues.

---

## Security Design

### API Key Management
- LLM provider API keys are stored **AES-encrypted** in PostgreSQL; the encryption key is injected at runtime via `ENCRYPTION_KEY` env var
- Keys are never logged, never returned in API responses, and never stored in `.env`

### Authentication
- JWT access tokens are signed with `JWT_SECRET_KEY` (HS256), default expiry **1 hour** (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`); production startup rejects values above 120 minutes
- Browser sessions use a separate httpOnly refresh-token cookie with rotation on `/api/v1/auth/refresh`; logout revokes both access and refresh tokens when the database is available
- Passwords hashed with bcrypt (cost factor 12, enforced in code); input silently truncated to 72 bytes (bcrypt limit) — avoid passwords longer than 72 bytes
- Login rate limiting: max 5 attempts per 5 minutes per IP address
- Token expiry enforced on all protected routes
- Exception details are redacted before being written to logs or returned in debug error responses
- `ALLOW_DEV_AUTH_BYPASS` bypasses authentication entirely — the backend refuses to start if this is `true` in `staging` or `production` environments

### LLM Security
- **Topic guard** blocks prompt injection and off-topic queries via pgvector similarity before any LLM call
- **Injection scanner** detects common prompt injection patterns in user input
- **PII redactor** strips email addresses, phone numbers, and other PII before logging

### Network
- Custom OpenAI-compatible endpoints must use HTTPS, cannot target local/private network hosts, and require `CUSTOM_ENDPOINT_ALLOWLIST` in production
- CORS restricted to `CORS_ORIGINS` — set explicitly in production
- Rate limiting enforced on chat endpoints (Redis-backed, falls back to in-process); configurable via `RATE_LIMIT_SECONDS`
- CSP enforced on all API responses; `unsafe-inline`/`unsafe-eval` only applied to Swagger UI paths in non-production environments
- Security headers on all responses: `Strict-Transport-Security`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `X-XSS-Protection`, `Permissions-Policy`

### Docker / Infrastructure
- PostgreSQL password set via `POSTGRES_PASSWORD` env var — never hardcoded; change the default `postgres` before any network exposure
- Backend connects to the database using the same `POSTGRES_PASSWORD` — credentials are consistent across services in Docker Compose

### Data
- Documents are stored with Internal/External visibility controls
- Upload restricted to PDF files with extractable text only (max 50MB, MIME type validated)
- BM25 cache files contain no user data and are excluded from version control

---

## Responsible Disclosure

We follow [responsible disclosure](https://en.wikipedia.org/wiki/Coordinated_vulnerability_disclosure). We ask that you:
- Give us reasonable time to patch before public disclosure
- Not exploit the vulnerability beyond confirming it exists
- Not access or modify user data during testing
