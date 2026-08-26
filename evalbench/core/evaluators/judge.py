import re

import httpx

from evalbench.core.evaluators.base import Evaluator


class LLMJudgeEvaluator(Evaluator):

    def __init__(
        self,
        judge_model: str = "llama3.1",
        base_url: str = "http://localhost:11434",
    ):
        self.judge_model = judge_model
        self.base_url = base_url

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
    ) -> tuple[bool, float]:

        if not actual.strip():
            return False, 0.0

        prompt = self._build_prompt(
            expected,
            actual,
            original_prompt,
        )

        payload = {
            "model": self.judge_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
            },
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                )

                response.raise_for_status()

                data = response.json()
                judge_output = data.get("response", "").strip()

                score, reason = self._parse_response(judge_output)

                passed = score >= 0.6

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
                )