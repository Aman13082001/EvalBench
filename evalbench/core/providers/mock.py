"""Deterministic in-process provider for tests and offline demos."""

from __future__ import annotations

from evalbench.core.providers.base import LLMResponse, Provider


class MockProvider(Provider):
    name = "mock"
    max_concurrency = 64

    def __init__(
        self,
        response: str = "mock response",
        completion_tokens: int = 5,
        prompt_tokens: int = 3,
        latency_ms: float = 1.0,
        models: list[str] | None = None,
    ):
        self._response = response
        self._completion_tokens = completion_tokens
        self._prompt_tokens = prompt_tokens
        self._latency_ms = latency_ms
        self._models = models or ["mock-model"]

    async def generate(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
    ) -> LLMResponse:
        return LLMResponse(
            text=self._response,
            model=model,
            prompt_tokens=self._prompt_tokens,
            completion_tokens=self._completion_tokens,
            latency_ms=self._latency_ms,
            finish_reason="stop",
        )

    async def list_models(self) -> list[str]:
        return list(self._models)
