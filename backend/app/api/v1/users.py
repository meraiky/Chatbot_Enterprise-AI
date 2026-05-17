from __future__ import annotations

import json
import logging
import ipaddress
from typing import Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.auth import TokenData, get_current_user
from app.core.config import settings
from app.core.database import get_conn
from app.core.redaction import redact_sensitive

logger = logging.getLogger(__name__)
from app.services.credential_service import decrypt_credential, encrypt_credential

router = APIRouter()

Provider = Literal["gemini", "anthropic", "openai", "custom"]
RoutingStrategy = Literal["random", "round_robin", "fallback"]


def _custom_endpoint_allowlist() -> set[str]:
    return {
        hostname.strip().lower()
        for hostname in settings.CUSTOM_ENDPOINT_ALLOWLIST.split(",")
        if hostname.strip()
    }


def _is_private_or_local_host(hostname: str) -> bool:
    normalized = hostname.strip().lower()
    if normalized in {"localhost"} or normalized.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(normalized)
        return (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        )
    except ValueError:
        return False


def _validate_custom_endpoint(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    value = value.strip()
    if not value:
        return None

    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("custom_endpoint must include a hostname")

    # H-5 fix: Block dangerous ports (Redis, PostgreSQL, internal services)
    port = parsed.port
    BLOCKED_PORTS = {6379, 5432, 11211, 27017, 3306, 9200, 5672, 6380, 6381}
    if port in BLOCKED_PORTS:
        raise ValueError(f"custom_endpoint cannot use port {port} (internal service port)")

    is_dev = settings.ENVIRONMENT.lower() in {"development", "local", "dev", "test"}
    if _is_private_or_local_host(hostname):
        # H-5 fix: Dev mode still requires HTTPS, just allows localhost hostname
        if not is_dev:
            raise ValueError("custom_endpoint cannot target local or private network hosts")
        if hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("custom_endpoint cannot target local or private network hosts")

    if parsed.scheme != "https":
        raise ValueError("custom_endpoint must use HTTPS")

    allowlist = _custom_endpoint_allowlist()
    if allowlist and hostname not in allowlist:
        raise ValueError("custom_endpoint host is not allowlisted")
    if not allowlist and not is_dev:
        raise ValueError("CUSTOM_ENDPOINT_ALLOWLIST is required for custom endpoints in production")
    return value


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ModelConfigCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    provider: Provider
    model_name: Optional[str] = Field(default=None, max_length=255)
    custom_endpoint: Optional[str] = Field(default=None, max_length=500)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    system_prompt: Optional[str] = Field(default=None, max_length=4000)
    is_active: bool = True
    priority: int = 0

    @field_validator("custom_endpoint")
    @classmethod
    def validate_custom_endpoint(cls, value: Optional[str]) -> Optional[str]:
        return _validate_custom_endpoint(value)
    
    @model_validator(mode='after')
    def validate_custom_provider_has_endpoint(self) -> 'ModelConfigCreate':
        """Ensure custom provider has a custom_endpoint configured."""
        if self.provider == "custom" and not self.custom_endpoint:
            raise ValueError("custom_endpoint is required when provider is 'custom'")
        return self


class ModelConfigUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    model_name: Optional[str] = Field(default=None, max_length=255)
    custom_endpoint: Optional[str] = Field(default=None, max_length=500)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    system_prompt: Optional[str] = Field(default=None, max_length=4000)
    is_active: Optional[bool] = None
    priority: Optional[int] = None

    @field_validator("custom_endpoint")
    @classmethod
    def validate_custom_endpoint(cls, value: Optional[str]) -> Optional[str]:
        return _validate_custom_endpoint(value)


class ModelCredentialUpdate(BaseModel):
    api_key: str = Field(..., min_length=8, max_length=4096)


class ModelConfigResponse(BaseModel):
    id: int
    name: str
    provider: Provider
    model_name: Optional[str] = None
    custom_endpoint: Optional[str] = None
    temperature: float = 0.2
    system_prompt: Optional[str] = None
    is_active: bool = True
    priority: int = 0
    has_api_key: bool = False


class RoutingConfigUpdate(BaseModel):
    strategy: RoutingStrategy = "random"
    enabled_model_ids: list[int] = Field(default_factory=list)
    fallback_order: list[int] = Field(default_factory=list)


class RoutingConfigResponse(BaseModel):
    strategy: RoutingStrategy = "random"
    enabled_model_ids: list[int] = Field(default_factory=list)
    fallback_order: list[int] = Field(default_factory=list)


class UserModelsResponse(BaseModel):
    models: list[ModelConfigResponse] = Field(default_factory=list)
    routing: RoutingConfigResponse


class ModelConnectionTestResponse(BaseModel):
    ok: bool
    model_id: int
    provider: Provider
    model_name: Optional[str] = None
    endpoint: Optional[str] = None
    detail: str


class LegacyUserSettingsResponse(BaseModel):
    preferred_model: Literal["gemini", "anthropic", "openai", "custom"] = "gemini"
    model_name: Optional[str] = None
    temperature: float = 0.2
    system_prompt: Optional[str] = None
    credentials: dict[str, bool] = Field(default_factory=dict)


class LegacyUserSettingsUpdate(BaseModel):
    preferred_model: Literal["gemini", "anthropic"] = "gemini"
    model_name: Optional[str] = Field(default=None, max_length=200)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    system_prompt: Optional[str] = Field(default=None, max_length=4000)


class LegacyCredentialStatusResponse(BaseModel):
    provider: Literal["gemini", "anthropic"]
    configured: bool


class WebSearchPreferencesResponse(BaseModel):
    allow_web_search: bool = False
    auto_web_search: bool = False
    web_search_providers: list[str] = ["duckduckgo"]


class WebSearchPreferencesUpdate(BaseModel):
    allow_web_search: Optional[bool] = None
    auto_web_search: Optional[bool] = None
    web_search_providers: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_user_id(current_user: TokenData) -> int:
    if current_user.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated token is missing user id",
        )
    return current_user.user_id


def _require_model_permission(current_user: TokenData) -> int:
    """H-1 fix: Re-validate model-management permission from DB, not JWT only.

    JWT claims can become stale after an admin revokes `can_manage_models`; checking
    the current database value prevents privilege retention until token expiry.
    """
    user_id = _require_user_id(current_user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT can_manage_models FROM users WHERE id = %s AND is_active = TRUE",
                (user_id,),
            )
            row = cur.fetchone()
    if not row or not bool(row[0]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account does not have permission to manage model configurations.",
        )
    return user_id


def _load_routing(user_id: int) -> RoutingConfigResponse:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT routing_strategy, enabled_model_ids, fallback_order
                   FROM user_routing_config
                   WHERE user_id = %s""",
                (user_id,),
            )
            row = cur.fetchone()

    if not row:
        return RoutingConfigResponse()

    strategy, enabled_model_ids, fallback_order = row
    return RoutingConfigResponse(
        strategy=strategy or "random",
        enabled_model_ids=json.loads(enabled_model_ids) if enabled_model_ids else [],
        fallback_order=json.loads(fallback_order) if fallback_order else [],
    )


def _load_models(user_id: int) -> list[ModelConfigResponse]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, provider, model_name, custom_endpoint,
                          temperature, system_prompt, is_active, priority,
                          api_key_encrypted
                   FROM user_model_configs
                   WHERE user_id = %s
                   ORDER BY priority DESC, id""",
                (user_id,),
            )
            rows = cur.fetchall()

    models: list[ModelConfigResponse] = []
    for row in rows:
        models.append(
            ModelConfigResponse(
                id=row[0],
                name=row[1],
                provider=row[2],
                model_name=row[3],
                custom_endpoint=row[4],
                temperature=float(row[5]) if row[5] is not None else 0.2,
                system_prompt=row[6],
                is_active=bool(row[7]),
                priority=int(row[8] or 0),
                has_api_key=bool(row[9]),
            )
        )
    return models


# ---------------------------------------------------------------------------
# New multi-model API
# ---------------------------------------------------------------------------


@router.get("/me/models", response_model=UserModelsResponse)
async def get_my_models(current_user: TokenData = Depends(get_current_user)):
    user_id = _require_user_id(current_user)
    return UserModelsResponse(models=_load_models(user_id), routing=_load_routing(user_id))


@router.post("/me/models", response_model=ModelConfigResponse, status_code=201)
async def create_my_model(
    body: ModelConfigCreate,
    current_user: TokenData = Depends(get_current_user),
):
    user_id = _require_model_permission(current_user)

    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """INSERT INTO user_model_configs (
                            user_id, name, provider, model_name, custom_endpoint,
                            temperature, system_prompt, is_active, priority, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        RETURNING id, name, provider, model_name, custom_endpoint,
                                  temperature, system_prompt, is_active, priority,
                                  api_key_encrypted""",
                    (
                        user_id,
                        body.name.strip(),
                        body.provider,
                        body.model_name.strip() if body.model_name else None,
                        body.custom_endpoint,
                        body.temperature,
                        body.system_prompt,
                        body.is_active,
                        body.priority,
                    ),
                )
                row = cur.fetchone()
            except Exception as exc:
                try:
                    import psycopg2  # type: ignore[import-untyped]
                    if isinstance(exc, psycopg2.errors.UniqueViolation):
                        raise HTTPException(status_code=400, detail="A model config with that name already exists.") from exc
                except ImportError:
                    pass
                logger.exception("Failed to create model config")
                raise HTTPException(status_code=400, detail="Could not create model configuration.") from exc

    if row is None:
        raise HTTPException(status_code=500, detail="Model configuration was not created.")

    return ModelConfigResponse(
        id=row[0],
        name=row[1],
        provider=row[2],
        model_name=row[3],
        custom_endpoint=row[4],
        temperature=float(row[5]) if row[5] is not None else 0.2,
        system_prompt=row[6],
        is_active=bool(row[7]),
        priority=int(row[8] or 0),
        has_api_key=bool(row[9]),
    )


@router.put("/me/models/{model_id}", response_model=ModelConfigResponse)
async def update_my_model(
    model_id: int,
    body: ModelConfigUpdate,
    current_user: TokenData = Depends(get_current_user),
):
    user_id = _require_model_permission(current_user)

    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No fields provided for update")

    allowed = {
        "name",
        "model_name",
        "custom_endpoint",
        "temperature",
        "system_prompt",
        "is_active",
        "priority",
    }
    fields = [k for k in patch.keys() if k in allowed]
    set_clause = ", ".join(f"{f} = %s" for f in fields) + ", updated_at = NOW()"
    values = [patch[f] for f in fields]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""UPDATE user_model_configs
                    SET {set_clause}
                    WHERE id = %s AND user_id = %s
                    RETURNING id, name, provider, model_name, custom_endpoint,
                              temperature, system_prompt, is_active, priority,
                              api_key_encrypted""",
                (*values, model_id, user_id),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Model config not found")

    return ModelConfigResponse(
        id=row[0],
        name=row[1],
        provider=row[2],
        model_name=row[3],
        custom_endpoint=row[4],
        temperature=float(row[5]) if row[5] is not None else 0.2,
        system_prompt=row[6],
        is_active=bool(row[7]),
        priority=int(row[8] or 0),
        has_api_key=bool(row[9]),
    )


@router.delete("/me/models/{model_id}", status_code=204)
async def delete_my_model(
    model_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    user_id = _require_model_permission(current_user)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_model_configs WHERE id = %s AND user_id = %s",
                (model_id, user_id),
            )
            deleted = cur.rowcount

    if deleted == 0:
        raise HTTPException(status_code=404, detail="Model config not found")


@router.put("/me/models/{model_id}/api-key", response_model=ModelConfigResponse)
async def set_model_api_key(
    model_id: int,
    body: ModelCredentialUpdate,
    current_user: TokenData = Depends(get_current_user),
):
    user_id = _require_model_permission(current_user)
    encrypted_api_key = encrypt_credential(body.api_key.strip())

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE user_model_configs
                   SET api_key_encrypted = %s, updated_at = NOW()
                   WHERE id = %s AND user_id = %s
                   RETURNING id, name, provider, model_name, custom_endpoint,
                             temperature, system_prompt, is_active, priority,
                             api_key_encrypted""",
                (encrypted_api_key, model_id, user_id),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Model config not found")

    return ModelConfigResponse(
        id=row[0],
        name=row[1],
        provider=row[2],
        model_name=row[3],
        custom_endpoint=row[4],
        temperature=float(row[5]) if row[5] is not None else 0.2,
        system_prompt=row[6],
        is_active=bool(row[7]),
        priority=int(row[8] or 0),
        has_api_key=bool(row[9]),
    )


@router.delete("/me/models/{model_id}/api-key", response_model=ModelConfigResponse)
async def delete_model_api_key(
    model_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    user_id = _require_model_permission(current_user)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE user_model_configs
                   SET api_key_encrypted = NULL, updated_at = NOW()
                   WHERE id = %s AND user_id = %s
                   RETURNING id, name, provider, model_name, custom_endpoint,
                             temperature, system_prompt, is_active, priority,
                             api_key_encrypted""",
                (model_id, user_id),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Model config not found")

    return ModelConfigResponse(
        id=row[0],
        name=row[1],
        provider=row[2],
        model_name=row[3],
        custom_endpoint=row[4],
        temperature=float(row[5]) if row[5] is not None else 0.2,
        system_prompt=row[6],
        is_active=bool(row[7]),
        priority=int(row[8] or 0),
        has_api_key=bool(row[9]),
    )


@router.post("/me/models/{model_id}/test", response_model=ModelConnectionTestResponse)
async def test_my_model_connection(
    model_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    user_id = _require_model_permission(current_user)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, provider, model_name, custom_endpoint, temperature, api_key_encrypted
                   FROM user_model_configs
                   WHERE id = %s AND user_id = %s""",
                (model_id, user_id),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Model config not found")

    provider = row[1]
    model_name = row[2]
    custom_endpoint = row[3]
    temperature = float(row[4]) if row[4] is not None else 0.2
    api_key_encrypted = row[5]

    api_key = None
    if api_key_encrypted:
        try:
            api_key = decrypt_credential(api_key_encrypted)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Failed to decrypt API key.") from exc

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        key = api_key
        if not key:
            raise HTTPException(status_code=400, detail="Missing API key for this model")

        llm = ChatGoogleGenerativeAI(
            model=model_name or "gemini-2.0-flash-exp",
            google_api_key=key,
            temperature=temperature,
        )
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        key = api_key
        if not key:
            raise HTTPException(status_code=400, detail="Missing API key for this model")

        llm = ChatAnthropic(
            model_name=model_name or "claude-sonnet-4-20250514",
            api_key=key,
            temperature=temperature,
        )
    elif provider in {"openai", "custom"}:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise HTTPException(status_code=500, detail="langchain-openai is not installed") from exc

        key = api_key or "dummy"

        llm = ChatOpenAI(
            model=model_name or "gpt-4o-mini",
            openai_api_key=key,
            base_url=custom_endpoint or None,
            temperature=temperature,
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    try:
        response = llm.invoke("Reply exactly with: pong")
        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            content = " ".join(str(part) for part in content)

        return ModelConnectionTestResponse(
            ok=True,
            model_id=model_id,
            provider=provider,
            model_name=model_name,
            endpoint=custom_endpoint,
            detail=f"Connection successful. Sample response: {str(content)[:120]}",
        )
    except Exception as exc:
        return ModelConnectionTestResponse(
            ok=False,
            model_id=model_id,
            provider=provider,
            model_name=model_name,
            endpoint=custom_endpoint,
            detail=f"Connection failed: {redact_sensitive(exc)}",
        )


@router.put("/me/routing", response_model=RoutingConfigResponse)
async def update_my_routing(
    body: RoutingConfigUpdate,
    current_user: TokenData = Depends(get_current_user),
):
    user_id = _require_user_id(current_user)

    enabled_model_ids = json.dumps(body.enabled_model_ids)
    fallback_order = json.dumps(body.fallback_order)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO user_routing_config (
                        user_id, routing_strategy, enabled_model_ids, fallback_order, updated_at
                    )
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (user_id) DO UPDATE SET
                        routing_strategy = EXCLUDED.routing_strategy,
                        enabled_model_ids = EXCLUDED.enabled_model_ids,
                        fallback_order = EXCLUDED.fallback_order,
                        updated_at = NOW()
                    RETURNING routing_strategy, enabled_model_ids, fallback_order""",
                (user_id, body.strategy, enabled_model_ids, fallback_order),
            )
            row = cur.fetchone()

    if row is None:
        raise HTTPException(status_code=500, detail="Routing configuration was not saved.")

    return RoutingConfigResponse(
        strategy=row[0] or "random",
        enabled_model_ids=json.loads(row[1]) if row[1] else [],
        fallback_order=json.loads(row[2]) if row[2] else [],
    )


# ---------------------------------------------------------------------------
# Legacy compatibility API
# ---------------------------------------------------------------------------


@router.get("/me/settings", response_model=LegacyUserSettingsResponse)
async def get_my_settings(current_user: TokenData = Depends(get_current_user)):
    """Compatibility endpoint for old settings page.

    Derives single-model style response from multi-model configs.
    """
    user_id = _require_user_id(current_user)
    models = _load_models(user_id)

    # prefer top active gemini/anthropic config
    preferred = next((m for m in models if m.is_active and m.provider in {"gemini", "anthropic"}), None)
    if not preferred:
        return LegacyUserSettingsResponse(credentials={})

    credentials = {
        m.provider: m.has_api_key
        for m in models
        if m.provider in {"gemini", "anthropic"}
    }

    return LegacyUserSettingsResponse(
        preferred_model=preferred.provider,
        model_name=preferred.model_name,
        temperature=preferred.temperature,
        system_prompt=preferred.system_prompt,
        credentials=credentials,
    )


@router.put("/me/settings", response_model=LegacyUserSettingsResponse)
async def update_my_settings(
    body: LegacyUserSettingsUpdate,
    current_user: TokenData = Depends(get_current_user),
):
    """Compatibility endpoint that upserts a primary provider model config."""
    user_id = _require_user_id(current_user)

    primary_name = f"Primary {body.preferred_model.title()}"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id FROM user_model_configs
                   WHERE user_id = %s AND name = %s""",
                (user_id, primary_name),
            )
            existing = cur.fetchone()

            if existing:
                cur.execute(
                    """UPDATE user_model_configs
                       SET provider = %s,
                           model_name = %s,
                           temperature = %s,
                           system_prompt = %s,
                           is_active = true,
                           updated_at = NOW()
                       WHERE id = %s""",
                    (
                        body.preferred_model,
                        body.model_name,
                        body.temperature,
                        body.system_prompt,
                        existing[0],
                    ),
                )
            else:
                cur.execute(
                    """INSERT INTO user_model_configs (
                            user_id, name, provider, model_name, temperature, system_prompt, is_active, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, true, NOW())""",
                    (
                        user_id,
                        primary_name,
                        body.preferred_model,
                        body.model_name,
                        body.temperature,
                        body.system_prompt,
                    ),
                )

    return await get_my_settings(current_user)


@router.put("/me/credentials/{provider}", response_model=LegacyCredentialStatusResponse)
async def upsert_my_credential(
    provider: Literal["gemini", "anthropic"],
    body: ModelCredentialUpdate,
    current_user: TokenData = Depends(get_current_user),
):
    """Compatibility endpoint: save provider key into primary model config."""
    user_id = _require_user_id(current_user)
    encrypted_api_key = encrypt_credential(body.api_key.strip())
    primary_name = f"Primary {provider.title()}"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id FROM user_model_configs
                   WHERE user_id = %s AND name = %s""",
                (user_id, primary_name),
            )
            existing = cur.fetchone()

            if existing:
                cur.execute(
                    """UPDATE user_model_configs
                       SET provider = %s,
                           api_key_encrypted = %s,
                           is_active = true,
                           updated_at = NOW()
                       WHERE id = %s""",
                    (provider, encrypted_api_key, existing[0]),
                )
            else:
                cur.execute(
                    """INSERT INTO user_model_configs (
                            user_id, name, provider, api_key_encrypted, is_active, updated_at
                        )
                        VALUES (%s, %s, %s, %s, true, NOW())""",
                    (user_id, primary_name, provider, encrypted_api_key),
                )

    return LegacyCredentialStatusResponse(provider=provider, configured=True)


@router.delete("/me/credentials/{provider}", response_model=LegacyCredentialStatusResponse)
async def delete_my_credential(
    provider: Literal["gemini", "anthropic"],
    current_user: TokenData = Depends(get_current_user),
):
    user_id = _require_user_id(current_user)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE user_model_configs
                   SET api_key_encrypted = NULL, updated_at = NOW()
                   WHERE user_id = %s AND provider = %s""",
                (user_id, provider),
            )

    return LegacyCredentialStatusResponse(provider=provider, configured=False)


@router.get("/me/web-search-preferences", response_model=WebSearchPreferencesResponse)
async def get_my_web_search_preferences(current_user: TokenData = Depends(get_current_user)):
    user_id = _require_user_id(current_user)
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT allow_web_search, auto_web_search, web_search_providers FROM user_search_preferences WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if row:
                return WebSearchPreferencesResponse(
                    allow_web_search=row[0],
                    auto_web_search=row[1],
                    web_search_providers=json.loads(row[2]) if isinstance(row[2], str) else row[2],
                )
    
    # Default preferences if not found in DB
    return WebSearchPreferencesResponse()


@router.put("/me/web-search-preferences", response_model=WebSearchPreferencesResponse)
async def update_my_web_search_preferences(
    updates: WebSearchPreferencesUpdate,
    current_user: TokenData = Depends(get_current_user),
):
    user_id = _require_user_id(current_user)

    # N-3 FIX: Use a single atomic INSERT ... ON CONFLICT DO UPDATE instead of SELECT-then-INSERT/UPDATE.
    # The old pattern had a race condition: two concurrent requests from the same user could both
    # see no row in SELECT, then both attempt INSERT, causing a UniqueViolation on the second.
    # ON CONFLICT DO UPDATE is atomic and eliminates the race entirely.
    #
    # For partial updates (some fields None), we still need current values as defaults.
    # We do this by reading current state in the same transaction via EXCLUDED + COALESCE.
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Read current values first (within same transaction for consistency)
            cur.execute(
                "SELECT allow_web_search, auto_web_search, web_search_providers FROM user_search_preferences WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()

            # Apply partial updates on top of existing values (or defaults if no row yet)
            allow = updates.allow_web_search if updates.allow_web_search is not None else (row[0] if row else False)
            auto = updates.auto_web_search if updates.auto_web_search is not None else (row[1] if row else False)
            providers = (
                updates.web_search_providers if updates.web_search_providers is not None
                else (json.loads(row[2]) if row and isinstance(row[2], str) else (row[2] if row else ["duckduckgo"]))
            )

            cur.execute(
                """
                INSERT INTO user_search_preferences (user_id, allow_web_search, auto_web_search, web_search_providers)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    allow_web_search = EXCLUDED.allow_web_search,
                    auto_web_search = EXCLUDED.auto_web_search,
                    web_search_providers = EXCLUDED.web_search_providers,
                    updated_at = NOW()
                """,
                (user_id, allow, auto, json.dumps(providers)),
            )
            return WebSearchPreferencesResponse(allow_web_search=allow, auto_web_search=auto, web_search_providers=providers)
