from evalbench.core.evaluators.contains import ContainsEvaluator
from evalbench.core.evaluators.exact import ExactMatchEvaluator
from evalbench.core.evaluators.judge import LLMJudgeEvaluator
from evalbench.core.evaluators.security import SecurityEvaluator
from evalbench.core.evaluators.semantic import SemanticSimilarityEvaluator

EVALUATORS = {
    "exact": ExactMatchEvaluator,
    "contains": ContainsEvaluator,
    "semantic": SemanticSimilarityEvaluator,
    "judge": LLMJudgeEvaluator,
    "security": SecurityEvaluator,
}


def get_evaluator(name: str):
    if name not in EVALUATORS:
        raise ValueError(
            f"Unknown evaluator: {name}. Available: {list(EVALUATORS.keys())}"
        )
    return EVALUATORS[name]()
