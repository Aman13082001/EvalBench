import asyncio

from evalbench.core.evaluators.base import Evaluator

DEFAULT_THRESHOLD = 0.8

_model = None
_util = None


def _get_model():
    """The embedding model, loaded the first time something needs it.

    The import sits in here rather than at the top of the file because
    importing sentence_transformers imports torch, and torch costs a few
    hundred megabytes of resident memory the moment it is imported —
    before a single test has run. A free-tier host gives the whole
    process 512 MB, and most runs never reach a semantic check. So the
    process pays for this when it actually scores one, and not before.
    """
    global _model, _util
    if _model is None:
        from sentence_transformers import SentenceTransformer, util

        _util = util
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def _score_sync(expected: str, actual: str) -> float:
    model = _get_model()
    emb1 = model.encode(expected, convert_to_tensor=True)
    emb2 = model.encode(actual, convert_to_tensor=True)
    return float(_util.pytorch_cos_sim(emb1, emb2)[0][0])


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

        # Model load + encode are heavy and synchronous; run them off the
        # event loop so concurrent tests and /status polls stay responsive.
        score = await asyncio.to_thread(_score_sync, expected, actual)

        return score >= cutoff, score
