"""Composable per-test assertions.

A test may declare a list of assertions under the YAML key ``assert``. Every
assertion must pass for the test to pass; each yields a 0..1 score and the
test score is the weighted mean.

Legacy suites (``evaluator`` + ``expected`` + ``threshold``, no ``assert``)
have a single assertion synthesised for them, so nothing breaks.

Day 7 types:  exact, equals, contains, icontains, regex, semantic, judge
Day 8 types:  json-schema, llm-rubric, latency, cost
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

from evalbench.core.providers.base import Provider


class Assertion(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str

    # Expected string / regex pattern / JSON-schema dict, depending on type.
    value: Any = None

    # Graded types (semantic, judge, llm-rubric) compare their score here.
    threshold: float | None = None

    # Budget types.
    max_ms: float | None = None
    max_usd: float | None = None

    # llm-rubric: the natural-language grading criteria.
    criteria: str | None = None

    # Relative contribution to the test score.
    weight: float = 1.0


@dataclass
class AssertionOutcome:
    type: str
    passed: bool
    score: float
    detail: str = ""
    weight: float = 1.0


@dataclass
class AssertionContext:
    response_text: str
    prompt: str = ""
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    judge_provider: Provider | None = None
    judge_model: str = "llama3.1"
    extras: dict = field(default_factory=dict)


# ── Legacy evaluator name -> assertion type ──
_LEGACY_MAP = {
    "exact": "exact",
    "contains": "icontains",
    "semantic": "semantic",
    "judge": "judge",
}


def build_assertions(
    explicit: list[Assertion] | list[dict] | None,
    evaluator: str,
    expected: str,
    threshold: float | None,
) -> list[Assertion]:
    """Return the assertion list to run for a test.

    If the test declared ``assert:`` we use it verbatim; otherwise we
    synthesise one assertion from the legacy evaluator/expected/threshold.
    """
    if explicit:
        return [
            a if isinstance(a, Assertion) else Assertion(**a)
            for a in explicit
        ]

    a_type = _LEGACY_MAP.get(evaluator, evaluator)
    return [Assertion(type=a_type, value=expected, threshold=threshold)]


# ─────────────────────────────────────────────────────────────
# Checkers
# ─────────────────────────────────────────────────────────────


def _blank(actual: str) -> bool:
    return not actual.strip()


async def _check_exact(a: Assertion, ctx: AssertionContext) -> AssertionOutcome:
    ok = (
        not _blank(ctx.response_text)
        and ctx.response_text.strip().lower() == str(a.value).strip().lower()
    )
    return AssertionOutcome("exact", ok, 1.0 if ok else 0.0)


async def _check_equals(a: Assertion, ctx: AssertionContext) -> AssertionOutcome:
    ok = ctx.response_text == str(a.value)
    return AssertionOutcome("equals", ok, 1.0 if ok else 0.0)


async def _check_contains(a: Assertion, ctx: AssertionContext) -> AssertionOutcome:
    ok = not _blank(ctx.response_text) and str(a.value) in ctx.response_text
    return AssertionOutcome("contains", ok, 1.0 if ok else 0.0)


async def _check_icontains(a: Assertion, ctx: AssertionContext) -> AssertionOutcome:
    ok = (
        not _blank(ctx.response_text)
        and str(a.value).lower() in ctx.response_text.lower()
    )
    return AssertionOutcome("icontains", ok, 1.0 if ok else 0.0)


async def _check_regex(a: Assertion, ctx: AssertionContext) -> AssertionOutcome:
    try:
        hit = re.search(str(a.value), ctx.response_text, re.DOTALL) is not None
    except re.error as e:
        return AssertionOutcome("regex", False, 0.0, f"bad pattern: {e}")
    return AssertionOutcome("regex", hit, 1.0 if hit else 0.0)


async def _check_semantic(
    a: Assertion, ctx: AssertionContext
) -> AssertionOutcome:
    from evalbench.core.evaluators.semantic import SemanticSimilarityEvaluator

    passed, score = await SemanticSimilarityEvaluator().evaluate(
        str(a.value), ctx.response_text, ctx.prompt, a.threshold
    )
    return AssertionOutcome(
        "semantic", bool(passed), float(score), f"cosine={score:.3f}"
    )


async def _check_judge(a: Assertion, ctx: AssertionContext) -> AssertionOutcome:
    from evalbench.core.evaluators.judge import LLMJudgeEvaluator

    ev = LLMJudgeEvaluator(
        judge_model=ctx.judge_model, provider=ctx.judge_provider
    )
    passed, score = await ev.evaluate(
        str(a.value), ctx.response_text, ctx.prompt, a.threshold
    )
    return AssertionOutcome(
        "judge", bool(passed), float(score), f"rating={score * 5:.1f}/5"
    )


async def _check_latency(
    a: Assertion, ctx: AssertionContext
) -> AssertionOutcome:
    budget = a.max_ms if a.max_ms is not None else a.value
    if budget is None:
        return AssertionOutcome("latency", False, 0.0, "no max_ms set")
    ok = ctx.latency_ms <= float(budget)
    return AssertionOutcome(
        "latency",
        ok,
        1.0 if ok else 0.0,
        f"{ctx.latency_ms:.0f}ms vs {float(budget):.0f}ms budget",
    )


async def _check_cost(a: Assertion, ctx: AssertionContext) -> AssertionOutcome:
    budget = a.max_usd if a.max_usd is not None else a.value
    if budget is None:
        return AssertionOutcome("cost", False, 0.0, "no max_usd set")
    ok = ctx.cost_usd <= float(budget)
    return AssertionOutcome(
        "cost",
        ok,
        1.0 if ok else 0.0,
        f"${ctx.cost_usd:.6f} vs ${float(budget):.6f} budget",
    )


async def _check_json_schema(
    a: Assertion, ctx: AssertionContext
) -> AssertionOutcome:
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - dependency always present in prod
        return AssertionOutcome(
            "json-schema", False, 0.0, "jsonschema not installed"
        )

    raw = ctx.response_text.strip()
    # Tolerate a fenced ```json block.
    fence = re.search(r"```(?:json)?\s*(.+?)```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()

    try:
        instance = json.loads(raw)
    except json.JSONDecodeError as e:
        return AssertionOutcome(
            "json-schema", False, 0.0, f"not valid JSON: {e}"
        )

    try:
        jsonschema.validate(instance, a.value)
    except jsonschema.ValidationError as e:
        return AssertionOutcome(
            "json-schema", False, 0.0, f"schema: {e.message}"
        )
    return AssertionOutcome("json-schema", True, 1.0, "valid")


async def _check_llm_rubric(
    a: Assertion, ctx: AssertionContext
) -> AssertionOutcome:
    from evalbench.core.evaluators.judge import LLMJudgeEvaluator

    criteria = a.criteria or str(a.value or "")
    cutoff = a.threshold if a.threshold is not None else 0.6

    prompt = (
        "You are grading an AI response against a rubric.\n\n"
        f"QUESTION: {ctx.prompt}\n\n"
        f"RUBRIC: {criteria}\n\n"
        f"RESPONSE: {ctx.response_text}\n\n"
        "Think step by step about how well the response meets the rubric, "
        "then finish with two lines exactly:\n"
        "SCORE: <integer 1-5>\n"
        "REASON: <one sentence>"
    )

    ev = LLMJudgeEvaluator(
        judge_model=ctx.judge_model, provider=ctx.judge_provider
    )
    try:
        raw = await ev._ask_judge(prompt)
        score, reason = ev._parse_response(raw)
    except Exception as e:  # noqa: BLE001 - judge unavailable
        return AssertionOutcome("llm-rubric", False, 0.0, f"judge error: {e}")

    ok = score >= cutoff
    return AssertionOutcome("llm-rubric", ok, float(score), reason)


_CHECKERS = {
    "exact": _check_exact,
    "equals": _check_equals,
    "contains": _check_contains,
    "icontains": _check_icontains,
    "regex": _check_regex,
    "semantic": _check_semantic,
    "judge": _check_judge,
    "latency": _check_latency,
    "cost": _check_cost,
    "json-schema": _check_json_schema,
    "llm-rubric": _check_llm_rubric,
}


def available_assertion_types() -> list[str]:
    return sorted(_CHECKERS)


async def check_assertion(
    assertion: Assertion, ctx: AssertionContext
) -> AssertionOutcome:
    checker = _CHECKERS.get(assertion.type)
    if checker is None:
        return AssertionOutcome(
            assertion.type,
            False,
            0.0,
            f"unknown assertion type '{assertion.type}'",
        )
    outcome = await checker(assertion, ctx)
    outcome.weight = assertion.weight
    return outcome


async def run_assertions(
    assertions: list[Assertion], ctx: AssertionContext
) -> tuple[bool, float, list[AssertionOutcome]]:
    """Run every assertion. Test passes iff all pass; score = weighted mean."""
    outcomes = [await check_assertion(a, ctx) for a in assertions]
    if not outcomes:
        return False, 0.0, []

    passed = all(o.passed for o in outcomes)
    total_w = sum(o.weight for o in outcomes) or 1.0
    score = sum(o.score * o.weight for o in outcomes) / total_w
    return passed, round(score, 4), outcomes
