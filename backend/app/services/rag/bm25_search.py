"""
bm25_search.py — Persistent BM25 index with disk caching.

The BM25 index is cached in memory and persisted to disk to avoid
rebuilding on every query. The index is automatically invalidated
when the corpus changes (detected via checksum).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

# N-5 fix: Anchor cache dir to this file's location, not the process cwd
CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "bm25_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Module-level cache: avoids rebuilding BM25Okapi from disk JSON on every query.
# Keyed by "{mode}_{corpus_hash}" — evicted when corpus changes for that mode.
_mem_cache: dict[str, BM25Searcher] = {}


def tokenize(text: str) -> list[str]:
    """Simple tokenizer for BM25."""
    return re.findall(r'\w+', text.lower())


def _compute_corpus_hash(corpus: list[str]) -> str:
    """H-7 fix: Sort short per-doc hashes instead of full text — O(n log n) with small constants.

    Sorting the full corpus strings is O(n * L * log n) where L is avg doc length.
    Sorting 16-char hex digests is O(n * 16 * log n) ≈ O(n log n) with a tiny constant.
    """
    doc_hashes = sorted(hashlib.sha256(doc.encode()).hexdigest()[:16] for doc in corpus)
    return hashlib.sha256("\n".join(doc_hashes).encode()).hexdigest()[:16]


class BM25Searcher:
    """
    Persistent BM25 searcher with disk caching.
    
    The index is cached in memory and persisted to disk. When the corpus
    changes, the index is automatically rebuilt and saved.
    """
    
    def __init__(self, corpus: list[str], mode: str = "default"):
        """
        Initialize BM25 searcher with optional disk caching.
        
        Args:
            corpus: List of documents to index
            mode: Cache key (e.g., "Internal", "External") for separate indices
        """
        self.corpus = corpus
        self.mode = mode
        self.corpus_hash = _compute_corpus_hash(corpus)
        self.cache_path = CACHE_DIR / f"bm25_{mode}_{self.corpus_hash}.json"
        self.tokenized_corpus = [tokenize(doc) for doc in corpus]
        self.bm25: BM25Okapi | None = None

        if not self.tokenized_corpus:
            logger.info("Skipping BM25 index for mode=%s because corpus is empty", mode)
            return
        
        # Try to load from cache
        self.bm25 = self._load_from_cache()
        
        # If cache miss, build and save
        if self.bm25 is None:
            logger.info("Building BM25 index for mode=%s (corpus_size=%d)", mode, len(corpus))
            self.bm25 = BM25Okapi(self.tokenized_corpus)
            self._save_to_cache()

    def _load_from_cache(self) -> BM25Okapi | None:
        """Load BM25 index from disk cache."""
        if not self.cache_path.exists():
            return None

        try:
            with open(self.cache_path, encoding="utf-8") as f:
                data = json.load(f)

            if data.get("corpus_hash") != self.corpus_hash or data.get("mode") != self.mode:
                logger.warning("BM25 cache mismatch, rebuilding index")
                return None

            tokenized_corpus = data.get("tokenized_corpus")
            if not isinstance(tokenized_corpus, list):
                logger.warning("BM25 cache missing tokenized corpus, rebuilding index")
                return None

            self.tokenized_corpus = [list(tokens) for tokens in tokenized_corpus]
            logger.info("Loaded BM25 token cache: %s", self.cache_path.name)
            return BM25Okapi(self.tokenized_corpus)
        except Exception as e:
            logger.warning("Failed to load BM25 cache: %s", e)
            return None

    def _save_to_cache(self) -> None:
        """H-6 fix: Prune old cache files for this mode before writing the new one."""
        try:
            # H-6 fix: Delete stale cache files for same mode to prevent unbounded growth
            for old_file in CACHE_DIR.glob(f"bm25_{self.mode}_*.json"):
                if old_file != self.cache_path:
                    try:
                        old_file.unlink()
                        logger.info("Pruned stale BM25 cache: %s", old_file.name)
                    except Exception as e:
                        logger.warning("Failed to prune BM25 cache %s: %s", old_file.name, e)

            data = {
                "corpus_hash": self.corpus_hash,
                "mode": self.mode,
                "tokenized_corpus": self.tokenized_corpus,
            }
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            logger.info("Saved BM25 token cache: %s", self.cache_path.name)
        except Exception as e:
            logger.warning("Failed to save BM25 cache: %s", e)

    def search(self, query: str, k: int = 5) -> list[tuple[int, float]]:
        """
        Search the corpus for the top k most relevant documents.
        Returns a list of (index, score) tuples.
        """
        if not self.corpus or self.bm25 is None:
            return []
            
        tokenized_query = tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)
        
        # Get indices of top k scores
        top_n = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True
        )[:k]
        
        return [(i, scores[i]) for i in top_n if scores[i] > 0]

    @staticmethod
    def clear_cache(mode: str | None = None) -> int:
        """
        Clear BM25 cache files.
        
        Args:
            mode: If specified, only clear cache for this mode. Otherwise clear all.
        
        Returns:
            Number of cache files deleted.
        """
        deleted = 0
        pattern = f"bm25_{mode}_*.json" if mode else "bm25_*.json"
        
        for cache_file in CACHE_DIR.glob(pattern):
            try:
                cache_file.unlink()
                deleted += 1
                logger.info("Deleted BM25 cache: %s", cache_file.name)
            except Exception as e:
                logger.warning("Failed to delete cache %s: %s", cache_file.name, e)
        
        return deleted

    @staticmethod
    def cache_status() -> dict:
        files = list(CACHE_DIR.glob("bm25_*.json"))
        return {
            "available": True,
            "cache_dir": str(CACHE_DIR),
            "files": len(files),
            "size_bytes": sum(path.stat().st_size for path in files if path.exists()),
        }


def get_or_build_searcher(corpus: list[str], mode: str) -> BM25Searcher:
    """Return a cached BM25Searcher, rebuilding only when corpus changes.

    Avoids reconstructing BM25Okapi from disk JSON on every query call.
    Old entries for the same mode are evicted when the corpus hash changes.
    """
    corpus_hash = _compute_corpus_hash(corpus)
    cache_key = f"{mode}_{corpus_hash}"

    if cache_key in _mem_cache:
        return _mem_cache[cache_key]

    # Evict stale entries for this mode before inserting the new one
    for stale in [k for k in _mem_cache if k.startswith(f"{mode}_") and k != cache_key]:
        del _mem_cache[stale]

    searcher = BM25Searcher(corpus, mode=mode)
    _mem_cache[cache_key] = searcher
    return searcher
