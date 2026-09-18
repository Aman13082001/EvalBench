"""A run against an OpenAI-compatible endpoint the caller names.

`provider: custom` plus a `base_url`. The key is optional — a personal
vLLM behind a tunnel has none — and the server's own keys are never
involved, so nothing here counts against the daily cap. The URL is
checked at submission (a 400 with the reason, not a dead run) and
checked again, harder, at connect time (see test_endpoint_url.py).
"""

import socket
from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from evalbench.api.deps import get_current_user
from evalbench.api.main import app

SUITE_ID = "507f1f77bcf86cd799439011"
RUN_ID = "507f191e810c19729de860ea"
ALICE = {"username": "alice", "role": "user", "_id": "a"}
PUBLIC = "93.184.216.34"

SUITE = {
    "_id": ObjectId(SUITE_ID), "name": "S", "provider": "groq",
    "model": "openai/gpt-oss-20b", "evaluator": "exact", "created_by": "alice",
    "samples": 1, "tests": [{"name": "t", "prompt": "p", "expected": "e"}],
}


def _resolver(*ips: str):
    def fake(host, port, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]

    return fake


@pytest.fixture
def as_alice(mock_db):
    app.dependency_overrides[get_current_user] = lambda: ALICE
    mock_db.suites.find_one.return_value = dict(SUITE)
    mock_db.test_runs.insert_one.return_value.inserted_id = ObjectId(RUN_ID)
    with TestClient(app) as c:
        yield c
    from tests.conftest import override_get_current_user

    app.dependency_overrides[get_current_user] = override_get_current_user


class TestSubmitting:
    def test_a_public_endpoint_is_accepted_with_no_key_and_no_cap(self, as_alice, mock_db):
        mock_db.test_runs.count_documents.return_value = 10_000  # cap exhausted
        with patch("evalbench.api.routes.submit_run") as submit, patch(
            "socket.getaddrinfo", _resolver(PUBLIC)
        ):
            r = as_alice.post(
                f"/suites/{SUITE_ID}/run",
                json={"provider": "custom", "base_url": "https://llm.example.com/v1/",
                      "model": "my-7b"},
            )
        assert r.status_code == 202, r.text
        doc = mock_db.test_runs.insert_one.call_args[0][0]
        assert doc["provider"] == "custom"
        assert doc["base_url"] == "https://llm.example.com/v1"
        assert doc["model"] == "my-7b"
        assert doc["used_server_key"] is False
        # No key was given; none travels.
        assert submit.call_args[0][3] is None

    def test_the_callers_key_travels_the_same_road_as_before(self, as_alice, mock_db):
        with patch("evalbench.api.routes.submit_run") as submit, patch(
            "socket.getaddrinfo", _resolver(PUBLIC)
        ):
            as_alice.post(
                f"/suites/{SUITE_ID}/run",
                json={"provider": "custom", "base_url": "https://llm.example.com/v1",
                      "model": "m", "provider_key": "theirs"},
            )
        assert submit.call_args[0][3] == "theirs"
        doc = mock_db.test_runs.insert_one.call_args[0][0]
        assert "theirs" not in str(doc)

    def test_an_internal_address_is_refused_with_the_reason(self, as_alice, mock_db):
        r = as_alice.post(
            f"/suites/{SUITE_ID}/run",
            json={"provider": "custom", "base_url": "https://169.254.169.254/v1", "model": "m"},
        )
        assert r.status_code == 400
        assert "not a public" in r.json()["detail"]
        mock_db.test_runs.insert_one.assert_not_called()

    def test_a_name_that_resolves_inside_is_refused(self, as_alice, mock_db):
        with patch("socket.getaddrinfo", _resolver("10.0.0.7")):
            r = as_alice.post(
                f"/suites/{SUITE_ID}/run",
                json={"provider": "custom", "base_url": "https://redis.example.com/v1",
                      "model": "m"},
            )
        assert r.status_code == 400
        mock_db.test_runs.insert_one.assert_not_called()

    def test_http_is_refused_by_default(self, as_alice, mock_db):
        r = as_alice.post(
            f"/suites/{SUITE_ID}/run",
            json={"provider": "custom", "base_url": "http://llm.example.com/v1", "model": "m"},
        )
        assert r.status_code == 400
        assert "https" in r.json()["detail"]

    def test_custom_needs_a_url(self, as_alice, mock_db):
        r = as_alice.post(
            f"/suites/{SUITE_ID}/run", json={"provider": "custom", "model": "m"}
        )
        assert r.status_code == 400
        assert "base_url" in r.json()["detail"]

    def test_custom_needs_a_model_name(self, as_alice, mock_db):
        """There is no list to pick from; the suite's default names a
        Groq model that means nothing to a stranger's endpoint."""
        with patch("socket.getaddrinfo", _resolver(PUBLIC)):
            r = as_alice.post(
                f"/suites/{SUITE_ID}/run",
                json={"provider": "custom", "base_url": "https://llm.example.com/v1"},
            )
        assert r.status_code == 400
        assert "model" in r.json()["detail"]

    def test_a_url_with_another_provider_is_a_mistake_not_ignored(self, as_alice, mock_db):
        r = as_alice.post(
            f"/suites/{SUITE_ID}/run",
            json={"provider": "groq", "base_url": "https://llm.example.com/v1", "model": "m"},
        )
        assert r.status_code == 400
        assert "custom" in r.json()["detail"]

    def test_the_grader_for_supplied_answers_can_be_a_custom_endpoint(self, as_alice, mock_db):
        judged = {
            **SUITE,
            "tests": [{"name": "poem", "prompt": "haiku",
                       "assert": [{"type": "llm-rubric", "value": "is a haiku"}]}],
        }
        mock_db.suites.find_one.return_value = judged
        with patch("evalbench.api.routes.submit_run"), patch(
            "socket.getaddrinfo", _resolver(PUBLIC)
        ):
            r = as_alice.post(
                f"/suites/{SUITE_ID}/run",
                json={"answers": [{"test_name": "poem", "response": "x"}],
                      "judge_provider": "custom", "judge_model": "grader-7b",
                      "base_url": "https://llm.example.com/v1"},
            )
        assert r.status_code == 202, r.text
        doc = mock_db.test_runs.insert_one.call_args[0][0]
        assert doc["judge_provider"] == "custom"
        assert doc["base_url"] == "https://llm.example.com/v1"
        assert doc["used_server_key"] is False


class TestTheProvidersList:
    def test_custom_is_offered_and_says_it_needs_a_url(self, as_alice):
        r = as_alice.get("/suites/providers")
        custom = next(p for p in r.json() if p["id"] == "custom")
        assert custom["needs_url"] is True
        assert custom["server_key"] is False
        # The key is optional, so the picker must not demand one.
        assert custom["needs_key"] is False


class TestTheJob:
    @pytest.mark.asyncio
    async def test_the_runner_is_told_the_url(self, mock_db):
        from evalbench import jobs

        mock_db.suites.find_one.return_value = dict(SUITE)
        mock_db.test_runs.find_one.return_value = {
            "_id": ObjectId(RUN_ID), "provider": "custom", "model": "my-7b",
            "base_url": "https://llm.example.com/v1",
        }
        seen = {}

        class _Runner:
            def __init__(self, provider_key=None, answers=None, base_url=None):
                seen["key"] = provider_key
                seen["base_url"] = base_url

            async def run_suite(self, suite, suite_id, progress_cb=None):
                seen["provider"] = suite.provider
                raise RuntimeError("stop")

            async def close(self):
                pass

        with patch.object(jobs, "db", mock_db), patch.object(jobs, "TestRunner", _Runner):
            await jobs.execute_run_job(RUN_ID, SUITE_ID, provider_key="theirs")

        assert seen == {"key": "theirs", "base_url": "https://llm.example.com/v1",
                        "provider": "custom"}

    def test_the_runner_builds_a_guarded_provider_for_it(self):
        from evalbench.core.endpoint import GuardedTransport
        from evalbench.core.runner import TestRunner

        with patch("socket.getaddrinfo", _resolver(PUBLIC)):
            r = TestRunner(base_url="https://llm.example.com/v1")
            p = r._make_provider("custom")
        assert p.base_url == "https://llm.example.com/v1"
        assert isinstance(p._client._transport, GuardedTransport)

    def test_the_runner_never_hands_custom_a_server_key(self, monkeypatch):
        from evalbench.core.runner import TestRunner

        monkeypatch.setenv("GROQ_API_KEY", "gsk_ours")
        with patch("socket.getaddrinfo", _resolver(PUBLIC)):
            p = TestRunner(base_url="https://llm.example.com/v1")._make_provider("custom")
        assert "authorization" not in {k.lower() for k in p._client.headers}


class TestTheSummaryKnows:
    def test_where_a_custom_run_went_is_part_of_the_result(self):
        """The same model name means different things on different
        servers. A report on "my-7b" that does not say whose my-7b is
        not a report."""
        from evalbench.api.summary import summarize_run

        s = summarize_run({
            "provider": "custom", "model": "my-7b",
            "base_url": "https://llm.example.com/v1",
            "results": [{"test_name": "a", "passed": True, "score": 1.0, "latency_ms": 5}],
        })
        assert s["base_url"] == "https://llm.example.com/v1"
