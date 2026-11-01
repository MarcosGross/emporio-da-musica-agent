"""Chat model factory, provider-agnostic via langchain's init_chat_model."""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "gpt-5.4-mini-2026-03-17"
DEFAULT_REASONING_EFFORT = "low"

# Environment variable holding each provider's API key.
API_KEY_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
    "mistralai": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
}

# OpenAI reasoning models accept reasoning_effort; older chat models reject it.
OPENAI_REASONING_MODEL = re.compile(r"^(gpt-5|o\d)")


class LLMConfigError(RuntimeError):
    """Configuration problem the user can fix in .env (shown without a stack trace)."""


def load_settings() -> dict[str, str]:
    load_dotenv(ROOT / ".env")
    return {
        "provider": os.getenv("LLM_PROVIDER", "").strip() or DEFAULT_PROVIDER,
        "model": os.getenv("LLM_MODEL", "").strip() or DEFAULT_MODEL,
        "reasoning_effort": os.getenv("LLM_REASONING_EFFORT", "").strip() or DEFAULT_REASONING_EFFORT,
    }


def get_chat_model() -> BaseChatModel:
    """Chat model from LLM_PROVIDER / LLM_MODEL in .env.

    No temperature is passed: GPT-5 models reject it. OpenAI models use the
    Responses API; reasoning models get LLM_REASONING_EFFORT (default "low"),
    which is not sent at all when set to "none".
    """
    settings = load_settings()
    provider, model = settings["provider"], settings["model"]

    key_var = API_KEY_VARS.get(provider)
    if key_var and not os.getenv(key_var, "").strip():
        raise LLMConfigError(
            f"{key_var} is not set. Add it to .env (see .env.example) to use "
            f"LLM_PROVIDER={provider}."
        )

    kwargs = {}
    if provider == "openai":
        # Chat Completions rejects tools + reasoning_effort on GPT-5.4 models; Responses API accepts both.
        kwargs["use_responses_api"] = True
        effort = settings["reasoning_effort"].lower()
        if OPENAI_REASONING_MODEL.match(model) and effort != "none":
            kwargs["reasoning_effort"] = effort

    try:
        return init_chat_model(model, model_provider=provider, **kwargs)
    except ImportError as exc:
        raise LLMConfigError(
            f"LLM_PROVIDER={provider} needs its langchain integration package: {exc}"
        ) from exc
    except ValueError as exc:
        raise LLMConfigError(f"Invalid LLM configuration ({provider}/{model}): {exc}") from exc
