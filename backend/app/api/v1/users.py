from __future__ import annotations

import json
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.core.auth import TokenData, get_current_user
from app.core.database import get_conn
from app.core.redaction import redact_sensitive

logger = logging.getLogger(__name__)
from app.services.credential_service import decrypt_credential, encrypt_credential

router = APIRouter()

Provider = Literal["gemini", "anthropic", "openai", "custom"]
RoutingStrategy = Literal["random", "round_robin", "fallback"]


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
        if value is None:
            return value
        value = value.strip()
        if not value:
            return None
        if not (
            value.startswith("https://")
            or value.startswith("http://localhost")
            or value.startswith("http://127.0.0.1")
        ):
            raise ValueError("custom_endpoint must be HTTPS or localhost")
        return value


class ModelConfigUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    model_name: Optional[str] = Field(default=None, max_length=255)
    custom_endpoint: Optional[str] = Field(default=None, max_length=500)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    system_prompt: Optional[str] = Field(default=None, max_length=4000)
    is_active: Optional[bool] = None
    priority: Optional[int] = None


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
    preferred_model: Literal["gemini", "anthropic"] = "gemini"
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
    user_id = _require_user_id(current_user)
    if not current_user.can_manage_models:
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
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Check if preferences exist
            cur.execute("SELECT allow_web_search, auto_web_search, web_search_providers FROM user_search_preferences WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            
            if row:
                # Update existing
                allow = updates.allow_web_search if updates.allow_web_search is not None else row[0]
                auto = updates.auto_web_search if updates.auto_web_search is not None else row[1]
                providers = updates.web_search_providers if updates.web_search_providers is not None else (json.loads(row[2]) if isinstance(row[2], str) else row[2])
                
                cur.execute(
                    "UPDATE user_search_preferences SET allow_web_search = %s, auto_web_search = %s, web_search_providers = %s, updated_at = NOW() WHERE user_id = %s",
                    (allow, auto, json.dumps(providers), user_id),
                )
                return WebSearchPreferencesResponse(allow_web_search=allow, auto_web_search=auto, web_search_providers=providers)
            else:
                # Create new
                allow = updates.allow_web_search if updates.allow_web_search is not None else False
                auto = updates.auto_web_search if updates.auto_web_search is not None else False
                providers = updates.web_search_providers if updates.web_search_providers is not None else ["duckduckgo"]
                
                cur.execute(
                    "INSERT INTO user_search_preferences (user_id, allow_web_search, auto_web_search, web_search_providers) VALUES (%s, %s, %s, %s)",
                    (user_id, allow, auto, json.dumps(providers)),
                )
                return WebSearchPreferencesResponse(allow_web_search=allow, auto_web_search=auto, web_search_providers=providers)
