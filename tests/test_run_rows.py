"""One definition of a run-history row, shared by both lists.

Two endpoints list runs — `/runs` (recent, across suites) and
`/suites/{id}/runs` (this benchmark's history) — and they had drifted.
`/runs` counted a test as scored when it had no `error` field at all,
while the summary counts it as scored when at least one sample produced
a score. A test that was rate-limited on one sample and answered on
another is scored by one rule and discarded by the other, so the same
run showed two different pass rates depending on which page you opened.

And the per-suite list shipped whole run documents — every response and
every assertion — to render twenty rows.
"""

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from evalbench.api.deps import get_current_user
from evalbench.api.main import app
from evalbench.api.summary import RUN_ROW_FIELDS, run_row

SUITE_ID = "507f1f77bcf86cd799439011"
RUN_ID = "507f191e810c19729de860ea"


@pytest.fixture
def as_alice(mock_db):
    app.dependency_overrides[get_current_user] = lambda: {
        "username": "alice", "role": "user", "_id": "a"
    }
    with TestClient(app) as c:
        yield c
    from tests.conftest import override_get_current_user

    app.dependency_overrides[get_current_user] = override_get_current_user


class TestRunRow:
    def test_a_partly_rate_limited_test_still_counts_as_scored(self):
        """It has an `error` string but `runs: 2` — two samples came back.
        Dropping it would report the provider's bad minute as a smaller
        benchmark than the one that ran."""
        row = run_row({
            "_id": ObjectId(RUN_ID),
            "results": [
                {"passed": True, "runs": 3},
                {"passed": False, "runs": 2, "error": "rate limited",
                 "rate_limited": 1},
                {"error": "timeout", "runs": 0},
            ],
        })
        assert row["scored_tests"] == 2
        assert row["passed"] == 1
        assert row["pass_rate"] == 0.5
        assert row["errors"] == 1

    def test_it_reports_lost_samples(self):
        row = run_row({
            "_id": ObjectId(RUN_ID),
            "results": [
                {"passed": True, "runs": 2, "rate_limited": 1},
                {"passed": True, "runs": 1, "rate_limited": 2},
            ],
        })
        assert row["rate_limited_samples"] == 3

    def test_nothing_scored_gives_no_rate_rather_than_zero(self):
        """0% and "we could not measure" are different claims."""
        row = run_row({
            "_id": ObjectId(RUN_ID),
            "results": [{"error": "boom", "runs": 0}],
        })
        assert row["pass_rate"] is None
        assert row["scored_tests"] == 0

    def test_the_results_never_ride_along(self):
        row = run_row({"_id": ObjectId(RUN_ID), "results": [{"passed": True}]})
        assert "results" not in row

    def test_the_projection_asks_only_for_what_it_counts(self):
        assert RUN_ROW_FIELDS["results.passed"] == 1
        for heavy in ("results.response", "results.assertions",
                      "results.prompt"):
            assert heavy not in RUN_ROW_FIELDS


class TestSuiteRunHistory:
    def test_history_rows_carry_the_pass_rate_and_not_the_bodies(
        self, as_alice, mock_db
    ):
        async def gen():
            yield {
                "_id": ObjectId(RUN_ID), "suite_id": SUITE_ID,
                "status": "completed", "total_tests": 2, "completed_tests": 2,
                "results": [
                    {"passed": True, "runs": 1},
                    {"passed": False, "runs": 1},
                ],
            }

        chain = mock_db.test_runs.find.return_value
        chain.sort.return_value.limit.return_value = gen()

        row = as_alice.get(f"/suites/{SUITE_ID}/runs").json()[0]
        assert row["pass_rate"] == 0.5
        assert row["scored_tests"] == 2
        assert "results" not in row

        projection = mock_db.test_runs.find.call_args[0][1]
        assert "results.assertions" not in projection

    def test_history_is_still_owner_scoped(self, as_alice, mock_db):
        async def empty():
            for _ in ():
                yield {}

        chain = mock_db.test_runs.find.return_value
        chain.sort.return_value.limit.return_value = empty()
        as_alice.get(f"/suites/{SUITE_ID}/runs")
        assert mock_db.test_runs.find.call_args[0][0]["created_by"] == "alice"
