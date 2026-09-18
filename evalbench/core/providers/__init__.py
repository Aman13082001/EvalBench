"""Provider registry.

Two kinds of entries:

* **Class providers** — ``ollama``, ``mock`` — a :class:`Provider` subclass
  instantiated directly.
* **Presets** — ``openai``, ``groq``, ``gemini``, ``github``, ``openrouter`` —
  an OpenAI-compatible endpoint resolved to an
  :class:`OpenAICompatibleProvider` using a ``base_url`` and an API key read
  from settings / the environment.

``get_provider("groq")`` returns a ready client (or raises with the exact
env var to set).
"""

from __future__ import annotations

import os

from evalbench.config import settings
from evalbench.core.providers.base import LLMResponse, Provider
from evalbench.core.providers.mock import MockProvider
from evalbench.core.providers.ollama import OllamaProvider
from evalbench.core.providers.openai_compat import OpenAICompatibleProvider
from evalbench.core.providers.replay import ReplayProvider

_PROVIDERS: dict[str, type[Provider]] = {
    "ollama": OllamaProvider,
    "mock": MockProvider,
    # Replays recorded answers so the demo suite runs with no
    # API key at all. See providers/replay.py.
    "demo": ReplayProvider,
}

# name -> (base_url, api-key env var). Key is also read from the matching
# lowercase settings attribute, so a .env entry works too.
_PRESETS: dict[str, tuple[str, str]] = {
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "gemini": (
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
    ),
    "github": ("https://models.inference.ai.azure.com", "GITHUB_TOKEN"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
}

# Safe parallel-request ceilings for each hosted preset's free tier.
_PRESET_CONCURRENCY: dict[str, int] = {
    "openai": 8,
    "groq": 4,
    "gemini": 2,
    "github": 1,
    "openrouter": 4,
}


# Substrings that mark a model as something other than a chat model —
# speech, audio, moderation classifiers, embeddings. Provider model lists
# include all of these; offering Whisper as a model to evaluate is a
# trap, and a prompt-guard classifier answers with a probability, not
# text. A user can still type any name — this only filters suggestions.
_NOT_CHAT = (
    "whisper", "tts", "orpheus", "speech", "audio", "transcri",
    # the classifier families, not bare "guard" — gpt-oss-safeguard-20b
    # is a safety-tuned chat model and answers normally
    "prompt-guard", "llama-guard", "llamaguard",
    "moderation", "embed", "rerank", "vision-encoder",
)


def is_chat_model(name: str) -> bool:
    """False for names that structurally cannot answer a prompt."""
    n = name.lower()
    return not any(tag in n for tag in _NOT_CHAT)


def register_provider(name: str, cls: type[Provider]) -> None:
    _PROVIDERS[name.lower()] = cls


def available_providers() -> list[str]:
    """Every provider name the system understands.

    Not the same question as whether *this server* can reach it: a caller
    supplying their own key can use any of these.
    """
    return sorted([*_PROVIDERS, *_PRESETS])


def configured_providers() -> list[str]:
    """Providers this server can reach on its own key.

    Everything in `_PROVIDERS` needs no key at all — Ollama is local, the
    replay provider answers from a recording — so those are always here.
    A hosted preset only counts when its key actually resolves.

    The picker offered all six regardless, so choosing one without a key
    was accepted, queued, and then failed inside the worker with
    "Provider 'github' needs an API key" — a failed run instead of a
    reason.
    """
    return sorted(
        [*_PROVIDERS, *(n for n in _PRESETS if _resolve_key(_PRESETS[n][1]))]
    )


def _resolve_key(env_var: str) -> str:
    return getattr(settings, env_var.lower(), "") or os.getenv(env_var, "")


def _build_preset(name: str, **overrides) -> OpenAICompatibleProvider:
    base_url, env_var = _PRESETS[name]
    api_key = overrides.pop("api_key", "") or _resolve_key(env_var)
    if not api_key:
        raise ValueError(
            f"Provider '{name}' needs an API key. Set {env_var} in your "
            f"environment or .env file."
        )
    return OpenAICompatibleProvider(
        base_url=overrides.pop("base_url", "") or base_url,
        api_key=api_key,
        name=name,
        max_concurrency=overrides.pop(
            "max_concurrency", _PRESET_CONCURRENCY.get(name)
        ),
        **overrides,
    )


def get_provider(name: str = "ollama", **kwargs) -> Provider:
    key = (name or "ollama").lower()
    if key in _PROVIDERS:
        # A caller's key is for hosted providers. A suite can still route
        # its judge through a keyless one — the demo suite judges on the
        # replay provider — and passing the key through crashed the run
        # with "unexpected keyword argument 'api_key'".
        kwargs.pop("api_key", None)
        return _PROVIDERS[key](**kwargs)
    if key in _PRESETS:
        return _build_preset(key, **kwargs)
    raise ValueError(
        f"Unknown provider: {name!r}. Available: {available_providers()}"
    )


__all__ = [
    "LLMResponse",
    "Provider",
    "OllamaProvider",
    "MockProvider",
    "OpenAICompatibleProvider",
    "get_provider",
    "register_provider",
    "available_providers",
]
