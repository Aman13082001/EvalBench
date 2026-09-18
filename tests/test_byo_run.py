"""A run on supplied answers, end to end: API, job, runner, summary.

Generation is replayed from the caller's file; only the checks that ask
an LLM to grade need a model, and only the grading counts against the
daily cap. The run document says `provider: answers`, so everything
downstream — the run list, the results page, the resolution estimate —
knows these answers came from the caller and not from a call.
"""

from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from evalbench.api.deps import get_current_user
from evalbench.api.main import app

SUITE_ID = "507f1f77bcf86cd799439011"
RUN_ID = "507f191e810c19729de860ea"
ALICE = {"username": "alice", "role": "user", "_id": "a"}

DETERMINISTIC = {
    "_id": ObjectId(SUITE_ID), "name": "S", "provider": "groq",
    "model": "openai/gpt-oss-20b", "evaluator": "exact", "created_by": "alice",
    "samples": 1,
    "tests": [
        {"name": "capital", "prompt": "Capital of France?", "expected": "Paris"},
        {"name": "sum", "prompt": "2+2?", "expected": "4"},
    ],
}
JUDGED = {
    **DETERMINISTIC,
    "tests": [
        {"name": "poem", "prompt": "A haiku about rain.",
         "assert": [{"type": "llm-rubric", "value": "It is a haiku."}]},
    ],
}
ANSWERS = [
    {"test_name": "capital", "response": "Paris"},
    {"test_name": "sum", "response": "4"},
]


@pytest.fixture
def as_alice(mock_db):
    app.dependency_overrides[get_current_user] = lambda: ALICE
    with TestClient(app) as c:
        yield c
    from tests.conftest import override_get_current_user

    app.dependency_overrides[get_current_user] = override_get_current_user


def _accept(mock_db, suite):
    mock_db.suites.find_one.return_value = dict(suite)
    mock_db.test_runs.insert_one.return_value.inserted_id = ObjectId(RUN_ID)


class TestSubmitting:
    def test_a_deterministic_suite_needs_no_key_and_no_cap(self, as_alice, mock_db):
        """String checks on supplied answers touch no model. It must not
        spend the daily cap, and it must not be refused for lacking a key
        the run has no use for."""
        _accept(mock_db, DETERMINISTIC)
        mock_db.test_runs.count_documents.return_value = 10_000  # cap exhausted
        with patch("evalbench.api.routes.submit_run"):
            r = as_alice.post(f"/suites/{SUITE_ID}/run", json={"answers": ANSWERS})
        assert r.status_code == 202, r.text
        doc = mock_db.test_runs.insert_one.call_args[0][0]
        assert doc["provider"] == "answers"
        assert doc["used_server_key"] is False
        assert [a["test_name"] for a in doc["answers"]] == ["capital", "sum"]

    def test_a_label_names_the_answers(self, as_alice, mock_db):
        _accept(mock_db, DETERMINISTIC)
        with patch("evalbench.api.routes.submit_run"):
            as_alice.post(
                f"/suites/{SUITE_ID}/run",
                json={"answers": ANSWERS, "model": "my-model-v2"},
            )
        assert mock_db.test_runs.insert_one.call_args[0][0]["model"] == "my-model-v2"

    def test_without_a_label_it_says_what_it_is(self, as_alice, mock_db):
        _accept(mock_db, DETERMINISTIC)
        with patch("evalbench.api.routes.submit_run"):
            as_alice.post(f"/suites/{SUITE_ID}/run", json={"answers": ANSWERS})
        assert mock_db.test_runs.insert_one.call_args[0][0]["model"] == "your answers"

    def test_a_judged_suite_spends_the_cap_for_the_grader(self, as_alice, mock_db):
        """The answers are free; the rubric is a model call on our key."""
        _accept(mock_db, JUDGED)
        with patch("evalbench.api.routes.submit_run"), patch(
            "evalbench.api.routes.configured_providers", return_value=["groq", "answers"]
        ):
            r = as_alice.post(
                f"/suites/{SUITE_ID}/run",
                json={"answers": [{"test_name": "poem", "response": "rain / roof / hush"}]},
            )
        assert r.status_code == 202, r.text
        doc = mock_db.test_runs.insert_one.call_args[0][0]
        assert doc["used_server_key"] is True
        assert doc["judge_provider"] == "groq"

    def test_a_judged_suite_is_refused_when_no_grader_is_reachable(self, as_alice, mock_db):
        _accept(mock_db, JUDGED)
        with patch(
            "evalbench.api.routes.configured_providers", return_value=["ollama", "answers"]
        ):
            r = as_alice.post(
                f"/suites/{SUITE_ID}/run",
                json={"answers": [{"test_name": "poem", "response": "x"}]},
            )
        assert r.status_code == 400
        assert "grade" in r.json()["detail"].lower()

    def test_the_caller_can_pick_the_grader(self, as_alice, mock_db):
        _accept(mock_db, JUDGED)
        with patch("evalbench.api.routes.submit_run"):
            r = as_alice.post(
                f"/suites/{SUITE_ID}/run",
                json={
                    "answers": [{"test_name": "poem", "response": "x"}],
                    "judge_provider": "openai", "judge_model": "gpt-4o-mini",
                    "provider_key": "sk-mine",
                },
            )
        assert r.status_code == 202, r.text
        doc = mock_db.test_runs.insert_one.call_args[0][0]
        assert doc["judge_provider"] == "openai"
        assert doc["judge_model"] == "gpt-4o-mini"
        assert doc["used_server_key"] is False

    def test_answers_that_match_nothing_are_refused_with_the_reason(self, as_alice, mock_db):
        _accept(mock_db, DETERMINISTIC)
        r = as_alice.post(
            f"/suites/{SUITE_ID}/run",
            json={"answers": [{"test_name": "capitol", "response": "Paris"}]},
        )
        assert r.status_code == 400
        assert "capitol" in r.json()["detail"]
        mock_db.test_runs.insert_one.assert_not_called()

    def test_a_malformed_row_is_refused_with_the_reason(self, as_alice, mock_db):
        _accept(mock_db, DETERMINISTIC)
        r = as_alice.post(
            f"/suites/{SUITE_ID}/run",
            json={"answers": [{"test_name": "capital"}]},
        )
        assert r.status_code == 400
        assert "response" in r.json()["detail"]


class TestTheJobReplaysThem:
    @pytest.mark.asyncio
    async def test_the_runner_gets_the_answers_and_a_real_grader(self, mock_db):
        from evalbench import jobs

        mock_db.suites.find_one.return_value = dict(JUDGED)
        mock_db.test_runs.find_one.return_value = {
            "_id": ObjectId(RUN_ID), "provider": "answers", "model": "v2",
            "judge_provider": "groq", "judge_model": "openai/gpt-oss-20b",
            "answers": [{"test_name": "poem", "prompt": None, "response": "rain / roof / hush"}],
        }
        seen = {}

        class _Runner:
            def __init__(self, provider_key=None, answers=None):
                seen["answers"] = answers

            async def run_suite(self, suite, suite_id, progress_cb=None):
                seen["provider"] = suite.provider
                seen["judge"] = (suite.judge_provider, suite.judge_model)
                seen["model"] = suite.model
                raise RuntimeError("stop")

            async def close(self):
                pass

        with patch.object(jobs, "db", mock_db), patch.object(jobs, "TestRunner", _Runner):
            await jobs.execute_run_job(RUN_ID, SUITE_ID)

        assert seen["provider"] == "answers"
        assert seen["judge"] == ("groq", "openai/gpt-oss-20b")
        assert seen["model"] == "v2"
        # keyed the way the replay provider looks prompts up
        from evalbench.core.providers.replay import _normalize

        assert _normalize("A haiku about rain.") in seen["answers"]

    @pytest.mark.asyncio
    async def test_the_runner_serves_them_through_the_replay_provider(self):
        from evalbench.core.providers.replay import _normalize
        from evalbench.core.runner import TestRunner

        r = TestRunner(answers={_normalize("2+2?"): {"prompt": "2+2?", "response": "4"}})
        p = r._make_provider("answers")
        out = await p.generate("v2", "2+2?")
        assert out.text == "4"
        await r.close()


class TestTheSummaryKnows:
    def test_latency_is_not_reported_for_supplied_answers(self):
        """There was no call, so there is no time-to-answer. Reporting the
        replay's 0 ms as the model's speed would be a fabrication."""
        from evalbench.api.summary import summarize_run

        s = summarize_run({
            "provider": "answers",
            "results": [{"test_name": "a", "passed": True, "score": 1.0, "latency_ms": 0}],
        })
        assert s["avg_latency_ms"] is None
        assert s["pass_rate"] == 1.0


class TestAMissingAnswerSaysSo:
    @pytest.mark.asyncio
    async def test_the_error_names_the_cause_not_the_demo(self):
        """The demo and supplied answers share a mechanism; they must not
        share an explanation. "Add your own API key" is wrong advice for
        someone whose file simply lacked a row."""
        from evalbench.core.providers.replay import NoRecordingError
        from evalbench.core.runner import TestRunner

        r = TestRunner(answers={})
        p = r._make_provider("answers")
        with pytest.raises(NoRecordingError) as e:
            await p.generate("v2", "an unanswered prompt")
        assert "No answer was supplied" in str(e.value)
        assert "demo" not in str(e.value).lower()
        await r.close()
