from __future__ import annotations

import logging
import warnings

from langchain_core.messages import HumanMessage

warnings.filterwarnings(
    "ignore",
    category=FutureWarning,
    module=r"langchain_google_genai\.chat_models",
)
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_llm_from_selection(selection, streaming: bool = False):
    """
    Build a LangChain LLM client from a ModelSelection object.
    `selection` is a ModelSelection from model_router_service.py.
    """
    provider = selection.provider
    temperature = selection.temperature
    api_key = selection.api_key

    if provider == "gemini":
        key = api_key or settings.GEMINI_API_KEY
        if not key:
            raise ValueError("GEMINI_API_KEY is not configured.")
        model_name = selection.model_name or settings.CHAT_MODEL
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=key,
            temperature=temperature,
            streaming=streaming,
        )

    if provider == "anthropic":
        key = api_key or settings.ANTHROPIC_API_KEY
        if not key:
            raise ValueError("ANTHROPIC_API_KEY is not configured for Claude model.")
        model_name = selection.model_name or "claude-3-5-sonnet-20241022"
        return ChatAnthropic(
            model_name=model_name,
            api_key=key,
            temperature=temperature,
            streaming=streaming,
        )

    if provider in ("openai", "custom"):
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ValueError("langchain-openai is not installed. Install it to use OpenAI-compatible models.") from None
        
        key = api_key or settings.OPENAI_API_KEY or "dummy"
        endpoint = selection.custom_endpoint
        model_name = selection.model_name or "gpt-4o"
        return ChatOpenAI(
            model=model_name,
            api_key=key or "dummy",
            base_url=endpoint or None,
            temperature=temperature,
            streaming=streaming,
        )

    raise ValueError(f"Unknown provider: {provider}")


def _get_default_llm(streaming: bool = False):
    """System default LLM when no user config is present."""
    model_name = settings.CHAT_MODEL
    if model_name.startswith("claude"):
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not configured.")
        return ChatAnthropic(
            model_name=model_name,
            api_key=settings.ANTHROPIC_API_KEY,
            temperature=0.2,
            streaming=streaming,
        )

    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not configured.")
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0.2,
        streaming=streaming,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_llm(streaming: bool = False, user_id: int | None = None):
    """
    Build a LangChain LLM instance.

    Resolution priority:
    1. If user_id is provided, use ModelRouter to pick from the user's configs.
       - If routing strategy is 'fallback', tries each model in order until one
         builds successfully (API key present).
       - Otherwise picks the single model chosen by the router.
    2. Fall back to system-wide settings from config/env.
    """
    if user_id is not None:
        try:
            from app.services.model_router_service import ModelRouter
            router = ModelRouter(user_id)
            logger.info(
                "get_llm user_id=%s strategy=%s pool_size=%s streaming=%s",
                user_id, router.strategy, len(router.models), streaming,
            )

            if router.strategy == "fallback":
                # Try each model in fallback order
                for sel in router.fallback_list():
                    try:
                        llm = _build_llm_from_selection(sel, streaming=streaming)
                        logger.info(
                            "get_llm SELECTED user_id=%s model=%s provider=%s endpoint=%s",
                            user_id, sel.model_name, sel.provider, sel.custom_endpoint or "(default)",
                        )
                        return llm
                    except ValueError as exc:
                        logger.warning(
                            "Fallback skip model=%s provider=%s: %s",
                            sel.model_id,
                            sel.provider,
                            exc,
                        )
            else:
                sel = router.select()
                if sel:
                    logger.info(
                        "get_llm SELECTED user_id=%s model=%s provider=%s endpoint=%s",
                        user_id, sel.model_name, sel.provider, sel.custom_endpoint or "(default)",
                    )
                    return _build_llm_from_selection(sel, streaming=streaming)
                else:
                    logger.warning("get_llm user_id=%s router.select() returned None", user_id)

        except Exception as exc:
            logger.warning(
                "user_id=%s model router failed (%s); falling back to system default",
                user_id,
                exc,
            )

    logger.info("get_llm using SYSTEM DEFAULT model=%s streaming=%s", settings.CHAT_MODEL, streaming)
    return _get_default_llm(streaming=streaming)


def summarize_history(history: list[dict[str, str]], user_id: int | None = None) -> str:
    """
    Summarizes a long conversation history into a concise paragraph
    to save tokens while preserving context.
    """
    if not history:
        return "(none)"

    llm = get_llm(streaming=False, user_id=user_id)

    history_text = "\n".join(
        [f"{m['role'].capitalize()}: {m['content']}" for m in history]
    )

    prompt = (
        "Summarize the following conversation history into a concise paragraph. "
        "Focus on the key facts, user preferences, and the current state of the discussion. "
        "Keep it under 200 words.\n\n"
        f"History:\n{history_text}"
    )

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        return response.content if hasattr(response, "content") else str(response)
    except Exception:
        return "\n".join(
            [f"{m['role'].capitalize()}: {m['content']}" for m in history[-5:]]
        )
