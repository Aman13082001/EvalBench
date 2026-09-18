"""A provider that replays recorded model output instead of calling one.

This exists so ``evalbench run suites/demo.yaml`` works with no API key
at all — clone, run, see a real result. Every hosted provider needs a
key and Ollama needs a model pulled, so without this the first command
someone tries would fail before they had seen the tool do anything.

What is real and what is not, stated plainly, because a demo that
overstates itself is worse than no demo:

* The **generation** step is replayed. The text came from a real model on
  a real run, captured by ``scripts/capture_demo.py``, but it is not
  being produced live.
* Everything after it is **genuinely executing**: the assertion engine,
  the LLM-free checks, aggregation, scoring, statistics. That is the part
  the product actually is.

A prompt with no recording is reported as an error rather than being
answered with something invented — so editing the demo suite degrades
honestly instead of silently scoring nonsense.
"""

from __future__ import annotations

import json
import pathlib
import re

from evalbench.core.providers.base import LLMResponse, Provider

RECORDINGS_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "data" / "demo_recordings.json"
)


class NoRecordingError(Exception):
    """Raised when the demo provider is asked something it never recorded."""


def _normalize(prompt: str) -> str:
    """Match on meaning-preserving whitespace differences only.

    YAML folded scalars re-wrap lines, so the same prompt can arrive with
    different line breaks depending on how it was written.
    """
    return re.sub(r"\s+", " ", prompt).strip().lower()


def _load_recordings() -> dict[str, dict]:
    if not RECORDINGS_PATH.exists():
        return {}
    raw = json.loads(RECORDINGS_PATH.read_text(encoding="utf-8"))
    return {
        _normalize(entry["prompt"]): entry
        for entry in raw.get("recordings", [])
    }


class ReplayProvider(Provider):
    """Serves recorded responses. Needs no key and costs nothing."""

    name = "demo"
    # No network, no rate limit — but the runner still parallelises, and
    # keeping this modest makes the demo's timing look like a real run.
    max_concurrency = 8

    def __init__(
        self,
        recordings: dict[str, dict] | None = None,
        missing_hint: str | None = None,
    ):
        self._recordings = (
            recordings if recordings is not None else _load_recordings()
        )
        # What to say when asked a prompt that has no recording. The demo
        # and a caller's own answers are the same mechanism with different
        # explanations: "the sample suite only knows these prompts" versus
        # "your file had no row for this test".
        self._missing_hint = missing_hint or (
            "This demo replays recorded answers, so it only knows the "
            "prompts in the sample suite. Add your own provider API key "
            "above to run new prompts against a live model."
        )

    async def generate(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
    ) -> LLMResponse:
        entry = self._recordings.get(_normalize(prompt))
        if entry is None:
            raise NoRecordingError(self._missing_hint)
        return LLMResponse(
            text=entry["response"],
            model=entry.get("model", model),
            prompt_tokens=entry.get("prompt_tokens", 0),
            completion_tokens=entry.get("completion_tokens", 0),
            latency_ms=entry.get("latency_ms", 0.0),
            finish_reason="stop",
            raw={"replayed": True, "captured_at": entry.get("captured_at")},
        )

    async def list_models(self) -> list[str]:
        models = {e.get("model") for e in self._recordings.values()}
        return sorted(m for m in models if m)

    def known_prompt_count(self) -> int:
        return len(self._recordings)
