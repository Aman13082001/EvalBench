"""The no-key demo must actually work, and must not overstate itself.

A visitor with no provider account can run `suites/demo.yaml` because the
model's answers are replayed from a recorded run. Three things can break
that silently:

* a prompt is edited in the suite but the recordings are not re-captured,
  so that test errors for every visitor;
* the copy of the YAML embedded in the web app drifts from the real file;
* the replay provider starts inventing answers for prompts it never saw,
  which would turn an honest demo into a fabricated one.
"""

import json
import pathlib
import re

import pytest
import yaml

from evalbench.core.providers import available_providers, get_provider
from evalbench.core.providers.replay import (
    NoRecordingError,
    ReplayProvider,
    _normalize,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "suites" / "demo.yaml"
RECORDINGS = ROOT / "evalbench" / "data" / "demo_recordings.json"


@pytest.fixture(scope="module")
def suite() -> dict:
    return yaml.safe_load(SUITE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def recorded() -> dict:
    return json.loads(RECORDINGS.read_text(encoding="utf-8"))


class TestRegistration:
    def test_demo_provider_is_available(self):
        assert "demo" in available_providers()

    def test_it_needs_no_credentials(self):
        """Every hosted provider raises without a key. This one must not,
        or the whole point is lost."""
        assert get_provider("demo") is not None


class TestRecordings:
    def test_recordings_file_ships(self):
        assert RECORDINGS.exists(), (
            "demo_recordings.json is missing — run "
            "`python scripts/capture_demo.py`"
        )

    def test_every_suite_prompt_has_a_recording(self, suite, recorded):
        known = {_normalize(e["prompt"]) for e in recorded["recordings"]}
        missing = [
            t["name"]
            for t in suite["tests"]
            if _normalize(t["prompt"]) not in known
        ]
        assert not missing, (
            f"no recorded answer for {missing} — the demo would report "
            f"these as errors. Re-run scripts/capture_demo.py."
        )

    def test_judge_calls_were_captured_too(self, recorded):
        """llm-rubric / faithfulness / context-recall each make their own
        graded call. Capturing only the suite's prompts would leave those
        unanswered."""
        prompts = " ".join(e["prompt"] for e in recorded["recordings"]).lower()
        assert "rubric" in prompts
        assert "grounded" in prompts or "atomic" in prompts

    def test_recorded_answers_are_not_empty(self, recorded):
        for e in recorded["recordings"]:
            assert e["response"].strip(), f"empty recording for {e['prompt'][:40]}"


class TestHonesty:
    @pytest.mark.asyncio
    async def test_unknown_prompt_errors_rather_than_inventing(self):
        """The failure mode that would matter: quietly answering a prompt
        it never recorded would make the demo fabricate results."""
        p = ReplayProvider(recordings={})
        with pytest.raises(NoRecordingError) as exc:
            await p.generate(model="m", prompt="something never recorded")
        # and the message must tell the visitor what to do about it
        assert "api key" in str(exc.value).lower()

    @pytest.mark.asyncio
    async def test_replays_the_recorded_text_verbatim(self):
        p = ReplayProvider(
            recordings={
                _normalize("Hello?"): {
                    "prompt": "Hello?",
                    "response": "recorded answer",
                    "model": "openai/gpt-oss-20b",
                    "prompt_tokens": 3,
                    "completion_tokens": 4,
                    "latency_ms": 12.5,
                }
            }
        )
        r = await p.generate(model="ignored", prompt="hello?")
        assert r.text == "recorded answer"
        assert r.model == "openai/gpt-oss-20b"
        assert r.raw["replayed"] is True, (
            "a replayed response must be labelled as such"
        )

    @pytest.mark.asyncio
    async def test_whitespace_differences_still_match(self):
        """YAML folded scalars re-wrap prompts; a line break must not
        turn a recorded prompt into an unknown one."""
        p = ReplayProvider(
            recordings={
                _normalize("one two three"): {
                    "prompt": "one two three",
                    "response": "ok",
                }
            }
        )
        r = await p.generate(model="m", prompt="  One   two\n  three  ")
        assert r.text == "ok"


def test_web_copy_of_the_suite_matches_the_real_file(suite):
    """web/lib/presets.ts embeds demo.yaml verbatim so the editor shows
    what actually ran. If they drift, the visitor edits one thing and
    runs another."""
    presets = ROOT / "web" / "lib" / "presets.ts"
    if not presets.exists():
        pytest.skip("web app not present")
    src = presets.read_text(encoding="utf-8")
    m = re.search(r"export const DEMO_SUITE = (\".*?\");", src, re.S)
    assert m, "DEMO_SUITE not found in presets.ts"
    embedded = json.loads(m.group(1))
    assert embedded == SUITE_PATH.read_text(encoding="utf-8"), (
        "web/lib/presets.ts DEMO_SUITE has drifted from suites/demo.yaml"
    )
