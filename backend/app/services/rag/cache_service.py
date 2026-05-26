"""
cache_service.py — Two-tier cache: Redis (L1) + PostgreSQL/pgvector (L2).

L1 (Redis): Exact match cache using hash of question + mode as key.
L2 (PostgreSQL): Semantic similarity cache using pgvector.

This reduces embedding API calls and database queries for repeated questions.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import redis

from app.core.config import settings
from app.core.database import get_conn
from app.services.rag.vector_store import get_embedding_function
from app.services.usage_tracker import estimate_tokens

logger = logging.getLogger(__name__)


class PostgresCacheService:
    """Two-tier Q&A cache: Redis (L1 exact match) + PostgreSQL (L2 semantic)."""

    def __init__(self) -> None:
        self._embeddings = get_embedding_function()
        self._redis_client: redis.Redis | None = None
        self._init_redis()

    def _init_redis(self) -> None:
        """Initialize Redis connection. Falls back gracefully if Redis is unavailable."""
        try:
            self._redis_client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            # Test connection
            self._redis_client.ping()
            logger.info("Redis cache initialized successfully")
        except Exception as e:
            logger.warning("Redis unavailable, falling back to PostgreSQL-only cache: %s", e)
            self._redis_client = None

    def ping(self) -> dict:
        if not self._redis_client:
            return {"available": False, "status": "disabled_or_unavailable"}
        try:
            self._redis_client.ping()
            return {"available": True, "status": "ok"}
        except Exception as exc:
            return {"available": False, "status": "error", "error": str(exc)}

    def _generate_cache_key(self, question: str, mode: str) -> str:
        """H-2 fix: Encode mode into cache key so clear_cache_by_mode can scan efficiently.

        Key format:  qa_cache:{mode}:{sha256(question)}
        This lets the Redis SCAN pattern be  qa_cache:{mode}:*  rather than
        scanning all qa_cache:* keys and loading JSON to filter by mode.
        """
        q_hash = hashlib.sha256(question.strip().lower().encode()).hexdigest()
        return f"qa_cache:{mode}:{q_hash}"

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_cached_answer(
        self, question: str, mode: str
    ) -> tuple[str, Any] | None:
        """
        Two-tier cache lookup:
        1. Check Redis (L1) for exact match
        2. Fall back to PostgreSQL (L2) for semantic similarity

        Returns (answer, sources) if found, else None.
        """
        # L1: Try Redis exact match first
        if self._redis_client:
            try:
                cache_key = self._generate_cache_key(question, mode)
                cached_data = self._redis_client.get(cache_key)
                if cached_data:
                    data = json.loads(cached_data)
                    logger.info("Redis L1 HIT mode=%s", mode)
                    return data["answer"], data["sources"]
            except Exception as e:
                logger.warning("Redis L1 lookup failed: %s", e)

        # L2: Fall back to PostgreSQL semantic search
        try:
            query_vec = self._embeddings.embed_query(question)
            vec_str = "[" + ",".join(str(v) for v in query_vec) + "]"

            sql = """
                SELECT id, answer, sources,
                       (embedding <=> %s::vector) AS distance
                FROM   qa_cache
                WHERE  mode = %s
                ORDER  BY distance
                LIMIT  1
            """
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(sql, (vec_str, mode))
                row = cur.fetchone()

            if row is None:
                logger.info("Cache MISS (L1+L2) mode=%s", mode)
                return None

            row_id, answer, sources_raw, distance = row

            if distance > settings.CACHE_SIMILARITY_THRESHOLD:
                logger.info(
                    "PostgreSQL L2 MISS mode=%s | distance: %.4f | threshold: %.2f",
                    mode, distance, settings.CACHE_SIMILARITY_THRESHOLD,
                )
                return None

            # Cache hit — update stats and populate Redis
            self._increment_hit(row_id)
            sources = sources_raw if isinstance(sources_raw, list) else json.loads(sources_raw or "[]")
            
            # Populate Redis L1 cache for future exact matches
            self._set_redis_cache(question, mode, answer, sources)
            
            logger.info(
                "PostgreSQL L2 HIT mode=%s | distance: %.4f",
                mode, distance,
            )
            return answer, sources

        except Exception:
            logger.exception("Error reading from cache (L2)")
            return None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def set_cached_answer(
        self, question: str, answer: str, sources: list, mode: str
    ) -> None:
        """
        Store Q&A pair in both Redis (L1) and PostgreSQL (L2).
        Redis provides fast exact-match lookups, PostgreSQL provides semantic search.
        """
        # Store in Redis L1 (with 24-hour TTL to prevent memory bloat)
        self._set_redis_cache(question, mode, answer, sources, ttl=86400)

        # Store in PostgreSQL L2 for semantic search
        try:
            query_vec = self._embeddings.embed_query(question)
            vec_str = "[" + ",".join(str(v) for v in query_vec) + "]"
            sources_json = json.dumps(sources, ensure_ascii=False)
            question_tokens = estimate_tokens(question)
            answer_tokens = estimate_tokens(answer)
            total_tokens = question_tokens + answer_tokens

            sql = """
                INSERT INTO qa_cache (
                    question, answer, sources, mode, embedding,
                    question_tokens, answer_tokens, total_tokens
                )
                VALUES (%s, %s, %s::jsonb, %s, %s::vector, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        question,
                        answer,
                        sources_json,
                        mode,
                        vec_str,
                        question_tokens,
                        answer_tokens,
                        total_tokens,
                    ),
                )

            logger.debug("Cached answer (L1+L2) mode=%s", mode)
        except Exception:
            logger.exception("Error writing to PostgreSQL cache (L2)")

    def _set_redis_cache(
        self, question: str, mode: str, answer: str, sources: list, ttl: int = 86400
    ) -> None:
        """Store answer in Redis with TTL (default 24 hours)."""
        if not self._redis_client:
            return

        try:
            cache_key = self._generate_cache_key(question, mode)
            cache_data = json.dumps(
                {"answer": answer, "sources": sources},
                ensure_ascii=False,
            )
            self._redis_client.setex(cache_key, ttl, cache_data)
        except Exception as e:
            logger.warning("Failed to write to Redis L1 cache: %s", e)

    # ------------------------------------------------------------------
    # Admin helpers
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Return cache statistics for the admin dashboard."""
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT COUNT(*), COALESCE(SUM(hit_count), 0) FROM qa_cache")
                total, total_hits = cur.fetchone()

                cur.execute(
                    """
                        SELECT question, mode, hit_count, created_at
                        FROM   qa_cache
                        ORDER  BY hit_count DESC
                        LIMIT  10
                        """
                )
                top_rows = cur.fetchall()

            top = [
                {
                    "question": f"sha256:{hashlib.sha256(str(r[0]).encode()).hexdigest()[:12]}",
                    "mode": r[1],
                    "hit_count": r[2],
                    "created_at": str(r[3]),
                }
                for r in top_rows
            ]
            # Calculate hit rate: hits / (hits + entries) as a rough estimate
            total_queries = total_hits + total
            hit_rate = (total_hits / total_queries) if total_queries > 0 else 0.0
            return {
                "total_entries": total, "total_hits": total_hits,
                "hit_rate": hit_rate, "top_questions": top,
            }
        except Exception:
            logger.exception("Error fetching qa_cache stats")
            return {"total_entries": 0, "total_hits": 0, "hit_rate": 0.0, "top_questions": []}

    def clear_cache(self) -> int:
        """Delete all rows from qa_cache (both Redis L1 and PostgreSQL L2)."""
        # Clear Redis L1
        if self._redis_client:
            try:
                # Delete all keys matching qa_cache:* pattern
                cursor = 0
                deleted = 0
                while True:
                    cursor, keys = self._redis_client.scan(cursor, match="qa_cache:*", count=100)
                    if keys:
                        deleted += self._redis_client.delete(*keys)
                    if cursor == 0:
                        break
                logger.info("Cleared %d Redis L1 cache entries", deleted)
            except Exception as e:
                logger.warning("Failed to clear Redis L1 cache: %s", e)

        # Clear PostgreSQL L2
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM qa_cache")
                count = cur.fetchone()[0]
                cur.execute("DELETE FROM qa_cache")
            logger.info("Cleared %d PostgreSQL L2 cache entries", count)
            return count
        except Exception:
            logger.exception("Error clearing PostgreSQL L2 cache")
            return 0

    def clear_cache_by_mode(self, mode: str) -> int:
        """H-2 fix: Delete Redis L1 entries only for the specified mode using mode-scoped key pattern."""
        if self._redis_client:
            try:
                cursor = 0
                deleted = 0
                while True:
                    # H-2 fix: pattern includes mode so only matching entries are deleted
                    cursor, keys = self._redis_client.scan(cursor, match=f"qa_cache:{mode}:*", count=100)
                    if keys:
                        deleted += self._redis_client.delete(*keys)
                    if cursor == 0:
                        break
                logger.info("Cleared %d Redis L1 cache entries for mode: %s", deleted, mode)
            except Exception as e:
                logger.warning("Failed to clear Redis L1 cache by mode: %s", e)

        # Clear PostgreSQL L2 for specific mode
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM qa_cache WHERE mode = %s", (mode,))
                count = cur.rowcount
            logger.info("Cleared %d PostgreSQL L2 cache entries for mode: %s", count, mode)
            return count
        except Exception:
            logger.exception("Error clearing PostgreSQL L2 cache for mode: %s", mode)
            return 0

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _increment_hit(self, row_id: int) -> None:
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE qa_cache SET hit_count = hit_count + 1, last_hit_at = NOW() WHERE id = %s",
                    (row_id,),
                )
        except Exception:
            logger.warning("Failed to increment hit_count for qa_cache id=%s", row_id)


# Singleton — imported by query_engine
cache_service = PostgresCacheService()
