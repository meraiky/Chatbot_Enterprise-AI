from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import settings

# Swagger UI (/docs, /redoc, /openapi.json) requires unsafe-inline/eval to render.
# In production, disable Swagger entirely and use the strict policy.
# In development, the relaxed policy applies only to Swagger routes.
_SWAGGER_PATHS = {"/docs", "/redoc", "/openapi.json"}

_CSP_STRICT = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data: https:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)

# Only used in development for Swagger UI routes.
_CSP_SWAGGER_DEV = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "font-src 'self' data:; "
    "connect-src 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        is_dev = settings.ENVIRONMENT != "production"
        is_swagger = request.url.path in _SWAGGER_PATHS

        csp = _CSP_SWAGGER_DEV if (is_dev and is_swagger) else _CSP_STRICT
        response.headers["Content-Security-Policy"] = csp

        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        is_https = request.url.scheme == "https" or forwarded_proto == "https" or settings.ENABLE_HSTS
        if is_https:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        return response


def setup_security_middleware(app: FastAPI):
    app.add_middleware(SecurityHeadersMiddleware)
