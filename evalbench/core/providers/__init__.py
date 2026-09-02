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

_PROVIDERS: dict[str, type[Provider]] = {
    "ollama": OllamaProvider,
    "mock": MockProvider,
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


def register_provider(name: str, cls: type[Provider]) -> None:
    _PROVIDERS[name.lower()] = cls


def available_providers() -> list[str]:
    return sorted([*_PROVIDERS, *_PRESETS])


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
        **overrides,
    )


def get_provider(name: str = "ollama", **kwargs) -> Provider:
    key = (name or "ollama").lower()
    if key in _PROVIDERS:
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
