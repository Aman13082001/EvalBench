"""Provider registry.

``get_provider("ollama")`` returns a ready-to-use :class:`Provider`.
More backends (OpenAI-compatible, mock) are registered here in later
phases.
"""

from __future__ import annotations

from evalbench.core.providers.base import LLMResponse, Provider
from evalbench.core.providers.ollama import OllamaProvider

_PROVIDERS: dict[str, type[Provider]] = {
    "ollama": OllamaProvider,
}


def register_provider(name: str, cls: type[Provider]) -> None:
    _PROVIDERS[name.lower()] = cls


def available_providers() -> list[str]:
    return sorted(_PROVIDERS)


def get_provider(name: str = "ollama", **kwargs) -> Provider:
    key = (name or "ollama").lower()
    if key not in _PROVIDERS:
        raise ValueError(
            f"Unknown provider: {name!r}. Available: {available_providers()}"
        )
    return _PROVIDERS[key](**kwargs)


__all__ = [
    "LLMResponse",
    "Provider",
    "OllamaProvider",
    "get_provider",
    "register_provider",
    "available_providers",
]
