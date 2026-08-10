from evalbench.core.evaluators.base import Evaluator


class ContainsEvaluator(Evaluator):
    async def evaluate(self, expected: str, actual: str, original_prompt: str = "") -> tuple[bool, float]:
        if not actual.strip():
            return False, 0.0
        score = 1.0 if expected.strip().lower() in actual.strip().lower() else 0.0
        return score >= 0.99, score