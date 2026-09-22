"""Provider registry.

Two kinds of entries:

* **Class providers** — ``ollama``, ``mock`` — a :class:`Provider` subclass
  instantiated directly.
* **Presets** — ``openai``, ``groq``, ``gemini``, ``github``, ``openrouter`` —
  an OpenAI-compatible endpoint resolved to an
  :class:`OpenAICompatibleProvider` using a ``base_url`` and an API key read
  from settings / the environment.
* **custom** — the same adapter pointed at a ``base_url`` the caller
  names, with the caller's key or none. Never a server key, and only
  through the guarded transport in :mod:`evalbench.core.endpoint`.

``get_provider("groq")`` returns a ready client (or raises with the exact
env var to set).
"""

from __future__ import annotations

import os
import time

import httpx

from evalbench.config import settings
from evalbench.core.endpoint import CONNECT_TIMEOUT, GuardedTransport, validate_endpoint
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
    # The same class, serving a recording the caller supplied. See
    # evalbench/answers.py. Keyless: the answers already exist.
    "answers": ReplayProvider,
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

# The caller's own OpenAI-compatible endpoint. Not a preset: it has no
# fixed URL and no server key, so it is neither in `_PROVIDERS` nor
# `_PRESETS` — `configured_providers()` must never list it.
CUSTOM = "custom"


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
    return sorted([*_PROVIDERS, *_PRESETS, CUSTOM])


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


def _build_custom(**overrides) -> OpenAICompatibleProvider:
    """The caller's endpoint, with the caller's key or none.

    ``api_key`` is whatever the caller supplied. It is never resolved
    from settings: an endpoint that received our Groq key in its
    Authorization header would be a one-line key exfiltration.
    """
    base_url = overrides.pop("base_url", "") or ""
    if not base_url:
        raise ValueError(
            "Provider 'custom' needs a base_url — the OpenAI-compatible "
            "endpoint to call, for example https://my-gateway.example.com/v1."
        )
    allow_private = settings.allow_private_endpoints
    endpoint = validate_endpoint(base_url, allow_private=allow_private)
    return OpenAICompatibleProvider(
        base_url=endpoint.url,
        api_key=overrides.pop("api_key", None) or None,
        name=CUSTOM,
        transport=GuardedTransport(allow_private=allow_private),
        timeout=httpx.Timeout(
            settings.default_request_timeout, connect=CONNECT_TIMEOUT
        ),
        max_concurrency=overrides.pop("max_concurrency", 4),
    )


def get_provider(name: str = "ollama", **kwargs) -> Provider:
    key = (name or "ollama").lower()
    if key == CUSTOM:
        return _build_custom(**kwargs)
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


# ── Is there actually an Ollama here? ────────────────────────────────
#
# Ollama needs no key, so it was always offered. On a hosted instance
# there is no Ollama and never will be: the visitor picks the one option
# that costs nothing, waits, and the run dies on a connection error —
# the same dead end `configured_providers` was written to close for
# keyed providers, entered from the other side.
#
# So the server asks. The answer is cached, because this is consulted on
# every provider list and every run, and an instance does not gain or
# lose a local model between two clicks.

_LOCAL_TTL = 60.0
_local_seen: tuple[float, bool] | None = None


async def local_models_available(timeout: float = 1.5) -> bool:
    """Whether an Ollama server answers at ``settings.ollama_base_url``.

    One cheap GET, cached for a minute. A miss is not an error: it is
    the honest answer that this instance serves hosted models only.
    """
    global _local_seen
    now = time.monotonic()
    if _local_seen and now - _local_seen[0] < _LOCAL_TTL:
        return _local_seen[1]
    url = settings.ollama_base_url.rstrip("/") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            ok = (await client.get(url)).status_code == 200
    except Exception:
        # Refused, unresolvable, timed out — all the same answer.
        ok = False
    _local_seen = (now, ok)
    return ok


def forget_local_probe() -> None:
    """Drop the cached answer. For tests, and for a restart mid-process."""
    global _local_seen
    _local_seen = None
