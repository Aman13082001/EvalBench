"""Backwards-compatible shim.

Prefer ``from evalbench.core.providers import get_provider``. ``OllamaClient``
is kept as an alias so older imports keep working; note that its
``generate()`` now returns an :class:`~evalbench.core.providers.base.LLMResponse`
rather than a raw dict.
"""

from evalbench.core.providers.ollama import OllamaProvider as OllamaClient

__all__ = ["OllamaClient"]
