"""Resolution is computed when a run lands, not when a list is drawn.

The first version read the 400 newest runs across all of a user's
benchmarks and bucketed them. Correct on a laptop with eighty runs;
wrong at ten thousand, because a user whose recent activity sits on two
benchmarks exhausts the window there, and an older benchmark that
genuinely has runs reports "Not yet measured — run it once". The page
states a falsehood, and quietly, which is the worst kind.

A bigger window only moves the threshold. The fix is to compute the
estimate at the moment new evidence arrives — a run finishing — and
store it on the benchmark, so drawing the list is a projection and costs
nothing per row.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId

SUITE_ID = "507f1f77bcf86cd799439011"


def _run(scores, created_at):
    return {
        "status": "completed",
        "created_at": created_at,
        "results": [{"test_name": k, "score": v} for k, v in scores.items()],
    }


class TestItIsRecordedWhenARunFinishes:
    @pytest.mark.asyncio
    async def test_a_finished_run_updates_the_benchmark(self, mock_db):
        from evalbench import jobs

        t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
        t1 = datetime(2026, 9, 2, tzinfo=timezone.utc)
        history = [
            _run({f"t{i}": 1.0 for i in range(20)}, t0),
            _run({f"t{i}": (0.0 if i % 4 == 0 else 1.0) for i in range(20)}, t1),
        ]

        chain = mock_db.test_runs.find.return_value
        chain.sort.return_value.limit.return_value = _cursor(history)

        with patch.object(jobs, "db", mock_db):
            await jobs.record_resolution(SUITE_ID)

        where, update = mock_db.suites.update_one.call_args[0]
        assert where == {"_id": ObjectId(SUITE_ID)}
        res = update["$set"]["resolution"]
        assert res["mde"] is not None and res["runs_used"] == 2
        assert res["tests"] == 20

    @pytest.mark.asyncio
    async def test_it_reads_only_this_benchmarks_runs(self, mock_db):
        """The window that broke the first version was shared across
        benchmarks. Per benchmark, a fixed number of its own runs is
        exactly the evidence the estimate needs."""
        from evalbench import jobs

        chain = mock_db.test_runs.find.return_value
        chain.sort.return_value.limit.return_value = _cursor([])

        with patch.object(jobs, "db", mock_db):
            await jobs.record_resolution(SUITE_ID)

        where = mock_db.test_runs.find.call_args[0][0]
        assert where["suite_id"] == SUITE_ID
        assert where["status"] == "completed"
        chain.sort.return_value.limit.assert_called_once()
        assert chain.sort.return_value.limit.call_args[0][0] <= 10

    @pytest.mark.asyncio
    async def test_a_failure_here_never_fails_the_run(self, mock_db):
        """The run is the product; the estimate is a bonus. If this
        throws, the user's result must still be saved."""
        from evalbench import jobs

        mock_db.test_runs.find.side_effect = RuntimeError("mongo is unhappy")
        with patch.object(jobs, "db", mock_db):
            await jobs.record_resolution(SUITE_ID)  # must not raise

    @pytest.mark.asyncio
    async def test_a_bad_suite_id_is_ignored(self, mock_db):
        from evalbench import jobs

        with patch.object(jobs, "db", mock_db):
            await jobs.record_resolution("not-an-objectid")
        mock_db.suites.update_one.assert_not_called()


class TestTheListJustReadsIt:
    @pytest.mark.asyncio
    async def test_the_list_endpoint_no_longer_scans_runs(self, mock_db):
        """The whole point: drawing the page costs one query again."""
        from fastapi.testclient import TestClient

        from evalbench.api.deps import get_current_user
        from evalbench.api.main import app

        async def suites():
            yield {
                "_id": ObjectId(SUITE_ID), "name": "S", "created_by": "alice",
                "test_count": 20,
                "resolution": {"mde": 0.11, "runs_used": 3, "tests": 20,
                               "reason": None},
            }

        mock_db.suites.aggregate.return_value = suites()

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "alice", "role": "user", "_id": "a"
        }
        try:
            with TestClient(app) as c:
                # Startup is allowed to read runs (it backfills the
                # status of pre-job-model runs, once). The endpoint is not.
                mock_db.test_runs.find = MagicMock(
                    side_effect=AssertionError("the list must not read runs")
                )
                row = c.get("/suites").json()[0]
        finally:
            from tests.conftest import override_get_current_user

            app.dependency_overrides[get_current_user] = (
                override_get_current_user
            )

        assert row["resolution"]["mde"] == 0.11

    @pytest.mark.asyncio
    async def test_a_benchmark_without_one_still_reads_honestly(self, mock_db):
        """Benchmarks that predate this have no stored estimate. The row
        must say so rather than leave the field missing."""
        from fastapi.testclient import TestClient

        from evalbench.api.deps import get_current_user
        from evalbench.api.main import app

        async def suites():
            yield {"_id": ObjectId(SUITE_ID), "name": "S",
                   "created_by": "alice", "test_count": 20}

        mock_db.suites.aggregate.return_value = suites()

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "alice", "role": "user", "_id": "a"
        }
        try:
            with TestClient(app) as c:
                row = c.get("/suites").json()[0]
        finally:
            from tests.conftest import override_get_current_user

            app.dependency_overrides[get_current_user] = (
                override_get_current_user
            )

        assert row["resolution"]["mde"] is None
        assert row["resolution"]["reason"]


def _cursor(docs):
    async def gen():
        for d in docs:
            yield d

    return gen()


class TestTheProjectionCarriesTheEvidence:
    def test_runs_is_fetched_or_nothing_looks_scored(self):
        """`runs` is what separates a test that never answered from one
        that answered on a second sample. Without it in the projection
        every partially rate-limited test reads as unscored — which on a
        run that hit a free-tier limit is most of them."""
        from evalbench.jobs import _RESOLUTION_FIELDS

        assert _RESOLUTION_FIELDS["results.runs"] == 1
        assert _RESOLUTION_FIELDS["results.score"] == 1
        # and still nothing heavy
        assert "results.response" not in _RESOLUTION_FIELDS
        assert "results.assertions" not in _RESOLUTION_FIELDS
