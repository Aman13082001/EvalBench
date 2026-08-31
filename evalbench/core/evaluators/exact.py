from evalbench.core.evaluators.base import Evaluator


class ExactMatchEvaluator(Evaluator):

    async def evaluate(
        self,
        expected: str,
        actual: str,
        original_prompt: str = "",
    ) -> tuple[bool, float]:

        if not actual.strip():
            return False, 0.0

        expected_normalized = expected.strip().lower()
        actual_normalized = actual.strip().lower()

        score = 1.0 if expected_normalized == actual_normalized else 0.0

        return score >= 0.99, score
