"""
Model Router Service — selects a model from the user's configured pool.

Supports three routing strategies:
  - random   : pick uniformly at random from enabled models
  - round_robin : cycle through enabled models (stateless per-request hash)
  - fallback : try first model; on LLM error the caller retries with next
"""

from __future__ import annotations

import contextlib
import json
import logging
import random
import time

from app.core.database import get_conn
from app.services.credential_service import decrypt_credential

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

KNOWN_PROVIDERS = {"gemini", "anthropic", "openai", "custom"}


class ModelSelection:
    """Value object returned by the router."""

    def __init__(
        self,
        model_id: int,
        provider: str,
        model_name: str | None,
        api_key: str | None,
        custom_endpoint: str | None,
        custom_headers: dict | None,
        temperature: float,
        system_prompt: str | None,
    ):
        self.model_id = model_id
        self.provider = provider
        self.model_name = model_name
        self.api_key = api_key
        self.custom_endpoint = custom_endpoint
        self.custom_headers = custom_headers
        self.temperature = temperature
        self.system_prompt = system_prompt

    def __repr__(self) -> str:
        return (
            f"ModelSelection(id={self.model_id}, provider={self.provider}, "
            f"model={self.model_name})"
        )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class ModelRouter:
    """Loads user model configs and picks one per request."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.strategy: str = "random"
        self.enabled_ids: list[int] = []
        self.fallback_order: list[int] = []
        self.models: dict[int, dict] = {}
        self._load()

    # ----- DB loading -----

    def _load(self) -> None:
        with get_conn() as conn, conn.cursor() as cur:
            # Routing config
            cur.execute(
                """SELECT routing_strategy, enabled_model_ids, fallback_order
                       FROM user_routing_config WHERE user_id = %s""",
                (self.user_id,),
            )
            row = cur.fetchone()
            if row:
                self.strategy = row[0] or "random"
                self.enabled_ids = json.loads(row[1]) if row[1] else []
                self.fallback_order = json.loads(row[2]) if row[2] else []

            # Active model configs
            cur.execute(
                """SELECT id, provider, model_name, api_key_encrypted,
                              custom_endpoint, custom_headers,
                              temperature, system_prompt, priority
                       FROM user_model_configs
                       WHERE user_id = %s AND is_active = true
                       ORDER BY priority DESC, id""",
                (self.user_id,),
            )
            for r in cur.fetchall():
                self.models[r[0]] = {
                    "provider": r[1],
                    "model_name": r[2],
                    "api_key_encrypted": r[3],
                    "custom_endpoint": r[4],
                    "custom_headers": r[5],
                    "temperature": r[6] if r[6] is not None else 0.2,
                    "system_prompt": r[7],
                    "priority": r[8] or 0,
                }

    # ----- Selection -----

    def select(self) -> ModelSelection | None:
        """Pick a model using the configured strategy."""
        if not self.models:
            return None

        pool = self._effective_pool()
        if not pool:
            return None

        if self.strategy == "round_robin":
            chosen_id = self._round_robin(pool)
        elif self.strategy == "fallback":
            chosen_id = pool[0]  # first in fallback order
        else:
            chosen_id = random.choice(pool)

        return self._to_selection(chosen_id)

    def fallback_list(self) -> list[ModelSelection]:
        """Return ordered list for fallback-chain callers."""
        pool = self._effective_pool()
        return [self._to_selection(mid) for mid in pool]

    # ----- Internal -----

    def _effective_pool(self) -> list[int]:
        """Resolve which model IDs to consider."""
        if self.strategy == "fallback" and self.fallback_order:
            return [mid for mid in self.fallback_order if mid in self.models]
        if self.enabled_ids:
            return [mid for mid in self.enabled_ids if mid in self.models]
        return list(self.models.keys())

    def _round_robin(self, pool: list[int]) -> int:
        """Stateless round-robin using current second modulo pool size."""
        idx = int(time.time()) % len(pool)
        return pool[idx]

    def _to_selection(self, model_id: int) -> ModelSelection:
        cfg = self.models[model_id]
        api_key = None
        if cfg["api_key_encrypted"]:
            api_key = decrypt_credential(cfg["api_key_encrypted"])

        custom_headers = None
        if cfg["custom_headers"]:
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                custom_headers = json.loads(cfg["custom_headers"])

        return ModelSelection(
            model_id=model_id,
            provider=cfg["provider"],
            model_name=cfg["model_name"],
            api_key=api_key,
            custom_endpoint=cfg["custom_endpoint"],
            custom_headers=custom_headers,
            temperature=cfg["temperature"],
            system_prompt=cfg["system_prompt"],
        )
