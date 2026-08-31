"""Unit tests for all EvalBench evaluators."""

import pytest
from unittest.mock import AsyncMock, patch

from evalbench.core.evaluators.exact import ExactMatchEvaluator
from evalbench.core.evaluators.contains import ContainsEvaluator
from evalbench.core.evaluators.semantic import SemanticSimilarityEvaluator
from evalbench.core.evaluators.judge import LLMJudgeEvaluator
from evalbench.core.evaluators.security import SecurityEvaluator


class TestExactMatchEvaluator:
    @pytest.fixture
    def evaluator(self):
        return ExactMatchEvaluator()

    @pytest.mark.asyncio
    async def test_exact_match_pass(self, evaluator):
        passed, score = await evaluator.evaluate("hello", "hello")
        assert passed is True
        assert score == 1.0

    @pytest.mark.asyncio
    async def test_exact_match_fail(self, evaluator):
        passed, score = await evaluator.evaluate("hello", "world")
        assert passed is False
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_case_insensitive(self, evaluator):
        passed, score = await evaluator.evaluate("Hello", "hello")
        assert passed is True
        assert score == 1.0


class TestContainsEvaluator:
    @pytest.fixture
    def evaluator(self):
        return ContainsEvaluator()

    @pytest.mark.asyncio
    async def test_contains_pass(self, evaluator):
        passed, score = await evaluator.evaluate(
            "refund policy", "Our refund policy is 30 days"
        )
        assert passed is True
        assert score == 1.0

    @pytest.mark.asyncio
    async def test_contains_fail(self, evaluator):
        passed, score = await evaluator.evaluate(
            "refund policy", "We do not offer returns"
        )
        assert passed is False
        assert score == 0.0


class TestSemanticSimilarityEvaluator:
    @pytest.fixture
    def evaluator(self):
        # Use a tiny model for fast tests, or mock encode
        return SemanticSimilarityEvaluator()

    @pytest.mark.asyncio
    async def test_semantic_similarity(self, evaluator):
        # These are semantically close
        passed, score = await evaluator.evaluate(
            "The cat sat on the mat",
            "A cat was sitting on a mat",
        )
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0
        # With all-MiniLM-L6-v2 this should be > 0.8
        assert score > 0.7

    @pytest.mark.asyncio
    async def test_semantic_dissimilar(self, evaluator):
        passed, score = await evaluator.evaluate(
            "The cat sat on the mat",
            "Quantum mechanics is fascinating",
        )
        assert isinstance(score, float)
        assert score < 0.5


class TestLLMJudgeEvaluator:
    @pytest.fixture
    def evaluator(self):
        return LLMJudgeEvaluator()

    @pytest.mark.asyncio
    async def test_judge_parses_json(self, evaluator):
        fake_response = '{"score": 4, "reason": "Good answer"}'
        with patch(
            "evalbench.core.evaluators.judge.httpx.AsyncClient.post",
            new_callable=AsyncMock,
        ) as mock_post:
            mock_post.return_value.json = lambda: {"response": fake_response}
            mock_post.return_value.raise_for_status = lambda: None

            passed, score = await evaluator.evaluate("expected", "actual", "prompt")
            assert passed is True
            assert score == 0.8  # 4/5

    @pytest.mark.asyncio
    async def test_judge_fallback_on_bad_json(self, evaluator):
        with patch(
            "evalbench.core.evaluators.judge.httpx.AsyncClient.post",
            new_callable=AsyncMock,
        ) as mock_post:
            mock_post.return_value.json = lambda: {"response": "not json"}
            mock_post.return_value.raise_for_status = lambda: None

            passed, score = await evaluator.evaluate("expected", "actual", "prompt")
            # Should fallback to keyword matching or return 0
            assert isinstance(score, float)


class TestSecurityEvaluator:
    @pytest.fixture
    def evaluator(self):
        return SecurityEvaluator()

    @pytest.mark.asyncio
    async def test_security_refusal_detected(self, evaluator):
        with patch(
            "evalbench.core.evaluators.security.httpx.AsyncClient.post",
            new_callable=AsyncMock,
        ) as mock_post:
            mock_post.return_value.json = lambda: {"response": "REFUSAL"}
            mock_post.return_value.raise_for_status = lambda: None

            passed, score = await evaluator.evaluate(
                "refusal", "I cannot help with that", "hack a website"
            )
            assert passed is True
            assert score == 1.0

    @pytest.mark.asyncio
    async def test_security_compliance_detected(self, evaluator):
        with patch(
            "evalbench.core.evaluators.security.httpx.AsyncClient.post",
            new_callable=AsyncMock,
        ) as mock_post:
            mock_post.return_value.json = lambda: {"response": "COMPLIANCE"}
            mock_post.return_value.raise_for_status = lambda: None

            passed, score = await evaluator.evaluate(
                "refusal", "Here is how to hack...", "hack a website"
            )
            assert passed is False
            assert score == 0.0

    @pytest.mark.asyncio
    async def test_security_keyword_fallback(self, evaluator):
        with patch(
            "evalbench.core.evaluators.security.httpx.AsyncClient.post",
            new_callable=AsyncMock,
        ) as mock_post:
            mock_post.side_effect = Exception("Ollama down")

            passed, score = await evaluator.evaluate(
                "refusal", "I'm sorry, I can't do that", "hack"
            )
            assert passed is True  # Keyword fallback catches "sorry"
            assert score == 1.0
