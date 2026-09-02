import re

import httpx

from evalbench.config import settings
from evalbench.core.evaluators.base import Evaluator
from evalbench.core.providers.base import Provider


class LLMJudgeEvaluator(Evaluator):

    def __init__(
        self,
        judge_model: str = "llama3.1",
        base_url: str | None = None,
        provider: Provider | None = None,
    ):
        self.judge_model = judge_model
        self.base_url = base_url or settings.ollama_base_url
        # When set, the judge call is routed through the provider layer
        # (any hosted backend). When None, it hits Ollama directly.
        self._provider = provider

    async def _ask_judge(self, prompt: str) -> str:
        if self._provider is not None:
            resp = await self._provider.generate(
                model=self.judge_model,
                prompt=prompt,
                temperature=0.1,
            )
            return resp.text.strip()

        async with httpx.AsyncClient(
            timeout=settings.default_request_timeout
        ) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.judge_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
            )
            response.raise_for_status()
            return response.json().get("response", "").strip()

    def _build_prompt(
        self,
        expected: str,
        actual: str,
        original_prompt: str,
    ) -> str:
        return f"""You are an expert evaluation judge. Rate how well the ACTUAL ANSWER addresses the QUESTION compared to the EXPECTED ANSWER.

QUESTION: {original_prompt}

EXPECTED ANSWER: {expected}

ACTUAL ANSWER: {actual}

Rate on a scale of 1 to 5:

1 = Completely wrong or unrelated
2 = Partially correct, missing key info
3 = Mostly correct with notable issues
4 = Correct and complete, minor issues only
5 = Perfect or near-perfect match

Respond ONLY in this format:

SCORE: [number 1-5]

REASON: [one sentence explanation]"""

    def _parse_response(self, text: str) -> tuple[float, str]:
        score_match = re.search(
            r"SCORE:\s*(\d+(?:\.\d+)?)",
            text,
            re.IGNORECASE,
        )

        if score_match:
            score = float(score_match.group(1))
            score = max(1.0, min(5.0, score))
        else:
            fallback = re.search(
                r"\b([1-5](?:\.\d+)?)\b",
                text,
            )
            score = float(fallback.group(1)) if fallback else 3.0

        reason_match = re.search(
            r"REASON:\s*(.+?)(?:\n|$)",
            text,
            re.IGNORECASE | re.DOTALL,
        )

        reason = (
            reason_match.group(1).strip()
            if reason_match
            else "No reason provided"
        )

        # Normalize 1-5 score to 0.0-1.0.
        # 4/5 = 0.8, which matches EvalBench scoring.
        normalized = score / 5.0

        return round(normalized, 4), reason

    async def evaluate(
        self,
        expected: str,
        actual: str,
        original_prompt: str = "",
        threshold: float | None = None,
    ) -> tuple[bool, float]:

        cutoff = 0.6 if threshold is None else threshold

        if not actual.strip():
            return False, 0.0

        prompt = self._build_prompt(
            expected,
            actual,
            original_prompt,
        )

        try:
            judge_output = await self._ask_judge(prompt)
            score, _reason = self._parse_response(judge_output)
            passed = score >= cutoff
            return passed, score

        except Exception:
            from evalbench.core.evaluators.semantic import (
                SemanticSimilarityEvaluator,
            )

            fallback = SemanticSimilarityEvaluator()

            return await fallback.evaluate(
                expected,
                actual,
                original_prompt,
                threshold,
            )
