import ipaddress
import logging
import time
from datetime import timedelta

import redis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    TokenData,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    get_current_admin,
    get_current_user,
    oauth2_scheme,
    revoke_access_token,
    verify_password,
)
from app.core.config import settings
from app.core.database import get_conn

logger = logging.getLogger(__name__)
router = APIRouter()

LOGIN_RATE_LIMIT_WINDOW = 300  # 5 minutes
LOGIN_MAX_ATTEMPTS = 5

# In-memory fallback (single-process only; Redis is preferred)
_login_attempts: dict[str, list[float]] = {}
_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis | None:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        client = redis.from_url(settings.REDIS_URL, decode_responses=True,
                                socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        _redis_client = client
    except Exception:
        logger.warning("Redis unavailable for login rate limiting; using in-process fallback")
    return _redis_client


def _is_trusted_proxy(ip: str) -> bool:
    """Check if IP matches any entry in TRUSTED_PROXY_CIDRS (exact IP or CIDR range).

    Configurable via TRUSTED_PROXY_CIDRS env var (comma-separated IPs/CIDRs).
    Default covers loopback and the Docker bridge network (172.16.0.0/12).
    """
    entries = [e.strip() for e in settings.TRUSTED_PROXY_CIDRS.split(",") if e.strip()]
    try:
        addr = ipaddress.ip_address(ip)
        for entry in entries:
            try:
                if "/" in entry:
                    if addr in ipaddress.ip_network(entry, strict=False):
                        return True
                elif ip == entry:
                    return True
            except ValueError:
                continue
    except ValueError:
        pass
    return False


def _real_ip(request: Request) -> str:
    """Return the true client IP, honouring X-Real-IP only from trusted proxies.

    Security: only requests from TRUSTED_PROXY_CIDRS can set X-Real-IP/X-Forwarded-For.
    Prevents rate-limit bypass via header injection attacks.
    See: https://adam-p.ca/blog/2022/03/x-forwarded-for/
    """
    client_ip = request.client.host if request.client else "unknown"

    if _is_trusted_proxy(client_ip):
        # Try X-Real-IP first (set by nginx)
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        
        # Fallback to X-Forwarded-For (may contain chain of proxies)
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            # Take first IP (original client)
            return forwarded.split(",")[0].strip()
    
    return client_ip


def _check_login_rate_limit(ip: str) -> None:
    key = f"login_attempts:{ip}"
    client = _get_redis()

    if client is not None:
        try:
            count: int = client.incr(key)  # type: ignore[assignment]  # redis-py incr() returns int at runtime
            if count == 1:
                client.expire(key, LOGIN_RATE_LIMIT_WINDOW)
            if count > LOGIN_MAX_ATTEMPTS:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many login attempts. Please try again in {LOGIN_RATE_LIMIT_WINDOW // 60} minutes.",
                )
            return
        except HTTPException:
            raise
        except Exception:
            logger.warning("Redis login rate-limit check failed; falling back to in-process")

    now = time.time()
    # H-4 fix: Prune expired timestamps for this IP and delete empty buckets
    recent = [t for t in _login_attempts.get(ip, []) if now - t < LOGIN_RATE_LIMIT_WINDOW]
    if len(recent) >= LOGIN_MAX_ATTEMPTS:
        # Keep stale entry so repeated blocked requests don't reset the window
        _login_attempts[ip] = recent
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many login attempts. Please try again in {LOGIN_RATE_LIMIT_WINDOW // 60} minutes.",
        )
    recent.append(now)
    _login_attempts[ip] = recent
    # H-4 fix: Periodically prune IPs that have no recent attempts (prevent unbounded growth)
    if len(_login_attempts) > 10_000:
        cutoff = now - LOGIN_RATE_LIMIT_WINDOW
        stale_ips = [k for k, v in _login_attempts.items() if not v or max(v) < cutoff]
        for stale in stale_ips:
            del _login_attempts[stale]


def _is_dev_environment() -> bool:
    return settings.ENVIRONMENT.lower() in {"development", "local", "dev", "test"}


def _token_payload(
    username: str,
    role: str,
    user_id: int,
    can_manage_models: bool,
) -> dict:
    return {"sub": username, "role": role, "uid": user_id, "can_m": can_manage_models}


def _set_auth_cookies(response: JSONResponse, access_token: str, refresh_token: str) -> None:
    secure = not _is_dev_environment()
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/api",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/api/v1/auth",
    )

class UserResponse(BaseModel):
    """Response model for user creation/retrieval."""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 1,
                "username": "admin",
                "role": "admin",
                "can_manage_models": True
            }
        }
    )

    id: int
    username: str
    role: str
    can_manage_models: bool


@router.post("/login")
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    """Authenticate user and return JWT token with rate limiting."""
    _check_login_rate_limit(_real_ip(request))
    
    # 1. Fetch user from DB
    sql = "SELECT id, username, hashed_password, role, is_active, can_manage_models FROM users WHERE username = %s"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (form_data.username,))
        user = cur.fetchone()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id, username, hashed_password, role, is_active, can_manage_models = user

    if not is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )

    # 2. Verify password
    if not verify_password(form_data.password, hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Create JWT
    payload = _token_payload(username, role, user_id, can_manage_models)
    access_token = create_access_token(
        data=payload,
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    refresh_token = create_refresh_token(payload)

    # 4. Set httpOnly cookie (browser clients) + return token in body (API/Swagger clients)
    response = JSONResponse(content={"access_token": access_token, "token_type": "bearer"})
    _set_auth_cookies(response, access_token, refresh_token)
    return response


@router.post("/refresh")
async def refresh_session(request: Request):
    """Rotate the refresh token and issue a new short-lived access token."""
    refresh_token = request.cookies.get("refresh_token")
    token_data = decode_refresh_token(refresh_token) if refresh_token else None
    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not refresh session",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create new tokens FIRST to avoid losing session if token creation fails
    payload = _token_payload(
        username=token_data.username or "",
        role=token_data.role or "",
        user_id=token_data.user_id or 0,
        can_manage_models=bool(token_data.can_manage_models),
    )
    access_token = create_access_token(payload)
    new_refresh_token = create_refresh_token(payload)
    
    # Then revoke old refresh token (best-effort, don't fail if revocation fails)
    if refresh_token:
        try:
            revoke_access_token(refresh_token)
        except Exception:
            logger.warning("Failed to revoke old refresh token during rotation")
    
    response = JSONResponse(content={"access_token": access_token, "token_type": "bearer"})
    _set_auth_cookies(response, access_token, new_refresh_token)
    return response


@router.post("/logout")
async def logout(request: Request, bearer: str | None = Depends(oauth2_scheme)):
    """Revoke current access/refresh tokens and clear auth cookies."""
    access_token = bearer or request.cookies.get("access_token")
    refresh_token = request.cookies.get("refresh_token")
    revoked_access = revoke_access_token(access_token) if access_token else False
    revoked_refresh = revoke_access_token(refresh_token) if refresh_token else False
    secure = not _is_dev_environment()
    response = JSONResponse(content={"revoked": revoked_access or revoked_refresh})
    response.delete_cookie("access_token", path="/api", httponly=True, samesite="lax", secure=secure)
    response.delete_cookie("refresh_token", path="/api/v1/auth", httponly=True, samesite="lax", secure=secure)
    return response


@router.get("/me")
async def get_me(current_user: TokenData = Depends(get_current_user)):
    """Return the current authenticated user's public profile."""
    return {
        "username": current_user.username,
        "role": current_user.role,
        "can_manage_models": current_user.can_manage_models,
    }

class UserCreate(BaseModel):
    """Request model for creating a new admin user."""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"username": "admin_user", "password": "securepassword123"}
        }
    )

    username: str = Field(..., min_length=3, max_length=50, pattern=r"^\w+$", description="Alphanumeric username")
    password: str = Field(..., min_length=8, max_length=72, description="Password must be at least 8 characters long")

    @field_validator('password')
    @classmethod
    def password_byte_limit(cls, v: str) -> str:
        """R4-1 fix: Enforce 72-byte limit at API layer to return HTTP 422 instead of 500."""
        if len(v.encode('utf-8')) > 72:
            raise ValueError("Password must be at most 72 bytes when encoded as UTF-8")
        return v

@router.post(
    "/create-admin",
    status_code=201,
    response_model=UserResponse,
    dependencies=[Depends(get_current_admin)],
)
async def create_admin_user(body: UserCreate):
    """
    Bootstrap endpoint to create the first admin user.
    
    Protected admin-only user creation endpoint.
    """
    from app.core.auth import get_password_hash

    hashed_pw = get_password_hash(body.password)
    sql = "INSERT INTO users (username, hashed_password, role, can_manage_models) VALUES (%s, %s, %s, true) RETURNING id"
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(sql, (body.username, hashed_pw, "admin"))
            result = cur.fetchone()
            if not result:
                raise HTTPException(status_code=400, detail="Failed to create user")
            user_id = result[0]
        return {"id": user_id, "username": body.username, "role": "admin", "can_manage_models": True}
    except Exception as e:
        try:
            import psycopg2  # type: ignore[import-untyped]
            if isinstance(e, psycopg2.errors.UniqueViolation):
                raise HTTPException(status_code=400, detail="Username already exists") from e
        except ImportError:
            pass
        logger.exception("Failed to create admin user: username=%s", body.username)
        raise HTTPException(status_code=400, detail="Could not create user") from e
