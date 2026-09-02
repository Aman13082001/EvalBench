"""Composable assertion engine."""

import pytest

from evalbench.core.assertions import (
    Assertion,
    AssertionContext,
    build_assertions,
    check_assertion,
    run_assertions,
)


def ctx(text="", **kw):
    return AssertionContext(response_text=text, **kw)


class TestBasicTypes:
    @pytest.mark.asyncio
    async def test_exact_normalizes_case_and_whitespace(self):
        o = await check_assertion(Assertion(type="exact", value="Paris"), ctx("  paris \n"))
        assert o.passed and o.score == 1.0

    @pytest.mark.asyncio
    async def test_equals_is_strict(self):
        assert (await check_assertion(Assertion(type="equals", value="Paris"), ctx("paris"))).passed is False
        assert (await check_assertion(Assertion(type="equals", value="Paris"), ctx("Paris"))).passed is True

    @pytest.mark.asyncio
    async def test_contains_is_case_sensitive(self):
        assert (await check_assertion(Assertion(type="contains", value="Paris"), ctx("The Paris metro"))).passed
        assert (await check_assertion(Assertion(type="contains", value="paris"), ctx("The Paris metro"))).passed is False

    @pytest.mark.asyncio
    async def test_icontains_is_case_insensitive(self):
        assert (await check_assertion(Assertion(type="icontains", value="PARIS"), ctx("the paris metro"))).passed

    @pytest.mark.asyncio
    async def test_regex(self):
        assert (await check_assertion(Assertion(type="regex", value=r"\d{3}-\d{4}"), ctx("call 555-1234"))).passed
        bad = await check_assertion(Assertion(type="regex", value=r"("), ctx("x"))
        assert bad.passed is False and "bad pattern" in bad.detail

    @pytest.mark.asyncio
    async def test_unknown_type_fails_gracefully(self):
        o = await check_assertion(Assertion(type="nonsense", value="x"), ctx("x"))
        assert o.passed is False
        assert "unknown assertion type" in o.detail


class TestBudgetTypes:
    @pytest.mark.asyncio
    async def test_latency_within_budget(self):
        assert (await check_assertion(Assertion(type="latency", max_ms=1000), ctx("x", latency_ms=400))).passed
        assert (await check_assertion(Assertion(type="latency", max_ms=100), ctx("x", latency_ms=400))).passed is False

    @pytest.mark.asyncio
    async def test_cost_within_budget(self):
        assert (await check_assertion(Assertion(type="cost", max_usd=0.01), ctx("x", cost_usd=0.002))).passed
        assert (await check_assertion(Assertion(type="cost", max_usd=0.001), ctx("x", cost_usd=0.002))).passed is False


class TestJsonSchema:
    @pytest.mark.asyncio
    async def test_valid_object_passes(self):
        schema = {"type": "object", "required": ["name", "age"],
                  "properties": {"age": {"type": "integer"}}}
        o = await check_assertion(
            Assertion(type="json-schema", value=schema),
            ctx('{"name": "Ada", "age": 36}'),
        )
        assert o.passed

    @pytest.mark.asyncio
    async def test_strips_code_fence(self):
        schema = {"type": "object", "required": ["ok"]}
        o = await check_assertion(
            Assertion(type="json-schema", value=schema),
            ctx('```json\n{"ok": true}\n```'),
        )
        assert o.passed

    @pytest.mark.asyncio
    async def test_bad_json_fails(self):
        o = await check_assertion(
            Assertion(type="json-schema", value={"type": "object"}),
            ctx("not json at all"),
        )
        assert o.passed is False
        assert "not valid JSON" in o.detail

    @pytest.mark.asyncio
    async def test_schema_violation_fails(self):
        schema = {"type": "object", "required": ["missing"]}
        o = await check_assertion(
            Assertion(type="json-schema", value=schema),
            ctx('{"present": 1}'),
        )
        assert o.passed is False


class TestSynthesisAndAggregation:
    def test_explicit_assertions_used_verbatim(self):
        out = build_assertions(
            [Assertion(type="regex", value="x"), {"type": "latency", "max_ms": 50}],
            "exact", "ignored", 0.8,
        )
        assert [a.type for a in out] == ["regex", "latency"]

    def test_legacy_evaluator_is_synthesised(self):
        out = build_assertions(None, "semantic", "an OS manages hardware", 0.5)
        assert len(out) == 1
        assert out[0].type == "semantic"
        assert out[0].value == "an OS manages hardware"
        assert out[0].threshold == 0.5

    def test_legacy_contains_maps_to_icontains(self):
        out = build_assertions(None, "contains", "refund", None)
        assert out[0].type == "icontains"

    @pytest.mark.asyncio
    async def test_all_must_pass(self):
        passed, score, outs = await run_assertions(
            [Assertion(type="icontains", value="paris"),
             Assertion(type="latency", max_ms=100)],
            ctx("Paris", latency_ms=999),
        )
        assert passed is False  # latency fails even though icontains passes
        assert len(outs) == 2
        assert [o.passed for o in outs] == [True, False]

    @pytest.mark.asyncio
    async def test_weighted_mean_score(self):
        passed, score, _ = await run_assertions(
            [Assertion(type="icontains", value="x", weight=3),
             Assertion(type="icontains", value="zzz", weight=1)],
            ctx("x"),
        )
        assert passed is False
        assert score == pytest.approx(0.75)  # (1*3 + 0*1) / 4
