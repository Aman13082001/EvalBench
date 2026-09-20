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
from evalbench.core.providers.base import (
    LLMResponse,
    Provider,
    ProviderError,
    RateLimitError,
)

# 429 retry policy: back off 1s, 2s, 4s… (capped), honouring Retry-After.
#
# The ceiling on a free tier is per-minute and shared, so one worker
# hitting it means the others are about to. Each 429 therefore pauses the
# whole provider, not just the request that saw it: without that, four
# concurrent workers spend their retries in parallel against a door that
# is shut for all of them, and the samples are lost together. A real
# 51-test run at samples=3 lost 34 of 153 generations that way.
_MAX_RETRIES = 5
_BACKOFF_BASE = 1.0
_BACKOFF_CAP = 20.0


def _error_body(resp) -> dict:
    """The ``error`` object of a failed reply, or ``{}``.

    OpenAI, Groq and OpenRouter answer ``{"error": {...}}``; Google wraps
    the same object in a list. A reply with no JSON at all is fine too.
    """
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001 - an HTML error page, or a bare fake
        return {}
    if isinstance(body, list) and body:
        body = body[0]
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, str):
        return {"message": err}
    return err if isinstance(err, dict) else {}


def _error_message(err: dict) -> str:
    """The provider's sentence about what went wrong. OpenRouter relays
    the upstream's words in ``metadata.raw``, which say more than its own
    "Provider returned error"."""
    meta = err.get("metadata")
    raw = meta.get("raw") if isinstance(meta, dict) else None
    return str(raw or err.get("message") or "").strip()


def _quota_exhausted(err: dict) -> bool:
    """A 429 that no amount of waiting will clear: the account has no
    credit. OpenAI marks it ``insufficient_quota``."""
    return err.get("type") == "insufficient_quota" or err.get("code") in (
        "insufficient_quota",
        "credit_balance_exhausted",
    )


class OpenAICompatibleProvider(Provider):
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        name: str = "openai-compat",
        extra_headers: dict[str, str] | None = None,
        timeout: float | httpx.Timeout | None = None,
        max_concurrency: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        # Shared across every in-flight request to this provider: when one
        # is rate limited, they all wait.
        self._paused_until = 0.0
        if max_concurrency is not None:
            self.max_concurrency = max_concurrency
        # No key, no header. A personal model server behind a tunnel has
        # no key to send, and "Bearer None" is not the same as none.
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        if extra_headers:
            headers.update(extra_headers)
        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=timeout or settings.default_request_timeout,
            # A 302 from a model endpoint has no honest meaning, and a
            # 302 to an internal address is an attack. httpx already
            # defaults to this; it is spelled out so it stays.
            follow_redirects=False,
            # Custom endpoints get the transport that checks where it is
            # connecting. See evalbench/core/endpoint.py.
            transport=transport,
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

    def paused_for(self) -> float:
        """Seconds still owed to a rate limit, shared across callers."""
        return max(0.0, self._paused_until - time.monotonic())

    def _pause_for(self, delay: float) -> None:
        """Shut the door for everyone until ``delay`` has passed."""
        self._paused_until = max(
            self._paused_until, time.monotonic() + delay
        )

    async def _post_with_retry(self, payload: dict) -> httpx.Response:
        """POST /chat/completions, retrying 429s with a shared backoff."""
        for attempt in range(_MAX_RETRIES + 1):
            # Another worker may already have been told to wait. Spending
            # a request now would just collect the same 429.
            waiting = self.paused_for()
            if waiting > 0:
                await asyncio.sleep(waiting)

            resp = await self._client.post(
                f"{self.base_url}/chat/completions", json=payload
            )
            if resp.status_code != 429:
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as e:
                    # "404 Not Found for url …" says nothing; Google's
                    # body names the model that replaced the retired one.
                    why = _error_message(_error_body(resp))
                    if not why:
                        raise
                    raise ProviderError(
                        f"{self.name}: {resp.status_code} {why}"
                    ) from e
                return resp

            err = _error_body(resp)
            if _quota_exhausted(err):
                # Not backpressure. Five retries would burn half a minute
                # and then call it a rate limit, which it is not.
                raise ProviderError(
                    f"{self.name}: {_error_message(err) or 'no credits remaining'}"
                )

            if attempt == _MAX_RETRIES:
                why = _error_message(err)
                raise RateLimitError(
                    f"{self.name}: rate limited (429) after "
                    f"{_MAX_RETRIES} retries" + (f" — {why}" if why else "")
                )

            retry_after = (resp.headers or {}).get("retry-after")
            if retry_after and str(retry_after).isdigit():
                delay = float(retry_after)
            else:
                delay = min(_BACKOFF_BASE * (2 ** attempt), _BACKOFF_CAP)
            self._pause_for(delay)
            await asyncio.sleep(delay)

        # unreachable
        raise RateLimitError(f"{self.name}: rate limited")

    async def list_models(self) -> list[str]:
        # Best effort — not every gateway implements /models.
        try:
            resp = await self._client.get(f"{self.base_url}/models")
            resp.raise_for_status()
            ids = [m["id"] for m in resp.json().get("data", [])]
        except Exception:
            return []
        # Google's /models answers with resource names (``models/gemini-
        # 2.5-flash``) while its /chat/completions wants the bare id and
        # 404s on the resource name. List what the chat endpoint accepts,
        # or the dropdown offers a name that fails and refuses the one
        # that works.
        return [i.removeprefix("models/") for i in ids]

    async def close(self) -> None:
        await self._client.aclose()
