"""Native Ollama provider (`/api/generate`)."""

from __future__ import annotations

import time

import httpx

from evalbench.config import settings
from evalbench.core.providers.base import LLMResponse, Provider


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=settings.default_request_timeout
        )

    async def generate(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
    ) -> LLMResponse:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        started = time.time()
        resp = await self._client.post(
            f"{self.base_url}/api/generate", json=payload
        )
        resp.raise_for_status()
        data = resp.json()

        latency_ms = data.get("total_duration", 0) / 1_000_000
        if not latency_ms:
            latency_ms = (time.time() - started) * 1000

        return LLMResponse(
            text=data.get("response", ""),
            model=model,
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            latency_ms=latency_ms,
            finish_reason=data.get("done_reason"),
            raw=data,
        )

    async def list_models(self) -> list[str]:
        resp = await self._client.get(f"{self.base_url}/api/tags")
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]

    async def close(self) -> None:
        await self._client.aclose()
