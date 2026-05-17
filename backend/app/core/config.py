from pathlib import Path
import os

from dotenv import dotenv_values
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
ENV_FILES = (PROJECT_ROOT / ".env", BACKEND_DIR / ".env")

_ORIGINAL_ENV_KEYS = set(os.environ)
for env_file in ENV_FILES:
    for key, value in dotenv_values(env_file).items():
        if value is not None and key not in _ORIGINAL_ENV_KEYS:
            os.environ[key] = value


class Settings(BaseSettings):
    PROJECT_NAME: str = "Enterprise AI Chatbot"
    ENVIRONMENT: str = "development"  # development, staging, production
    GEMINI_API_KEY: str = ""
    CHAT_MODEL: str = "gemini-2.0-flash"
    # Vendor-independent local embeddings (768 dims, no API key required)
    EMBEDDING_MODEL: str = "sentence-transformers/all-mpnet-base-v2"
    DOCUMENT_STORAGE_DIR: str = "./storage/documents"
    # R7-3 fix: Removed stale Streamlit origins (8501). Credentials belong in REDIS_URL, not REDIS_PASSWORD.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"
    RETRIEVAL_TOP_K: int = 5
    RETRIEVAL_CANDIDATES_K: int = 10
    FINAL_CONTEXT_K: int = 3
    MAX_CONTEXT_CHARS: int = 8000
    TOKEN_USAGE_DB: str = "./token_usage.db"
    CACHE_SIMILARITY_THRESHOLD: float = 0.10  # pgvector cosine distance (lower = more similar)
    MIN_RERANK_SCORE: float = 0.05
    MAX_HISTORY_MESSAGES: int = 10
    MAX_HISTORY_TOKENS: int = 1500
    RATE_LIMIT_SECONDS: int = 2
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    LOCAL_COST_BUDGET: float = 50.0  # Local budget for cost tracking alerts
    JWT_SECRET_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALLOW_DEV_AUTH_BYPASS: bool = False
    TOPIC_GUARD_FAIL_CLOSED: bool = True
    ENCRYPTION_KEY: str = ""  # 32-byte base64 key for encrypting user credentials

    # Web Search API Keys (optional)
    GOOGLE_SEARCH_API_KEY: str = ""
    GOOGLE_SEARCH_CX: str = ""
    BING_SEARCH_API_KEY: str = ""
    CUSTOM_ENDPOINT_ALLOWLIST: str = ""  # Comma-separated hostnames allowed for custom LLM endpoints.

    # Railway PostgreSQL — auto-injected by Railway, or set manually in .env
    DATABASE_URL: str = ""
    # R7-1 fix: REDIS_PASSWORD was silently ignored — all four Redis clients use REDIS_URL only.
    # Embed credentials directly in REDIS_URL: redis://:password@host:6379/0
    REDIS_URL: str = "redis://localhost:6379/0"
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000
    ENABLE_HSTS: bool = False

    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        extra="ignore",
    )

settings = Settings()

def get_cors_origins() -> list[str]:
    return [
        origin.strip()
        for origin in settings.CORS_ORIGINS.split(",")
        if origin.strip()
    ]
