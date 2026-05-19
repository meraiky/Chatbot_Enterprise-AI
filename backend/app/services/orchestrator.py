"""
orchestrator.py — Orca-style parallel orchestration for RAG operations.

Provides parallel execution utilities for:
- Multi-source retrieval (vector + BM25 + external search)
- Batch document processing
- Concurrent API calls with context isolation

Inspired by Orca's ThreadPoolExecutor-based parallel execution pattern.
"""

from __future__ import annotations

import copy
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def execute_parallel(
    tasks: List[Callable[[], T]],
    max_workers: int | None = None,
    context: Dict[str, Any] | None = None,
) -> List[T]:
    """
    Execute multiple tasks in parallel using ThreadPoolExecutor.
    
    Args:
        tasks: List of callable functions to execute in parallel
        max_workers: Maximum number of worker threads (default: len(tasks))
        context: Optional shared context dict (deep-copied per task for isolation)
        
    Returns:
        List of results in the same order as input tasks
        
    Example:
        >>> def fetch_vector(): return vector_search(query)
        >>> def fetch_bm25(): return bm25_search(query)
        >>> results = execute_parallel([fetch_vector, fetch_bm25])
        >>> vector_results, bm25_results = results
    """
    if not tasks:
        return []
    
    if max_workers is None:
        max_workers = len(tasks)
    
    # Deep copy context for each task to prevent race conditions
    contexts = [copy.deepcopy(context) if context else {} for _ in tasks]
    
    results: List[T | None] = [None] * len(tasks)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks with their index
        future_to_index = {
            executor.submit(task): idx
            for idx, task in enumerate(tasks)
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                logger.error("Task %d failed: %s", idx, e, exc_info=True)
                results[idx] = None
    
    return results  # type: ignore[return-value]


def execute_parallel_with_context(
    tasks: List[Callable[[Dict[str, Any]], T]],
    context: Dict[str, Any],
    max_workers: int | None = None,
) -> tuple[List[T], Dict[str, Any]]:
    """
    Execute tasks in parallel with isolated context per task, then merge results.
    
    Args:
        tasks: List of functions that accept and modify a context dict
        context: Shared context dict (deep-copied per task)
        max_workers: Maximum number of worker threads
        
    Returns:
        Tuple of (results, merged_context)
        
    Example:
        >>> def read_file(ctx):
        ...     ctx['content'] = read(ctx['path'])
        ...     return ctx['content']
        >>> tasks = [lambda ctx: read_file({**ctx, 'path': p}) for p in paths]
        >>> results, ctx = execute_parallel_with_context(tasks, {})
    """
    if not tasks:
        return [], context
    
    if max_workers is None:
        max_workers = len(tasks)
    
    # Deep copy context for each task
    contexts = [copy.deepcopy(context) for _ in tasks]
    
    results: List[T | None] = [None] * len(tasks)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(task, ctx): idx
            for idx, (task, ctx) in enumerate(zip(tasks, contexts))
        }
        
        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                logger.error("Task %d failed: %s", idx, e, exc_info=True)
                results[idx] = None
    
    # Merge context results (aggregate pattern)
    merged_context = copy.deepcopy(context)
    
    # Collect list-type results (e.g., file_contents from parallel reads)
    for idx, ctx in enumerate(contexts):
        if results[idx] is not None:
            # Merge any list fields
            for key, value in ctx.items():
                if isinstance(value, list) and key not in merged_context:
                    merged_context[key] = []
                if isinstance(value, list):
                    merged_context[key].extend(value)
    
    return results, merged_context  # type: ignore[return-value]


def parallel_retrieval(
    vector_search_fn: Callable[[], Any],
    bm25_search_fn: Callable[[], Any],
    external_search_fn: Callable[[], Any] | None = None,
) -> Dict[str, Any]:
    """
    Execute multiple retrieval strategies in parallel.
    
    Args:
        vector_search_fn: Function that performs vector search
        bm25_search_fn: Function that performs BM25 search
        external_search_fn: Optional function for external/web search
        
    Returns:
        Dict with keys: vector_results, bm25_results, external_results (if provided)
        
    Example:
        >>> results = parallel_retrieval(
        ...     lambda: vector_store.similarity_search(query, k=10),
        ...     lambda: bm25_searcher.search(query, k=10),
        ... )
        >>> vector_docs = results['vector_results']
        >>> bm25_docs = results['bm25_results']
    """
    tasks = [vector_search_fn, bm25_search_fn]
    keys = ["vector_results", "bm25_results"]
    
    if external_search_fn:
        tasks.append(external_search_fn)
        keys.append("external_results")
    
    logger.debug("Starting parallel retrieval with %d strategies", len(tasks))
    results = execute_parallel(tasks)
    
    return dict(zip(keys, results))


def batch_process(
    items: List[Any],
    process_fn: Callable[[Any], T],
    batch_size: int = 10,
    max_workers: int | None = None,
) -> List[T]:
    """
    Process items in parallel batches.
    
    Args:
        items: List of items to process
        process_fn: Function to apply to each item
        batch_size: Number of items to process in parallel
        max_workers: Maximum number of worker threads per batch
        
    Returns:
        List of processed results in original order
        
    Example:
        >>> documents = batch_process(
        ...     file_paths,
        ...     lambda path: extract_text(path),
        ...     batch_size=5
        ... )
    """
    if not items:
        return []
    
    all_results: List[T] = []
    
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        # Create proper closures to avoid late binding issue
        def make_task(item):
            return lambda: process_fn(item)
        tasks = [make_task(item) for item in batch]
        batch_results = execute_parallel(tasks, max_workers=max_workers)
        all_results.extend(batch_results)
        logger.debug("Processed batch %d/%d", i // batch_size + 1, (len(items) + batch_size - 1) // batch_size)
    
    return all_results
