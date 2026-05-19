from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import chat, document, usage, admin, auth, users
from app.core.config import get_cors_origins, settings
from app.core.database import init_db, seed_initial_admin
from app.middleware.error_handler import setup_exception_handlers
from app.middleware.security import setup_security_middleware
from app.middleware.logging import LoggingMiddleware

logger = logging.getLogger(__name__)

_is_prod = settings.ENVIRONMENT == "production"


@asynccontextmanager
async def lifespan(app: FastAPI):
    _run_startup_checks()
    yield
    # Cleanup on shutdown
    from app.core.database import close_pool
    close_pool()


app = FastAPI(
    title=f"{settings.PROJECT_NAME} API",
    description=(
        "Enterprise-grade RAG (Retrieval-Augmented Generation) Chatbot API. "
        "Features hybrid search (Vector + BM25), semantic caching, topic guarding, "
        "and comprehensive usage tracking. Supports both streaming and non-streaming responses."
    ),
    version="1.0.0",
    docs_url=None if _is_prod else "/docs",
    redoc_url=None if _is_prod else "/redoc",
    openapi_url=None if _is_prod else "/openapi.json",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Chat", "description": "Core chat endpoints for interacting with the AI"},
        {"name": "Document", "description": "Knowledge base management and PDF indexing"},
        {"name": "Usage", "description": "Token consumption and API usage statistics"},
        {"name": "Admin", "description": "System administration, topic guards, and cache management"},
        {"name": "Authentication", "description": "User authentication and JWT token management"},
        {"name": "Users", "description": "Per-user model settings and credential management"},
    ]
)

# CORS config for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
)

# Logging Middleware
app.add_middleware(LoggingMiddleware)

# Security Headers
setup_security_middleware(app)
setup_exception_handlers(app)

def _validate_startup_secrets() -> None:
    import base64
    errors = []
    jwt_key = settings.JWT_SECRET_KEY.strip()
    if not jwt_key:
        errors.append("JWT_SECRET_KEY is not set")
    elif jwt_key.startswith("replace-with") or len(jwt_key) < 32:
        errors.append("JWT_SECRET_KEY looks like a placeholder or is shorter than 32 chars")

    enc_key = settings.ENCRYPTION_KEY.strip()
    if not enc_key:
        errors.append("ENCRYPTION_KEY is not set")
    elif enc_key.startswith("replace-with"):
        errors.append("ENCRYPTION_KEY looks like a placeholder — generate a real 32-byte base64 key")
    else:
        try:
            decoded = base64.b64decode(enc_key)
            if len(decoded) != 32:
                errors.append(f"ENCRYPTION_KEY must decode to exactly 32 bytes, got {len(decoded)}")
        except Exception:
            errors.append("ENCRYPTION_KEY is not valid base64")

    if errors:
        raise RuntimeError("Startup secret validation failed:\n  - " + "\n  - ".join(errors))


def _run_startup_checks() -> None:
    """Validate runtime settings and run migrations before accepting traffic."""
    # Hard block: dev auth bypass is only safe in an explicit local-dev environment.
    _safe_envs = {"development", "local", "dev", "test"}
    if settings.ALLOW_DEV_AUTH_BYPASS and settings.ENVIRONMENT.lower() not in _safe_envs:
        raise RuntimeError(
            f"ALLOW_DEV_AUTH_BYPASS=true is not allowed in ENVIRONMENT={settings.ENVIRONMENT!r}. "
            "Set ALLOW_DEV_AUTH_BYPASS=false or ENVIRONMENT to one of: "
            + ", ".join(sorted(_safe_envs))
        )

    # Validate critical secrets — fail fast before accepting any traffic.
    _validate_startup_secrets()

    # Block dangerously long token lifetimes in production.
    from app.core.auth import ACCESS_TOKEN_EXPIRE_MINUTES
    _prod = settings.ENVIRONMENT.lower() not in {"development", "local", "dev", "test"}
    if _prod and ACCESS_TOKEN_EXPIRE_MINUTES > 120:
        raise RuntimeError(
            f"ACCESS_TOKEN_EXPIRE_MINUTES={ACCESS_TOKEN_EXPIRE_MINUTES} is too long for production "
            "(max allowed here: 120 min). Add a rotating refresh-token flow before using longer sessions."
        )

    if settings.DATABASE_URL:
        init_db()
        seed_initial_admin()

@app.get("/")
def health_check():
    return {"status": "ok", "message": "Enterprise AI Chatbot Backend is running."}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/ready")
def ready():
    """M-9 fix: Check DB connectivity before reporting ready."""
    try:
        from app.core.database import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return {"status": "ready"}
    except Exception as e:
        logger.error(f"Readiness probe failed: {e}")
        raise HTTPException(status_code=503, detail="Database not ready")

app.include_router(chat.router, prefix="/api/v1/chat", tags=["Chat"])
app.include_router(document.router, prefix="/api/v1/document", tags=["Document"])
app.include_router(usage.router, prefix="/api/v1/usage", tags=["Usage"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])

if __name__ == "__main__":
    import uvicorn
    _dev = settings.ENVIRONMENT.lower() in {"development", "local", "dev"}
    uvicorn.run("main:app", host=settings.APP_HOST, port=settings.APP_PORT, reload=_dev)
