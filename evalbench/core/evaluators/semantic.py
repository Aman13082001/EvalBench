from sentence_transformers import SentenceTransformer, util

from evalbench.core.evaluators.base import Evaluator

DEFAULT_THRESHOLD = 0.8

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


class SemanticSimilarityEvaluator(Evaluator):
    """Score a response by cosine similarity of sentence embeddings."""

    async def evaluate(
        self,
        expected: str,
        actual: str,
        original_prompt: str = "",
        threshold: float | None = None,
    ) -> tuple[bool, float]:
        if not actual.strip():
            return False, 0.0

        cutoff = DEFAULT_THRESHOLD if threshold is None else threshold

        model = _get_model()
        emb1 = model.encode(expected, convert_to_tensor=True)
        emb2 = model.encode(actual, convert_to_tensor=True)
        score = float(util.pytorch_cos_sim(emb1, emb2)[0][0])

        return score >= cutoff, score
