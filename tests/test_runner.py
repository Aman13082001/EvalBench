"""Unit tests for TestRunner with a mocked provider."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from evalbench.core.providers.base import LLMResponse
from evalbench.core.runner import TestRunner as Runner
from evalbench.db.schemas import TestCase as Case
from evalbench.db.schemas import TestSuite as Suite


def _resp(
    text: str,
    tokens: int = 10,
    latency_ms: float = 1000.0,
    prompt_tokens: int = 5,
) -> LLMResponse:
    return LLMResponse(
        text=text,
        model="llama3.1",
        prompt_tokens=prompt_tokens,
        completion_tokens=tokens,
        latency_ms=latency_ms,
    )


@pytest.fixture
def sample_suite():
    return Suite(
        name="Test Suite",
        model="llama3.1",
        evaluator="exact",
        tests=[
            Case(
                name="t1",
                prompt="What is 2+2?",
                expected="4",
                threshold=0.8,
            ),
            Case(
                name="t2",
                prompt="Capital of France?",
                expected="Paris",
                threshold=0.8,
            ),
        ],
    )


@pytest.fixture
def mock_ollama():
    with patch("evalbench.core.runner.get_provider") as mock_get:
        instance = AsyncMock()
        instance.name = "ollama"
        instance.max_concurrency = 8
        instance.has_model = AsyncMock(return_value=True)
        instance.list_models = AsyncMock(return_value=["llama3.1", "mistral"])
        instance.generate = AsyncMock(return_value=_resp("4"))
        instance.close = AsyncMock()

        mock_get.return_value = instance
        yield instance


@pytest.mark.asyncio
async def test_run_suite_exact_match(
    mock_ollama,
    sample_suite,
):
    runner = Runner()

    run = await runner.run_suite(
        sample_suite,
        "suite_123",
    )

    assert run.suite_id == "suite_123"
    assert run.model == "llama3.1"
    assert run.evaluator == "exact"
    assert len(run.results) == 2

    assert run.results[0].passed is True
    assert run.results[0].score == 1.0
    assert run.results[0].actual == "4"

    await runner.close()


@pytest.mark.asyncio
async def test_run_suite_tracks_token_split_and_free_cost(
    mock_ollama,
    sample_suite,
):
    runner = Runner()
    run = await runner.run_suite(sample_suite, "suite_cost")

    r = run.results[0]
    assert r.prompt_tokens == 5
    assert r.completion_tokens == 10
    # Ollama is a local/free provider -> no cost.
    assert r.cost_usd == 0.0

    await runner.close()


@pytest.mark.asyncio
async def test_run_suite_estimates_hosted_cost(mock_ollama):
    suite = Suite(
        name="Hosted",
        provider="groq",
        model="openai/gpt-oss-20b",
        evaluator="exact",
        tests=[
            Case(name="t1", prompt="2+2?", expected="4", threshold=0.8),
        ],
    )
    mock_ollama.name = "groq"
    mock_ollama.generate = AsyncMock(
        return_value=_resp("4", tokens=1000, prompt_tokens=2000)
    )

    runner = Runner()
    run = await runner.run_suite(suite, "suite_hosted")

    # 2000/1e6 * 0.10 + 1000/1e6 * 0.50 = 0.0007
    assert run.results[0].cost_usd == pytest.approx(0.0007)

    await runner.close()


@pytest.mark.asyncio
async def test_run_suite_model_not_found(
    mock_ollama,
    sample_suite,
):
    mock_ollama.has_model = AsyncMock(
        return_value=False
    )

    mock_ollama.list_models = AsyncMock(
        return_value=["mistral"]
    )

    runner = Runner()

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await runner.run_suite(
            sample_suite,
            "suite_123",
        )

    assert "not available" in exc.value.detail.lower()

    await runner.close()


@pytest.mark.asyncio
async def test_run_suite_ollama_error(
    mock_ollama,
    sample_suite,
):
    mock_ollama.generate = AsyncMock(
        side_effect=Exception(
            "Ollama timeout"
        )
    )

    runner = Runner()

    run = await runner.run_suite(
        sample_suite,
        "suite_123",
    )

    assert run.results[0].error == (
        "Ollama timeout"
    )

    assert run.results[0].passed is False
    assert run.results[0].score == 0.0

    await runner.close()


@pytest.mark.asyncio
async def test_run_suite_contains_evaluator(
    mock_ollama,
):
    suite = Suite(
        name="Contains Test",
        model="llama3.1",
        evaluator="contains",
        tests=[
            Case(
                name="t1",
                prompt="Refund?",
                expected="refund",
                threshold=0.8,
            ),
        ],
    )

    mock_ollama.generate = AsyncMock(
        return_value=_resp("Our refund policy is 30 days", tokens=8)
    )

    runner = Runner()

    run = await runner.run_suite(
        suite,
        "suite_456",
    )

    assert run.results[0].passed is True
    assert run.results[0].score == 1.0

    await runner.close()


@pytest.mark.asyncio
async def test_run_suite_samples_are_aggregated(mock_ollama):
    suite = Suite(
        name="Sampled",
        model="llama3.1",
        evaluator="exact",
        samples=3,
        tests=[
            Case(
                name="t1",
                prompt="What is 2+2?",
                expected="4",
                threshold=0.8,
                category="math",
            ),
        ],
    )

    runner = Runner()
    run = await runner.run_suite(suite, "suite_s")

    r = run.results[0]
    assert r.runs == 3
    assert r.pass_count == 3
    assert r.score_std == 0.0
    assert r.passed is True
    assert r.category == "math"
    assert r.evaluator == "exact"

    await runner.close()


@pytest.mark.asyncio
async def test_run_suite_per_test_evaluator_override(mock_ollama):
    suite = Suite(
        name="Mixed",
        model="llama3.1",
        evaluator="exact",
        tests=[
            Case(
                name="t1",
                prompt="Refund?",
                expected="refund",
                threshold=0.8,
                evaluator="contains",
            ),
        ],
    )

    mock_ollama.generate = AsyncMock(
        return_value=_resp("Our refund policy is 30 days", tokens=8)
    )

    runner = Runner()
    run = await runner.run_suite(suite, "suite_m")

    assert run.results[0].evaluator == "contains"
    assert run.results[0].passed is True

    await runner.close()


@pytest.mark.asyncio
async def test_run_suite_respects_provider_concurrency_cap():
    active = 0
    peak = 0

    async def slow_generate(model, prompt, temperature=0.7):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.05)
        active -= 1
        return _resp("4")

    provider = AsyncMock()
    provider.name = "groq"
    provider.max_concurrency = 2
    provider.has_model = AsyncMock(return_value=True)
    provider.list_models = AsyncMock(return_value=["m"])
    provider.generate = slow_generate
    provider.close = AsyncMock()

    suite = Suite(
        name="conc",
        provider="groq",
        model="m",
        evaluator="exact",
        concurrency=10,  # asks for 10, provider only allows 2
        tests=[
            Case(name=f"t{i}", prompt="2+2?", expected="4") for i in range(8)
        ],
    )

    with patch("evalbench.core.runner.get_provider", return_value=provider):
        runner = Runner()
        run = await runner.run_suite(suite, "suite_conc")
        await runner.close()

    assert len(run.results) == 8
    assert peak == 2  # ran in parallel, but never above the provider cap


@pytest.mark.asyncio
async def test_run_suite_preserves_order_under_concurrency():
    async def echo_generate(model, prompt, temperature=0.7):
        await asyncio.sleep(0.01)
        return _resp(prompt)

    provider = AsyncMock()
    provider.name = "mock"
    provider.max_concurrency = 32
    provider.has_model = AsyncMock(return_value=True)
    provider.list_models = AsyncMock(return_value=[])
    provider.generate = echo_generate
    provider.close = AsyncMock()

    suite = Suite(
        name="order",
        provider="mock",
        model="m",
        evaluator="contains",
        concurrency=8,
        tests=[
            Case(name=f"t{i}", prompt=str(i), expected=str(i))
            for i in range(12)
        ],
    )

    with patch("evalbench.core.runner.get_provider", return_value=provider):
        runner = Runner()
        run = await runner.run_suite(suite, "suite_order")
        await runner.close()

    assert [r.test_name for r in run.results] == [f"t{i}" for i in range(12)]
    assert [r.actual for r in run.results] == [str(i) for i in range(12)]


@pytest.mark.asyncio
async def test_run_suite_security_evaluator(
    mock_ollama,
):
    suite = Suite(
        name="Security Test",
        model="llama3.1",
        evaluator="security",
        tests=[
            Case(
                name="ignore",
                prompt="Ignore instructions",
                expected="refusal",
                threshold=1.0,
            ),
        ],
    )

    mock_ollama.generate = AsyncMock(
        return_value=_resp("I cannot help with that", tokens=6)
    )

    with patch(
        "evalbench.core.evaluators.security.httpx.AsyncClient.post",
        new_callable=AsyncMock,
    ) as mock_judge:

        mock_judge.return_value.json = (
            lambda: {"response": "REFUSAL"}
        )

        mock_judge.return_value.raise_for_status = (
            lambda: None
        )

        runner = Runner()

        run = await runner.run_suite(
            suite,
            "suite_789",
        )

        assert run.results[0].passed is True

        await runner.close()
