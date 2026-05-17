"""Web Search Service with multi-provider support and caching"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import httpx

from app.core.database import get_conn
from app.services.llm_service import get_llm
from app.services.rag.injection_scanner import scan_chunk

logger = logging.getLogger(__name__)

# Search result structure
SearchResult = Dict[str, str]  # {"url": str, "title": str, "snippet": str}


class WebSearchProvider(ABC):
    """Abstract base class for web search providers"""

    @abstractmethod
    async def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """Search and return results"""
        pass

    @abstractmethod
    def name(self) -> str:
        """Provider name"""
        pass


class DuckDuckGoProvider(WebSearchProvider):
    """DuckDuckGo search (free, no API key required) using duckduckgo-search library"""

    def name(self) -> str:
        return "duckduckgo"

    async def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """
        Search using duckduckgo-search library (more reliable than Instant Answer API).
        Falls back to Instant Answer API if library unavailable.
        """
        # Try duckduckgo-search library first (much more reliable)
        try:
            from ddgs import DDGS
            import asyncio

            def _ddg_search():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=num_results))

            # W-4 fix: use get_running_loop() (safe in async context, no deprecation warning)
            loop = asyncio.get_running_loop()
            raw_results = await loop.run_in_executor(None, _ddg_search)

            results = []
            for item in raw_results:
                results.append({
                    "url": item.get("href", ""),
                    "title": item.get("title", ""),
                    "snippet": item.get("body", "")[:400],
                })
            if results:
                logger.info(f"DuckDuckGo (library) returned {len(results)} results for: {query[:60]}")
                return results[:num_results]
        except ImportError:
            logger.warning("duckduckgo-search library not installed, falling back to Instant Answer API")
        except Exception as e:
            logger.warning(f"DuckDuckGo library search failed ({e}), falling back to Instant Answer API")

        # Fallback: Instant Answer API (limited but no extra dependency)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                params = {
                    "q": query,
                    "format": "json",
                    "no_redirect": 1,
                    "no_html": 1,
                    "skip_disambig": 1,
                }
                response = await client.get(
                    "https://api.duckduckgo.com/",
                    params=params,
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                response.raise_for_status()
                data = response.json()

                results = []

                # Add instant answer if available
                if data.get("AbstractText"):
                    results.append({
                        "url": data.get("AbstractURL", ""),
                        "title": data.get("Heading", query),
                        "snippet": data.get("AbstractText", "")[:300]
                    })

                # Add related topics
                for topic in data.get("RelatedTopics", [])[:num_results - 1]:
                    if "FirstURL" in topic:
                        results.append({
                            "url": topic["FirstURL"],
                            "title": topic.get("Text", "").split(" - ")[0],
                            "snippet": topic.get("Text", "")[:300]
                        })

                return results[:num_results]

        except Exception as e:
            logger.error(f"DuckDuckGo search failed: {e}")
            return []


class GoogleSearchProvider(WebSearchProvider):
    """Google Custom Search API (requires API key and CX)"""

    def __init__(self, api_key: str, cx: str):
        self.api_key = api_key
        self.cx = cx

    def name(self) -> str:
        return "google"

    async def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """Search using Google Custom Search API"""
        if not self.api_key or not self.cx:
            logger.warning("Google Search API key or CX not configured")
            return []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                params = {
                    "key": self.api_key,
                    "cx": self.cx,
                    "q": query,
                    "num": num_results,
                }
                response = await client.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params=params
                )
                response.raise_for_status()
                data = response.json()

                results = []
                for item in data.get("items", [])[:num_results]:
                    results.append({
                        "url": item.get("link", ""),
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", "")[:300]
                    })

                return results

        except Exception as e:
            logger.error(f"Google search failed: {e}")
            return []


class BingSearchProvider(WebSearchProvider):
    """Bing Search API (requires subscription key)"""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def name(self) -> str:
        return "bing"

    async def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """Search using Bing Search API"""
        if not self.api_key:
            logger.warning("Bing Search API key not configured")
            return []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {"Ocp-Apim-Subscription-Key": self.api_key}
                params = {
                    "q": query,
                    "count": num_results,
                    "mkt": "en-US",
                }
                response = await client.get(
                    "https://api.bing.microsoft.com/v7.0/search",
                    params=params,
                    headers=headers
                )
                response.raise_for_status()
                data = response.json()

                results = []
                for item in data.get("webPages", {}).get("value", [])[:num_results]:
                    results.append({
                        "url": item.get("url", ""),
                        "title": item.get("name", ""),
                        "snippet": item.get("snippet", "")[:300]
                    })

                return results

        except Exception as e:
            logger.error(f"Bing search failed: {e}")
            return []


class WebSearchService:
    """Web search service with caching and multi-provider support"""

    def __init__(self, providers: List[WebSearchProvider]):
        self.providers = providers
        self.default_ttl_days = 7

    async def search_with_cache(
        self,
        query: str,
        user_id: Optional[int] = None,
        ttl_days: Optional[int] = None,
        force_refresh: bool = False
    ) -> Dict:
        """
        Search web with caching
        
        Returns:
        {
            "cached": bool,
            "results": [...],
            "answer": str,
            "sources": [...]
        }
        """
        if ttl_days is None:
            ttl_days = self.default_ttl_days

        # W-2 fix: scan web search query for prompt injection before LLM synthesis
        scan_result = scan_chunk(query)
        if not scan_result["clean"]:
            logger.warning(f"Web search query blocked by injection scanner: {query[:80]}")
            return {
                "cached": False,
                "results": [],
                "answer": "Your query was blocked because it contains patterns that resemble prompt injection.",
                "sources": [],
            }

        # W-1 fix: include user_id in cache key so per-user LLM configs don't cross-pollinate
        cache_seed = f"{query}:user={user_id or 'anon'}"
        query_hash = hashlib.sha256(cache_seed.encode()).hexdigest()

        # Check cache first (unless force_refresh)
        if not force_refresh:
            cached_result = self._get_cached_result(query_hash)
            if cached_result:
                logger.info(f"Web search cache hit for query: {query[:50]}")
                return {
                    "cached": True,
                    "results": cached_result["search_results"],
                    "answer": cached_result["answer"],
                    "sources": cached_result["sources"]
                }

        # Not cached → perform search
        logger.info(f"Web search cache miss for query: {query[:50]}")
        results = await self._search_multi_provider(query)

        if not results:
            logger.warning(f"No search results found for query: {query[:50]}")
            return {
                "cached": False,
                "results": [],
                "answer": "Không tìm thấy kết quả trên Internet.",
                "sources": []
            }

        # Synthesize answer using LLM
        answer, sources = await self._synthesize_answer(query, results, user_id)

        # Cache results
        self._cache_result(query_hash, query, results, answer, sources, ttl_days)

        return {
            "cached": False,
            "results": results,
            "answer": answer,
            "sources": sources
        }

    async def _search_multi_provider(self, query: str) -> List[SearchResult]:
        """Try multiple providers with fallback"""
        for provider in self.providers:
            try:
                logger.info(f"Searching with {provider.name()}: {query[:50]}")
                results = await provider.search(query)
                if results:
                    logger.info(f"Got {len(results)} results from {provider.name()}")
                    return results
            except Exception as e:
                logger.warning(f"Provider {provider.name()} failed: {e}")
                continue

        logger.error(f"All search providers failed for query: {query[:50]}")
        return []

    async def _synthesize_answer(
        self,
        query: str,
        results: List[SearchResult],
        user_id: Optional[int] = None
    ) -> Tuple[str, List[Dict]]:
        """
        Use LLM to synthesize answer from search results
        Returns: (answer_text, sources_used)
        """
        # Build context from search results
        context_parts = []
        for i, result in enumerate(results[:5], 1):
            context_parts.append(
                f"[{i}] {result['title']}\n"
                f"URL: {result['url']}\n"
                f"{result['snippet']}"
            )

        context = "\n\n".join(context_parts)

        prompt = f"""Based on the following web search results, answer the question concisely.
Cite sources using [1], [2], etc. format.
Keep answer under 300 words.

Question: {query}

Search Results:
{context}

Answer:"""

        try:
            # Call LLM
            llm = get_llm(streaming=False, user_id=user_id)
            response = llm.invoke(prompt)

            # Extract plain text from response — handle both string and list[block] formats
            raw_content = response.content
            if isinstance(raw_content, str):
                answer = raw_content
            elif isinstance(raw_content, list):
                # Anthropic/Gemini style: list of {"type": "text", "text": "..."}
                parts = []
                for block in raw_content:
                    if isinstance(block, dict):
                        parts.append(block.get("text") or block.get("content") or "")
                    elif isinstance(block, str):
                        parts.append(block)
                answer = "".join(parts).strip()
            else:
                answer = str(raw_content)

            # Extract which sources were cited by [1], [2], etc.
            sources_used = []
            for i in range(1, len(results[:5]) + 1):
                if f"[{i}]" in answer:
                    sources_used.append({
                        "url": results[i - 1]["url"],
                        "title": results[i - 1]["title"],
                        "snippet": results[i - 1]["snippet"]
                    })

            # If LLM didn't use citation markers, return all results as sources
            if not sources_used:
                sources_used = [
                    {"url": r["url"], "title": r["title"], "snippet": r["snippet"]}
                    for r in results[:5]
                ]

            return answer, sources_used

        except Exception as e:
            logger.error(f"Failed to synthesize answer: {e}")
            # Fallback: return concatenated snippets
            fallback_answer = "\n\n".join([
                f"[{i}] {r['title']}: {r['snippet']}"
                for i, r in enumerate(results[:3], 1)
            ])
            fallback_sources = [
                {"url": r["url"], "title": r["title"], "snippet": r["snippet"]}
                for r in results[:3]
            ]
            return fallback_answer, fallback_sources

    def _get_cached_result(self, query_hash: str) -> Optional[Dict]:
        """Get cached search result from database"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT search_results, answer, sources, created_at
                        FROM external_search_cache
                        WHERE query_hash = %s 
                          AND expires_at > NOW()
                    """, (query_hash,))
                    row = cur.fetchone()

                    if row:
                        # Update hit count and last accessed
                        cur.execute("""
                            UPDATE external_search_cache
                            SET hit_count = hit_count + 1,
                                last_accessed = NOW()
                            WHERE query_hash = %s
                        """, (query_hash,))

                        return {
                            "search_results": row[0],
                            "answer": row[1],
                            "sources": row[2]
                        }

                    return None

        except Exception as e:
            logger.error(f"Failed to get cached result: {e}")
            return None

    def _cache_result(
        self,
        query_hash: str,
        query: str,
        results: List[SearchResult],
        answer: str,
        sources: List[Dict],
        ttl_days: int
    ) -> None:
        """Cache search result in database"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO external_search_cache 
                        (query_hash, search_query, search_results, answer, sources, expires_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (query_hash) DO UPDATE
                        SET search_results = EXCLUDED.search_results,
                            answer = EXCLUDED.answer,
                            sources = EXCLUDED.sources,
                            expires_at = EXCLUDED.expires_at,
                            hit_count = external_search_cache.hit_count + 1,
                            last_accessed = NOW()
                    """, (
                        query_hash,
                        query,
                        json.dumps(results),
                        answer,
                        json.dumps(sources),
                        datetime.now(timezone.utc) + timedelta(days=ttl_days)
                    ))

        except Exception as e:
            logger.error(f"Failed to cache result: {e}")

    def cleanup_expired_cache(self) -> int:
        """Delete expired cache entries. Returns count of deleted rows."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        DELETE FROM external_search_cache
                        WHERE expires_at < NOW()
                    """)
                    deleted = cur.rowcount
                    logger.info(f"Cleaned up {deleted} expired cache entries")
                    return deleted

        except Exception as e:
            logger.error(f"Failed to cleanup cache: {e}")
            return 0


# Factory function to create service with configured providers
def create_web_search_service() -> WebSearchService:
    """Create WebSearchService with configured providers.
    
    Provider priority:
    1. Google Custom Search (if API key + CX configured) - most reliable
    2. Bing Search (if API key configured) - fallback
    3. DuckDuckGo (always available) - free fallback
    """
    from app.core.config import settings

    providers: List[WebSearchProvider] = []

    # Add Google if configured (highest priority - most reliable)
    if hasattr(settings, "GOOGLE_SEARCH_API_KEY") and settings.GOOGLE_SEARCH_API_KEY:
        google_cx = getattr(settings, "GOOGLE_SEARCH_CX", "")
        if google_cx:  # Both API key and CX required
            providers.append(GoogleSearchProvider(
                api_key=settings.GOOGLE_SEARCH_API_KEY,
                cx=google_cx
            ))
            logger.info("Web search: Google Custom Search enabled (primary provider)")
        else:
            logger.warning("Web search: GOOGLE_SEARCH_API_KEY set but GOOGLE_SEARCH_CX missing - Google provider disabled")

    # Add Bing if configured (secondary fallback)
    if hasattr(settings, "BING_SEARCH_API_KEY") and settings.BING_SEARCH_API_KEY:
        providers.append(BingSearchProvider(
            api_key=settings.BING_SEARCH_API_KEY
        ))
        logger.info("Web search: Bing Search enabled (secondary provider)")

    # Always add DuckDuckGo (free, no config needed - final fallback)
    providers.append(DuckDuckGoProvider())
    logger.info("Web search: DuckDuckGo enabled (fallback provider)")

    if not providers:
        logger.warning("Web search: No providers configured - search will fail")

    return WebSearchService(providers)
