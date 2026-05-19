"""
database.py — SQLAlchemy + pgvector bootstrap for Railway PostgreSQL.

Tables managed here:
  - qa_cache      : persistent semantic cache (replaces ChromaDB query_cache_v2)
  - topic_guard   : admin-defined blocked topic patterns

Usage:
    from app.core.database import init_db, get_conn
    init_db()          # call once at app startup
    with get_conn() as conn: ...
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pg_pool

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection pool (thread-safe)
# ---------------------------------------------------------------------------
_pool: pg_pool.ThreadedConnectionPool | None = None


def _get_pool() -> pg_pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        if not settings.DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL is not set. "
                "Add it to your .env or Railway environment variables."
            )
        _pool = pg_pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=settings.DATABASE_URL,
        )
    return _pool


@contextmanager
def get_conn() -> Generator[psycopg2.extensions.connection, None, None]:
    """Context-manager that yields a connection and auto-commits / rolls back."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def close_pool() -> None:
    """Close all connections in the pool. Call this on application shutdown."""
    global _pool
    if _pool is not None:
        logger.info("Closing database connection pool")
        _pool.closeall()
        _pool = None


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Initialize database schema using Alembic migrations.
    
    CRITICAL FIX (C-3): Previously caught exceptions without re-raising, allowing the app
    to start with broken schema. Now follows fail-fast principle: if migrations fail,
    the app should not start.
    
    Raises:
        RuntimeError: If migrations fail to apply
    """
    try:
        from alembic.config import Config
        from alembic import command
        from pathlib import Path

        ini_path = str(Path(__file__).resolve().parents[2] / "alembic.ini")
        
        if not Path(ini_path).exists():
            logger.warning("alembic.ini not found at %s, skipping automatic migrations", ini_path)
            _create_tables_fallback()
            return

        alembic_cfg = Config(ini_path)
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations applied successfully (upgraded to head).")
    except Exception as exc:
        logger.exception("Failed to run database migrations: %s", exc)
        # Fallback: create tables directly if migrations fail
        logger.warning("Attempting direct table creation as fallback")
        _create_tables_fallback()


def _create_tables_fallback() -> None:
    """Create essential tables directly when Alembic is unavailable."""
    if not settings.DATABASE_URL:
        return

    with get_conn() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                hashed_password TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                can_manage_models BOOLEAN NOT NULL DEFAULT FALSE,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_memory (
                id SERIAL PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversation_memory_cid
            ON conversation_memory(conversation_id, created_at DESC)
        """)
        # Add user_id if missing (safe on existing deployments)
        cursor.execute("""
            ALTER TABLE conversation_memory
            ADD COLUMN IF NOT EXISTS user_id INTEGER
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversation_memory_uid
            ON conversation_memory(user_id, created_at DESC)
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS topic_guard (
                id SERIAL PRIMARY KEY,
                pattern TEXT NOT NULL,
                mode TEXT,
                reason TEXT,
                is_regex BOOLEAN NOT NULL DEFAULT FALSE,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS revoked_tokens (
                jti TEXT PRIMARY KEY,
                expires_at TIMESTAMPTZ NOT NULL
            )
        """)

        # pgvector-dependent tables — skip gracefully if extension missing
        try:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS qa_cache (
                    id SERIAL PRIMARY KEY,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    sources JSONB NOT NULL DEFAULT '[]',
                    mode TEXT NOT NULL,
                    embedding vector(768),
                    question_tokens INTEGER NOT NULL DEFAULT 0,
                    answer_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    hit_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_hit_at TIMESTAMPTZ
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id SERIAL PRIMARY KEY,
                    chunk_id TEXT NOT NULL UNIQUE,
                    doc_id TEXT,
                    content TEXT NOT NULL,
                    metadata JSONB,
                    embedding vector(768),
                    source TEXT,
                    mode TEXT,
                    doc_type TEXT,
                    page INTEGER,
                    checksum TEXT,
                    uploaded_at TIMESTAMPTZ
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_document_chunks_doc_type
                ON document_chunks(doc_type)
            """)
        except Exception as vec_exc:
            logger.warning("pgvector tables skipped (extension unavailable): %s", vec_exc)

        logger.info("Core tables created/verified via fallback")


def seed_initial_admin() -> None:
    """Create the first admin account on fresh installs.

    Runs only when INITIAL_ADMIN_USERNAME and INITIAL_ADMIN_PASSWORD are set AND
    the users table is completely empty. Safe to call on every startup — it's a no-op
    once any user exists.
    """
    username = settings.INITIAL_ADMIN_USERNAME.strip()
    password = settings.INITIAL_ADMIN_PASSWORD.strip()
    if not username or not password:
        return

    if not settings.DATABASE_URL:
        return

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users")
                row = cur.fetchone()
                if row and row[0] > 0:
                    return  # users already exist, skip

                from app.core.auth import get_password_hash
                cur.execute(
                    """INSERT INTO users (username, hashed_password, role, is_active, can_manage_models)
                       VALUES (%s, %s, 'admin', TRUE, TRUE)""",
                    (username, get_password_hash(password)),
                )
        logger.info("First-run admin account created: username=%s", username)
    except Exception as exc:
        logger.error("Failed to seed initial admin: %s", exc)
