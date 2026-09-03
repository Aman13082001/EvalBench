"""Estimated USD cost of a model call.

Rates are USD per 1,000,000 tokens. Each entry carries ``as_of`` (the
month the rate was last checked) and ``source`` so the table's staleness
is visible — `scripts/check_pricing.py` fails CI on entries that go
stale. Local backends (``ollama``, ``mock``) are always free; a model
with no entry is treated as free rather than guessed, unless the caller
opts into ``--strict-cost``.
"""

from __future__ import annotations

from typing import NamedTuple

FREE_PROVIDERS = {"ollama", "mock"}


class ModelPrice(NamedTuple):
    input: float  # USD per 1M input tokens
    output: float  # USD per 1M output tokens
    as_of: str  # YYYY-MM, when this rate was last verified
    source: str


_OPENAI = "openai.com/api/pricing"
_GROQ = "groq.com/pricing"
_GEMINI = "ai.google.dev/pricing"
_ANTHROPIC = "anthropic.com/pricing"

MODEL_PRICING: dict[str, ModelPrice] = {
    # ── OpenAI ──
    "gpt-4o": ModelPrice(2.50, 10.00, "2026-08", _OPENAI),
    "gpt-4o-mini": ModelPrice(0.15, 0.60, "2026-08", _OPENAI),
    "gpt-4.1": ModelPrice(2.00, 8.00, "2026-08", _OPENAI),
    "gpt-4.1-mini": ModelPrice(0.40, 1.60, "2026-08", _OPENAI),
    "gpt-4.1-nano": ModelPrice(0.10, 0.40, "2026-08", _OPENAI),
    "o3-mini": ModelPrice(1.10, 4.40, "2026-08", _OPENAI),
    # ── Groq ──
    "openai/gpt-oss-20b": ModelPrice(0.10, 0.50, "2026-08", _GROQ),
    "openai/gpt-oss-120b": ModelPrice(0.15, 0.75, "2026-08", _GROQ),
    "llama-3.3-70b-versatile": ModelPrice(0.59, 0.79, "2026-08", _GROQ),
    "llama-3.1-8b-instant": ModelPrice(0.05, 0.08, "2026-08", _GROQ),
    "qwen/qwen3.8-27b": ModelPrice(0.20, 0.40, "2026-08", _GROQ),
    # ── Google Gemini ──
    "gemini-2.0-flash": ModelPrice(0.10, 0.40, "2026-08", _GEMINI),
    "gemini-1.5-flash": ModelPrice(0.075, 0.30, "2026-08", _GEMINI),
    "gemini-1.5-pro": ModelPrice(1.25, 5.00, "2026-08", _GEMINI),
    # ── Anthropic (via OpenAI-compatible gateways) ──
    "claude-3-5-haiku": ModelPrice(0.80, 4.00, "2026-08", _ANTHROPIC),
    "claude-3-5-sonnet": ModelPrice(3.00, 15.00, "2026-08", _ANTHROPIC),
}


def _lookup(model: str) -> ModelPrice | None:
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    # Tolerate a version/date suffix (``gpt-4o-mini-2024-07-18``). Longest
    # matching prefix wins so ``gpt-4o-mini`` is not shadowed by ``gpt-4o``.
    for name in sorted(MODEL_PRICING, key=len, reverse=True):
        if model.startswith(name):
            return MODEL_PRICING[name]
    return None


def is_priced(model: str, provider: str | None = None) -> bool:
    """Whether cost for this call can be computed (free providers count)."""
    if provider and provider.lower() in FREE_PROVIDERS:
        return True
    return _lookup(model) is not None


def estimate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    provider: str | None = None,
) -> float:
    """USD cost of the call(s) that produced these token counts.

    Returns ``0.0`` for local/free providers and for any model without a
    pricing entry.
    """
    if provider and provider.lower() in FREE_PROVIDERS:
        return 0.0
    price = _lookup(model)
    if price is None:
        return 0.0
    cost = (prompt_tokens / 1_000_000) * price.input
    cost += (completion_tokens / 1_000_000) * price.output
    return round(cost, 6)
