"""Estimated USD cost of a model call.

Rates are USD per 1,000,000 tokens as ``(input, output)``, taken from each
provider's public pricing page. Local backends (``ollama``, ``mock``) are
always free. A model with no entry is treated as free rather than guessed —
the cost column then reads ``$0.0000`` instead of a made-up number.
"""

from __future__ import annotations

FREE_PROVIDERS = {"ollama", "mock"}

# model name -> (usd_per_1M_input, usd_per_1M_output)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # ── OpenAI ──
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "o3-mini": (1.10, 4.40),
    # ── Groq (billed like OpenAI; free tier still has these list prices) ──
    "openai/gpt-oss-20b": (0.10, 0.50),
    "openai/gpt-oss-120b": (0.15, 0.75),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "qwen/qwen3.8-27b": (0.20, 0.40),
    # ── Google Gemini ──
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
    # ── Anthropic (reachable through OpenAI-compatible gateways) ──
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-5-sonnet": (3.00, 15.00),
}


def _lookup(model: str) -> tuple[float, float] | None:
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    # Tolerate a version/date suffix (``gpt-4o-mini-2024-07-18``). Longest
    # matching prefix wins so ``gpt-4o-mini`` is not shadowed by ``gpt-4o``.
    for name in sorted(MODEL_PRICING, key=len, reverse=True):
        if model.startswith(name):
            return MODEL_PRICING[name]
    return None


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
    in_rate, out_rate = price
    cost = (prompt_tokens / 1_000_000) * in_rate
    cost += (completion_tokens / 1_000_000) * out_rate
    return round(cost, 6)
