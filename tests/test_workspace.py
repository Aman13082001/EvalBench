"""Backend wiring for the evaluation workspace.

Four small pieces the first authenticated page needs and nothing else
did: a model/provider override so one suite can be run against two
models, a caller-supplied key that never touches the database, a daily
cap on runs that spend the server's key, and one call for "my recent
runs" instead of one per suite. Plus the bundled benchmarks: listable,
and adoptable exactly once.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from evalbench.api.deps import get_current_user
from evalbench.api.main import app
from evalbench.benchmarks import BUNDLED, describe_benchmarks, load_benchmark

SUITE_ID = "507f1f77bcf86cd799439011"
RUN_ID = "507f191e810c19729de860ea"
ALICE = {"username": "alice", "role": "user", "_id": "a"}

SUITE_DOC = {
    "_id": ObjectId(SUITE_ID),
    "name": "S",
    "provider": "groq",
    "model": "openai/gpt-oss-20b",
    "evaluator": "exact",
    "created_by": "alice",
    "tests": [{"name": "t", "prompt": "p", "expected": "e"}],
}


@pytest.fixture
def as_alice(mock_db):
    app.dependency_overrides[get_current_user] = lambda: ALICE
    with TestClient(app) as c:
        yield c
    from tests.conftest import override_get_current_user

    app.dependency_overrides[get_current_user] = override_get_current_user


def _run_doc():
    return {"_id": ObjectId(RUN_ID), "created_by": "alice", "status": "queued"}


class TestModelOverride:
    def test_override_is_recorded_on_the_run(self, as_alice, mock_db):
        """The run document must say what was actually run, not what the
        suite defaults to — that is what makes it the source of truth."""
        mock_db.suites.find_one.return_value = dict(SUITE_DOC)
        mock_db.test_runs.insert_one.return_value.inserted_id = ObjectId(RUN_ID)
        with patch("evalbench.api.routes.submit_run"):
            r = as_alice.post(
                f"/suites/{SUITE_ID}/run",
                json={"model": "openai/gpt-oss-120b", "provider": "groq"},
            )
        assert r.status_code == 202, r.text
        inserted = mock_db.test_runs.insert_one.call_args[0][0]
        assert inserted["model"] == "openai/gpt-oss-120b"
        assert inserted["provider"] == "groq"

    def test_no_body_still_works_exactly_as_before(self, as_alice, mock_db):
        mock_db.suites.find_one.return_value = dict(SUITE_DOC)
        mock_db.test_runs.insert_one.return_value.inserted_id = ObjectId(RUN_ID)
        with patch("evalbench.api.routes.submit_run"):
            r = as_alice.post(f"/suites/{SUITE_ID}/run")
        assert r.status_code == 202
        inserted = mock_db.test_runs.insert_one.call_args[0][0]
        assert inserted["model"] == SUITE_DOC["model"]

    def test_unknown_provider_is_rejected(self, as_alice, mock_db):
        mock_db.suites.find_one.return_value = dict(SUITE_DOC)
        r = as_alice.post(
            f"/suites/{SUITE_ID}/run", json={"provider": "not-a-provider"}
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_job_applies_the_override_when_it_runs(self, mock_db):
        """The worker loads the suite by id; it must then read the run
        document and use *its* model, or the override is decorative."""
        from evalbench import jobs

        mock_db.suites.find_one.return_value = dict(SUITE_DOC)
        mock_db.test_runs.find_one.return_value = {
            **_run_doc(),
            "model": "openai/gpt-oss-120b",
            "provider": "groq",
        }
        seen = {}

        class _Runner:
            def __init__(self, provider_key=None):
                seen["key"] = provider_key

            async def run_suite(self, suite, suite_id, progress_cb=None):
                seen["model"] = suite.model
                seen["provider"] = suite.provider
                raise RuntimeError("stop here")

            async def close(self):
                pass

        with patch.object(jobs, "db", mock_db), patch.object(
            jobs, "TestRunner", _Runner
        ):
            await jobs.execute_run_job(RUN_ID, SUITE_ID, provider_key="k")

        assert seen["model"] == "openai/gpt-oss-120b"
        assert seen["provider"] == "groq"
        assert seen["key"] == "k"


class TestOwnKey:
    def test_key_reaches_the_job_but_never_the_database(self, as_alice, mock_db):
        mock_db.suites.find_one.return_value = dict(SUITE_DOC)
        mock_db.test_runs.insert_one.return_value.inserted_id = ObjectId(RUN_ID)
        with patch("evalbench.api.routes.submit_run") as submit:
            r = as_alice.post(
                f"/suites/{SUITE_ID}/run", json={"provider_key": "gsk_mine"}
            )
        assert r.status_code == 202
        assert submit.call_args[0][3] == "gsk_mine"
        inserted = mock_db.test_runs.insert_one.call_args[0][0]
        assert "gsk_mine" not in str(inserted)
        assert inserted["used_server_key"] is False


class TestDailyCap:
    def test_server_key_runs_are_capped(self, as_alice, mock_db):
        from evalbench.api import routes

        mock_db.suites.find_one.return_value = dict(SUITE_DOC)
        mock_db.test_runs.count_documents.return_value = routes.settings.daily_run_cap
        r = as_alice.post(f"/suites/{SUITE_ID}/run")
        assert r.status_code == 429
        assert "own provider key" in r.json()["detail"]
        mock_db.test_runs.insert_one.assert_not_called()

    def test_own_key_bypasses_the_cap(self, as_alice, mock_db):
        from evalbench.api import routes

        mock_db.suites.find_one.return_value = dict(SUITE_DOC)
        mock_db.test_runs.count_documents.return_value = routes.settings.daily_run_cap
        mock_db.test_runs.insert_one.return_value.inserted_id = ObjectId(RUN_ID)
        with patch("evalbench.api.routes.submit_run"):
            r = as_alice.post(
                f"/suites/{SUITE_ID}/run", json={"provider_key": "gsk_mine"}
            )
        assert r.status_code == 202

    def test_local_providers_are_not_capped(self, as_alice, mock_db):
        """Ollama costs nothing; the cap is about spending our key."""
        from evalbench.api import routes

        mock_db.suites.find_one.return_value = {**SUITE_DOC, "provider": "ollama"}
        mock_db.test_runs.count_documents.return_value = routes.settings.daily_run_cap
        mock_db.test_runs.insert_one.return_value.inserted_id = ObjectId(RUN_ID)
        with patch("evalbench.api.routes.submit_run"):
            r = as_alice.post(f"/suites/{SUITE_ID}/run")
        assert r.status_code == 202
        assert mock_db.test_runs.insert_one.call_args[0][0]["used_server_key"] is False

    def test_quota_endpoint_reports_remaining(self, as_alice, mock_db):
        from evalbench.api import routes

        mock_db.test_runs.count_documents.return_value = 3
        body = as_alice.get("/suites/quota").json()
        assert body["cap"] == routes.settings.daily_run_cap
        assert body["used"] == 3
        assert body["remaining"] == routes.settings.daily_run_cap - 3

    def test_admin_is_uncapped(self, client, mock_db):
        mock_db.test_runs.count_documents.return_value = 10_000
        body = client.get("/suites/quota").json()
        assert body["cap"] is None and body["remaining"] is None


class TestRecentRuns:
    def test_lists_only_own_runs_newest_first_with_pass_rate(self, as_alice, mock_db):
        async def gen():
            yield {
                "_id": ObjectId(RUN_ID), "suite_id": SUITE_ID, "model": "m",
                "status": "completed", "created_at": datetime.now(timezone.utc),
                "results": [
                    {"passed": True, "cost_usd": 0.001},
                    {"passed": False, "cost_usd": 0.002},
                    {"passed": False, "error": "timeout"},
                ],
            }

        chain = mock_db.test_runs.find.return_value
        chain.sort.return_value.limit.return_value = gen()
        r = as_alice.get("/runs?limit=5")
        assert r.status_code == 200
        # scoped to the caller
        assert mock_db.test_runs.find.call_args[0][0] == {"created_by": "alice"}
        # newest first, bounded
        chain.sort.assert_called_with("created_at", -1)
        chain.sort.return_value.limit.assert_called_with(5)
        row = r.json()[0]
        # the errored test is excluded from the rate, per the runner's rule
        assert row["passed"] == 1 and row["scored_tests"] == 2
        assert row["pass_rate"] == 0.5
        assert row["total_cost_usd"] == 0.003
        assert "results" not in row

    def test_limit_is_bounded(self, as_alice, mock_db):
        async def empty():
            for _ in ():
                yield {}

        chain = mock_db.test_runs.find.return_value
        chain.sort.return_value.limit.return_value = empty()
        as_alice.get("/runs?limit=9999")
        chain.sort.return_value.limit.assert_called_with(100)


class TestBundled:
    def test_manifest_points_at_real_files(self):
        for b in BUNDLED:
            assert load_benchmark(b["slug"]) is not None, b["file"]

    def test_fixtures_are_not_offered(self):
        """hero.yaml drives the homepage; demo.yaml is replay-only. Neither
        is something a user should be handed as a benchmark."""
        files = {b["file"] for b in BUNDLED}
        assert "hero.yaml" not in files
        assert "demo.yaml" not in files

    def test_counts_are_read_from_the_files(self):
        listed = {d["slug"]: d for d in describe_benchmarks()}
        for b in BUNDLED:
            assert listed[b["slug"]]["test_count"] == len(
                load_benchmark(b["slug"])["tests"]
            )

    def test_list_endpoint(self, as_alice, mock_db):
        r = as_alice.get("/suites/bundled")
        assert r.status_code == 200
        assert {d["slug"] for d in r.json()} == {b["slug"] for b in BUNDLED}

    def test_adopt_creates_a_copy_once(self, as_alice, mock_db):
        mock_db.suites.find_one.return_value = None
        mock_db.suites.insert_one.return_value.inserted_id = ObjectId(SUITE_ID)
        r = as_alice.post("/suites/bundled/safety/adopt")
        assert r.status_code == 200
        assert r.json()["created"] is True
        doc = mock_db.suites.insert_one.call_args[0][0]
        assert doc["created_by"] == "alice"
        assert doc["bundled_slug"] == "safety"

    def test_adopt_is_idempotent(self, as_alice, mock_db):
        """The clutter this guards against is real: repeated imports are
        how one account reached 69 suites."""
        mock_db.suites.find_one.return_value = {
            "_id": ObjectId(SUITE_ID), "name": "Safety Evaluation Suite"
        }
        r = as_alice.post("/suites/bundled/safety/adopt")
        assert r.json()["created"] is False
        assert r.json()["id"] == SUITE_ID
        mock_db.suites.insert_one.assert_not_called()
        # and it looked for *this user's* copy, not anyone's
        assert mock_db.suites.find_one.call_args[0][0]["created_by"] == "alice"

    def test_adopt_unknown_slug(self, as_alice, mock_db):
        mock_db.suites.find_one.return_value = None
        assert as_alice.post("/suites/bundled/nope/adopt").status_code == 404


class TestSummaryContract:
    def test_summary_includes_per_test_results(self, as_alice, mock_db):
        """The web client's RunSummary type declares `results`, and the
        result view maps over it. The playground summary always had it;
        this endpoint didn't, and the workspace crashed on first render."""
        mock_db.test_runs.find_one.return_value = {
            "_id": ObjectId(RUN_ID),
            "created_by": "alice",
            "status": "completed",
            "model": "m",
            "evaluator": "exact",
            "created_at": datetime.now(timezone.utc),
            "results": [
                {"test_name": "t", "passed": True, "score": 1.0,
                 "latency_ms": 5, "tokens": 3, "cost_usd": 0.0,
                 "category": "c", "assertions": []},
            ],
        }
        body = as_alice.get(f"/runs/{RUN_ID}/summary").json()
        assert "results" in body
        assert body["results"][0]["test_name"] == "t"
