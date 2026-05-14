import uuid
import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

from app.core.redaction import redact_sensitive

class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to inject a unique request ID into the log context
    and log request/response details.
    """
    async def dispatch(self, request: Request, call_next):
        # Generate a unique request ID
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        
        # Bind request ID to the structlog context
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            client=request.client.host if request.client else "unknown"
        )
        
        start_time = time.time()
        
        # Log the incoming request
        logger = structlog.get_logger()
        logger.info("request_started")
        
        try:
            response = await call_next(request)
            
            # Calculate duration
            duration = time.time() - start_time
            
            # Log the response
            logger.info(
                "request_finished",
                status_code=response.status_code,
                duration=f"{duration:.4f}s"
            )
            
            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id
            return response
            
        except Exception as e:
            duration = time.time() - start_time
            logger.exception(
                "request_failed",
                duration=f"{duration:.4f}s",
                error=redact_sensitive(e)
            )
            raise e
