"""Provider for any OpenAI-compatible `/chat/completions` endpoint.

One adapter covers OpenAI, Groq, Google Gemini (its OpenAI-compat
endpoint), GitHub Models, OpenRouter, a local vLLM, etc. — they only
differ by ``base_url`` and which env var holds the key.
"""

from __future__ import annotations

import time

import httpx

from evalbench.config import settings
from evalbench.core.providers.base import LLMResponse, Provider


class OpenAICompatibleProvider(Provider):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        name: str = "openai-compat",
        extra_headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"}
        if extra_headers:
            headers.update(extra_headers)
        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=timeout or settings.default_request_timeout,
        )

    async def generate(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
    ) -> LLMResponse:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        started = time.time()
        resp = await self._client.post(
            f"{self.base_url}/chat/completions", json=payload
        )
        resp.raise_for_status()
        data = resp.json()

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = data.get("usage") or {}

        return LLMResponse(
            text=message.get("content") or "",
            model=data.get("model", model),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=(time.time() - started) * 1000,
            finish_reason=choice.get("finish_reason"),
            raw=data,
        )

    async def list_models(self) -> list[str]:
        # Best effort — not every gateway implements /models.
        try:
            resp = await self._client.get(f"{self.base_url}/models")
            resp.raise_for_status()
            return [m["id"] for m in resp.json().get("data", [])]
        except Exception:
            return []

    async def close(self) -> None:
        await self._client.aclose()
