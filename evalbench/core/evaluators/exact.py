from evalbench.core.evaluators.base import Evaluator


class ExactMatchEvaluator(Evaluator):
    async def evaluate(self, expected: str, actual: str, original_prompt: str = "") -> tuple[bool, float]:
        if not actual.strip():
            return False, 0.0
        score = 1.0 if expected.strip() == actual.strip() else 0.0
        return score >= 0.99, score