"""Provider abstraction: a uniform interface over LLM backends.

Every backend (Ollama, an OpenAI-compatible HTTP API, a mock) implements
``Provider`` and returns a normalized :class:`LLMResponse`, so the runner
and evaluators never care which vendor served the request.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResponse:
    """Normalized result of a single generation."""

    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class Provider(ABC):
    """A backend that can generate completions and (optionally) list models."""

    name: str = "provider"

    # Upper bound on concurrent in-flight requests to this backend. The
    # runner takes ``min(suite.concurrency, provider.max_concurrency)``.
    max_concurrency: int = 4

    @abstractmethod
    async def generate(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Generate a single completion for ``prompt``."""
        raise NotImplementedError

    async def list_models(self) -> list[str]:
        """Return available model ids, or ``[]`` if the backend can't enumerate."""
        return []

    async def has_model(self, model: str) -> bool:
        """Whether ``model`` is usable. Providers that can't list assume yes."""
        models = await self.list_models()
        if not models:
            return True
        return any(
            m == model or m == f"{model}:latest" or m.split(":")[0] == model
            for m in models
        )

    async def close(self) -> None:
        """Release any held resources (HTTP clients, ...)."""
        return None
