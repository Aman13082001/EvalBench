"""Provider for any OpenAI-compatible `/chat/completions` endpoint.

One adapter covers OpenAI, Groq, Google Gemini (its OpenAI-compat
endpoint), GitHub Models, OpenRouter, a local vLLM, etc. — they only
differ by ``base_url`` and which env var holds the key.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from evalbench.config import settings
from evalbench.core.providers.base import LLMResponse, Provider, RateLimitError

# 429 retry policy: back off 1s, 2s, 4s (capped), honouring Retry-After.
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0
_BACKOFF_CAP = 10.0


class OpenAICompatibleProvider(Provider):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        name: str = "openai-compat",
        extra_headers: dict[str, str] | None = None,
        timeout: float | None = None,
        max_concurrency: int | None = None,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        if max_concurrency is not None:
            self.max_concurrency = max_concurrency
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
        resp = await self._post_with_retry(payload)
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

    async def _post_with_retry(self, payload: dict) -> httpx.Response:
        """POST /chat/completions, retrying 429s with backoff."""
        for attempt in range(_MAX_RETRIES + 1):
            resp = await self._client.post(
                f"{self.base_url}/chat/completions", json=payload
            )
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp

            if attempt == _MAX_RETRIES:
                raise RateLimitError(
                    f"{self.name}: rate limited (429) after "
                    f"{_MAX_RETRIES} retries"
                )

            retry_after = resp.headers.get("retry-after")
            if retry_after and retry_after.isdigit():
                delay = float(retry_after)
            else:
                delay = min(_BACKOFF_BASE * (2 ** attempt), _BACKOFF_CAP)
            await asyncio.sleep(delay)

        # unreachable
        raise RateLimitError(f"{self.name}: rate limited")

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
