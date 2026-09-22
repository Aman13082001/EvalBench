"""What the image is allowed to carry.

The deployed instance calls Groq, Gemini and OpenRouter over HTTP. It
has no GPU, no Ollama and no local model — so an image that ships CUDA
is carrying eight gigabytes of driver for hardware that is not there,
and no free tier will host it.

Two things keep it light, and both are one careless edit from being
undone, so both are asserted here rather than remembered.
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
SEMANTIC = ROOT / "evalbench" / "core" / "evaluators" / "semantic.py"


class TestTheImageHasNoGPUDrivers:
    def test_torch_comes_from_the_cpu_index(self):
        """pip's default torch wheel bundles the NVIDIA CUDA libraries.
        The CPU index serves the same torch without them: ~8 GB smaller,
        identical behaviour on a machine with no GPU."""
        text = DOCKERFILE.read_text(encoding="utf-8")
        assert "download.pytorch.org/whl/cpu" in text, (
            "the image would pull the CUDA build of torch"
        )


class TestTheEmbeddingModelStaysAsleep:
    """Importing sentence_transformers imports torch, which costs a few
    hundred megabytes of resident memory before a single test has run.
    A free tier is 512 MB. So the import lives inside the function that
    needs it, and the process pays for it only when a semantic check
    actually runs."""

    def test_nothing_imports_sentence_transformers_at_module_level(self):
        tree = ast.parse(SEMANTIC.read_text(encoding="utf-8"))
        top = [
            n
            for n in tree.body
            if isinstance(n, (ast.Import, ast.ImportFrom))
        ]
        names = {
            (n.module or "") if isinstance(n, ast.ImportFrom) else a.name
            for n in top
            for a in n.names
        }
        offenders = sorted(n for n in names if "sentence_transformers" in n or n == "torch")
        assert not offenders, f"imported at module level: {offenders}"

    def test_the_model_is_still_reachable(self):
        """Lazy, not gone. The evaluator must still resolve."""
        from evalbench.core.evaluators import get_evaluator

        assert get_evaluator("semantic") is not None
