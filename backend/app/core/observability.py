"""
observability.py — Lightweight tracing and performance monitoring.

Provides a Trace context manager to measure execution time of spans
and integrate them with the system logging and usage tracking.
"""

from __future__ import annotations

import time
import logging
from contextlib import contextmanager
from typing import Generator, Optional

logger = logging.getLogger(__name__)

class Trace:
    """
    A context manager for tracing the execution time of a block of code.
    
    Usage:
        with Trace("retrieval", request_id="abc-123"):
            # do work
    """
    def __init__(
        self, 
        span_name: str, 
        request_id: Optional[str] = None, 
        mode: Optional[str] = None
    ):
        self.span_name = span_name
        self.request_id = request_id
        self.mode = mode
        self.start_time: Optional[float] = None
        self.duration: Optional[float] = None

    def __enter__(self) -> Trace:
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.start_time is not None:
            self.duration = time.perf_counter() - self.start_time
            
            # Log the span duration
            log_msg = "Span [%s] completed in %.4fs" % (self.span_name, self.duration)
            if self.request_id:
                log_msg += f" | request_id={self.request_id}"
            if self.mode:
                log_msg += f" | mode={self.mode}"
                
            logger.info(log_msg)

    def get_duration(self) -> float:
        """Return the measured duration in seconds."""
        return self.duration or 0.0

@contextmanager
def trace_span(
    span_name: str, 
    request_id: Optional[str] = None, 
    mode: Optional[str] = None
) -> Generator[Trace, None, None]:
    """Convenience wrapper for the Trace context manager."""
    with Trace(span_name, request_id, mode) as trace:
        yield trace
