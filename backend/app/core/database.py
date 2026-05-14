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


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    Initialize database schema using Alembic migrations.
    This replaces the old raw SQL DDL approach.
    """
    try:
        from alembic.config import Config
        from alembic import command
        import os

        # Path to alembic.ini relative to this file or absolute
        # Assuming we are running from the backend root
        ini_path = os.path.join(os.getcwd(), "alembic.ini")
        
        if not os.path.exists(ini_path):
            logger.warning("alembic.ini not found at %s, skipping automatic migrations", ini_path)
            return

        alembic_cfg = Config(ini_path)
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations applied successfully (upgraded to head).")
    except Exception as exc:
        logger.exception("Failed to run database migrations: %s", exc)
