"""Your dashboard: your runs, drawn by the app.

Grafana reads Prometheus, whose metrics are labelled by model and suite
and never by user, so it shows the instance — everyone's runs, one
picture, read-only — and cannot show a person theirs. The app can: it
knows who is signed in. `GET /dashboard` answers with the caller's own
runs, counted exactly the way a run report counts them, so the two can
never disagree. Grafana stays the operations view, for the admin.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from evalbench.api import dashboard
from evalbench.api.deps import get_current_user
from evalbench.api.main import app

ALICE = {"username": "alice", "role": "user", "_id": "a"}
ADMIN = {"username": "admin", "role": "admin", "_id": "0"}
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def _run(days_ago, model="m1", provider="groq", status="completed", results=(), **extra):
    return {
        "_id": ObjectId(), "created_by": "alice", "model": model, "provider": provider,
        "status": status, "created_at": NOW - timedelta(days=days_ago),
        "total_tests": len(results), "results": list(results), **extra,
    }


def _res(passed, score=None, latency=100.0, cost=0.001, category="c", error=None, runs=1):
    r = {"passed": passed, "score": score if score is not None else (1.0 if passed else 0.0),
         "latency_ms": latency, "cost_usd": cost, "category": category, "runs": runs}
    if error:
        r["error"] = error
    return r


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()


def _as(user, mock_db, runs):
    mock_db.test_runs.find.return_value = _Cursor(runs)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


@pytest.fixture(autouse=True)
def _frozen_now():
    with patch.object(dashboard, "_now", lambda: NOW):
        yield


class TestScope:
    def test_the_query_is_the_callers_own_runs_in_the_window(self, mock_db):
        with _as(ALICE, mock_db, []) as c:
            r = c.get("/dashboard?days=30")
        assert r.status_code == 200
        q = mock_db.test_runs.find.call_args[0][0]
        assert q["created_by"] == "alice"
        assert q["created_at"]["$gte"] == NOW - timedelta(days=30)

    def test_an_admin_sees_the_whole_instance(self, mock_db):
        """owner_filter is empty for an admin: the same page, everyone's runs."""
        with _as(ADMIN, mock_db, []) as c:
            c.get("/dashboard")
        assert "created_by" not in mock_db.test_runs.find.call_args[0][0]

    def test_days_is_bounded(self, mock_db):
        with _as(ALICE, mock_db, []) as c:
            assert c.get("/dashboard?days=0").json()["days"] == 1
            assert c.get("/dashboard?days=9999").json()["days"] == 365
            assert c.get("/dashboard").json()["days"] == 30

    def test_only_what_the_page_needs_is_fetched(self, mock_db):
        """A run document carries every response; the dashboard needs
        counts, scores, latency, cost and category — not the text."""
        with _as(ALICE, mock_db, []) as c:
            c.get("/dashboard")
        projection = mock_db.test_runs.find.call_args[0][1]
        assert "results.score" in projection
        assert "results.actual" not in projection and "results.prompt" not in projection


class TestCountsAgreeWithTheRunReport:
    def test_totals(self, mock_db):
        runs = [
            _run(1, results=[_res(True), _res(False), _res(False, error="timeout", runs=0)]),
            _run(2, results=[_res(True), _res(True)]),
            _run(3, status="failed", results=[]),
        ]
        with _as(ALICE, mock_db, runs) as c:
            t = c.get("/dashboard").json()["totals"]
        # 3 runs; 2 completed; the timed-out test is an error, not a failure
        assert t["runs"] == 3 and t["completed"] == 2 and t["failed"] == 1
        assert t["scored"] == 4 and t["passed"] == 3 and t["errors"] == 1
        assert t["pass_rate"] == 0.75
        assert t["cost_usd"] == pytest.approx(0.005)
        assert t["avg_latency_ms"] == 100.0

    def test_no_runs_is_a_page_not_an_error(self, mock_db):
        with _as(ALICE, mock_db, []) as c:
            body = c.get("/dashboard").json()
        assert body["totals"]["runs"] == 0
        assert body["totals"]["pass_rate"] is None
        assert body["by_model"] == [] and body["by_category"] == []
        assert len(body["by_day"]) == 30

    def test_every_day_in_the_window_is_present_with_zeros(self, mock_db):
        runs = [_run(0, results=[_res(True)]), _run(2, results=[_res(False)]), _run(2, results=[_res(True)])]
        with _as(ALICE, mock_db, runs) as c:
            days = c.get("/dashboard?days=7").json()["by_day"]
        assert [d["day"] for d in days][-1] == "2026-09-21"
        assert [d["day"] for d in days][0] == "2026-09-15"
        assert len(days) == 7
        today, two_ago = days[-1], days[-3]
        assert today == {"day": "2026-09-21", "runs": 1, "scored": 1, "passed": 1, "pass_rate": 1.0}
        assert two_ago == {"day": "2026-09-19", "runs": 2, "scored": 2, "passed": 1, "pass_rate": 0.5}
        assert days[-2] == {"day": "2026-09-20", "runs": 0, "scored": 0, "passed": 0, "pass_rate": None}

    def test_by_model_is_the_comparison_a_person_wants(self, mock_db):
        runs = [
            _run(1, model="a", results=[_res(True, score=0.9, latency=200, cost=0.002), _res(True, score=0.7, latency=400, cost=0.002)]),
            _run(2, model="a", results=[_res(False, score=0.2, latency=300, cost=0.001)]),
            _run(3, model="b", provider="gemini", results=[_res(True, score=1.0, latency=50, cost=0.0)]),
        ]
        with _as(ALICE, mock_db, runs) as c:
            by = c.get("/dashboard").json()["by_model"]
        assert [m["model"] for m in by] == ["a", "b"]  # most runs first
        a = by[0]
        assert a["provider"] == "groq" and a["runs"] == 2
        assert a["scored"] == 3 and a["passed"] == 2 and a["pass_rate"] == pytest.approx(0.6667, abs=1e-4)
        assert a["avg_score"] == pytest.approx(0.6, abs=1e-4)
        assert a["avg_latency_ms"] == 300.0
        assert a["cost_usd"] == pytest.approx(0.005)

    def test_by_category_across_every_run(self, mock_db):
        runs = [
            _run(1, results=[_res(True, category="factual"), _res(False, category="reasoning")]),
            _run(2, results=[_res(True, category="reasoning"), _res(True, category="reasoning")]),
        ]
        with _as(ALICE, mock_db, runs) as c:
            by = c.get("/dashboard").json()["by_category"]
        assert {c["category"]: (c["scored"], c["passed"]) for c in by} == {
            "factual": (1, 1), "reasoning": (3, 2),
        }
        assert by[0]["category"] == "reasoning"  # most scored first

    def test_a_result_without_a_category_is_uncategorised_not_dropped(self, mock_db):
        r = _res(True)
        del r["category"]
        with _as(ALICE, mock_db, [_run(1, results=[r])]) as c:
            by = c.get("/dashboard").json()["by_category"]
        assert by == [{"category": "uncategorised", "scored": 1, "passed": 1, "pass_rate": 1.0}]


def test_the_route_requires_a_user(client):
    """Owned data: the auth-coverage scan lists it; this pins it too."""
    app.dependency_overrides.pop(get_current_user, None)
    try:
        assert client.get("/dashboard").status_code == 401
    finally:
        from tests.conftest import override_get_current_user

        app.dependency_overrides[get_current_user] = override_get_current_user
