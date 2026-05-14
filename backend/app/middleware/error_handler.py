from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.core.exceptions import ChatbotException
import logging

logger = logging.getLogger(__name__)

async def chatbot_exception_handler(request: Request, exc: ChatbotException):
    """Handler for all custom ChatbotExceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": exc.__class__.__name__,
            "message": exc.message,
            "detail": exc.detail,
        },
    )

async def generic_exception_handler(request: Request, exc: Exception):
    """Handler for all unhandled exceptions."""
    logger.exception("Unhandled exception occurred: %s", str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "InternalServerError",
            "message": "An unexpected error occurred on the server.",
            "detail": str(exc) if logger.isEnabledFor(logging.DEBUG) else None,
        },
    )

def setup_exception_handlers(app: FastAPI):
    """Register all exception handlers to the FastAPI app."""
    app.add_exception_handler(ChatbotException, chatbot_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
