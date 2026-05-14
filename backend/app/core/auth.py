from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import get_conn

ALGORITHM = "HS256"
# Default: 1h. Override with ACCESS_TOKEN_EXPIRE_MINUTES in .env.
# Keep this short in production until a rotating refresh-token flow is added.
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
    settings.ACCESS_TOKEN_EXPIRE_MINUTES
)
REFRESH_TOKEN_EXPIRE_DAYS: int = int(settings.REFRESH_TOKEN_EXPIRE_DAYS)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None
    user_id: Optional[int] = None
    jti: Optional[str] = None
    can_manage_models: Optional[bool] = None
    token_type: Optional[str] = None

# ---------------------------------------------------------------------------
# Logic
# ---------------------------------------------------------------------------

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password using bcrypt."""
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)

def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt with cost factor 12. Automatically truncates to 72 bytes."""
    # Bcrypt has a 72-byte limit, truncate password if needed
    password_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt(rounds=12)  # Cost factor 12 as per SECURITY.md
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')

def _get_jwt_secret() -> str:
    secret = settings.JWT_SECRET_KEY.strip()
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY is not configured")
    return secret


def _create_token(data: dict, token_type: str, expires_delta: timedelta):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire, "jti": str(uuid4()), "typ": token_type})
    encoded_jwt = jwt.encode(to_encode, _get_jwt_secret(), algorithm=ALGORITHM)
    return encoded_jwt


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    return _create_token(
        data=data,
        token_type="access",
        expires_delta=expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None):
    return _create_token(
        data=data,
        token_type="refresh",
        expires_delta=expires_delta or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )


def _is_token_revoked(jti: str | None) -> bool:
    if not jti or not settings.DATABASE_URL:
        return False
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM revoked_tokens WHERE jti = %s LIMIT 1",
                    (jti,),
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def revoke_access_token(token: str) -> bool:
    if not settings.DATABASE_URL:
        return False
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=[ALGORITHM])
    except JWTError:
        return False

    jti = payload.get("jti")
    expires_at = datetime.fromtimestamp(payload.get("exp"), tz=timezone.utc)
    if not jti:
        return False

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO revoked_tokens (jti, expires_at)
                VALUES (%s, %s)
                ON CONFLICT (jti) DO NOTHING
                """,
                (jti, expires_at),
            )
    return True


def decode_token(token: str, expected_type: str = "access") -> Optional[TokenData]:
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=[ALGORITHM])
        token_type: str = payload.get("typ", "access")
        if token_type != expected_type:
            return None
        username: str = payload.get("sub")
        role: str = payload.get("role")
        user_id: int = payload.get("uid")
        jti: str = payload.get("jti")
        can_manage_models: bool = payload.get("can_m", False)
        if username is None:
            return None
        if _is_token_revoked(jti):
            return None
        return TokenData(
            username=username,
            role=role,
            user_id=user_id,
            jti=jti,
            can_manage_models=can_manage_models,
            token_type=token_type,
        )
    except JWTError:
        return None


def decode_access_token(token: str) -> Optional[TokenData]:
    return decode_token(token, expected_type="access")


def decode_refresh_token(token: str) -> Optional[TokenData]:
    return decode_token(token, expected_type="refresh")

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login", auto_error=False)

_DEV_ENVIRONMENTS = {"development", "local", "dev", "test"}

def _allow_dev_user() -> bool:
    # Allowlist approach: bypass only in explicitly safe environments.
    # Any unknown/missing ENVIRONMENT value is treated as production-like (deny).
    return (
        settings.ALLOW_DEV_AUTH_BYPASS
        and settings.ENVIRONMENT.lower() in _DEV_ENVIRONMENTS
    )


async def get_current_user(
    bearer: Optional[str] = Depends(oauth2_scheme),
    cookie_token: Optional[str] = Cookie(None, alias="access_token"),
) -> TokenData:
    """Accept token from Authorization: Bearer header (API/Swagger) or httpOnly cookie (browser)."""
    token = bearer if isinstance(bearer, str) else None
    if token is None and isinstance(cookie_token, str):
        token = cookie_token

    if not token and _allow_dev_user():
        return TokenData(username="dev-admin", role="admin", can_manage_models=True)

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception

    token_data = decode_access_token(token)
    if token_data is None:
        raise credentials_exception
    return token_data

async def get_current_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Dependency to ensure the current user is an admin."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user does not have enough privileges"
        )
    return current_user
