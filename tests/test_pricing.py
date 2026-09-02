"""Cost estimation from token counts."""

import pytest

from evalbench.pricing import estimate_cost


def test_known_model_cost_matches_list_price():
    # gpt-4o-mini: $0.15 / 1M in, $0.60 / 1M out.
    assert estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000) == pytest.approx(0.75)


def test_unknown_model_is_treated_as_free():
    assert estimate_cost("totally-made-up-model", 5000, 5000) == 0.0


def test_local_providers_are_always_free():
    assert estimate_cost("gpt-4o", 1000, 1000, provider="ollama") == 0.0
    assert estimate_cost("gpt-4o", 1000, 1000, provider="mock") == 0.0


def test_version_suffix_falls_back_to_base_price():
    base = estimate_cost("gpt-4o-mini", 1000, 500)
    dated = estimate_cost("gpt-4o-mini-2024-07-18", 1000, 500)
    assert base > 0
    assert dated == base


def test_longest_prefix_wins_over_shorter_one():
    # "gpt-4o-mini-x" must price as gpt-4o-mini, not as gpt-4o.
    mini = estimate_cost("gpt-4o-mini", 1_000_000, 0)  # 0.15
    shadowed = estimate_cost("gpt-4o-mini-x", 1_000_000, 0)
    assert shadowed == mini == pytest.approx(0.15)


def test_zero_tokens_zero_cost():
    assert estimate_cost("gpt-4o", 0, 0) == 0.0
