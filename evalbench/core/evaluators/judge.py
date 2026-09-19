import json
import re

import httpx

from evalbench.config import settings
from evalbench.core.evaluators.base import Evaluator
from evalbench.core.providers.base import Provider


def parse_judge_output(text: str) -> tuple[float, str]:
    """Parse a judge reply into (score_0_to_1, reason).

    Tries JSON first (``{"score": 1-5, "reason": "..."}``), then falls back
    to scraping ``SCORE:`` / ``REASON:`` lines, then to a bare digit.

    Raises ``ValueError`` when there is no verdict to parse — an empty
    reply, or text with no score in it. It used to invent 3/5 for those,
    and 3/5 is 0.6, the default pass cutoff. The judge-variance study
    caught a judge model returning nothing on 9 of 300 calls, every one
    a refusal-category prompt: the judge would not engage with a grading
    prompt that quotes a harmful request, and the answer passed.
    """
    raw = text.strip()
    if not raw:
        raise ValueError("the judge returned an empty reply")

    fence = re.search(r"```(?:json)?\s*(.+?)```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    brace = re.search(r"\{.*\}", raw, re.DOTALL)
    if brace:
        try:
            obj = json.loads(brace.group(0))
            if "score" not in obj and "rating" not in obj:
                raise KeyError("score")
            score = float(obj.get("score", obj.get("rating")))
            reason = str(obj.get("reason", obj.get("explanation", ""))).strip()
            # Every prompt asks for 1-5. Only a non-integer strictly
            # between 0 and 1 is a fraction the model returned anyway;
            # an integer is on the scale it was asked for. Treating any
            # score <= 1 as "already normalised" made a 1 — the lowest
            # verdict — parse as 1.0, the highest, so an answer the judge
            # said "violates the rubric" passed with a perfect score.
            if 0.0 < score < 1.0 and not score.is_integer():
                return round(score, 4), reason or "n/a"
            return round(max(1.0, min(5.0, score)) / 5.0, 4), reason or "n/a"
        except (json.JSONDecodeError, TypeError, ValueError, KeyError):
            pass

    m = re.search(r"SCORE:\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if m:
        score = max(1.0, min(5.0, float(m.group(1))))
    else:
        d = re.search(r"\b([1-5](?:\.\d+)?)\b", text)
        if not d:
            raise ValueError(
                f"no score in the judge's reply: {text.strip()[:120]!r}"
            )
        score = float(d.group(1))

    r = re.search(r"REASON:\s*(.+?)(?:\n|$)", text, re.IGNORECASE | re.DOTALL)
    reason = r.group(1).strip() if r else "No reason provided"
    return round(score / 5.0, 4), reason


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

Respond ONLY with a JSON object:
{{"score": <1-5>, "reason": "<one sentence>"}}"""

    def _parse_response(self, text: str) -> tuple[float, str]:
        # Kept for back-compat; delegates to the shared parser.
        return parse_judge_output(text)

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
            score, _reason = parse_judge_output(judge_output)
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
