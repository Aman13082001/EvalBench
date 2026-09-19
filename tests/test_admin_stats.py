"""Admin stats must not read the whole database to draw four numbers.

Total spend was summed by iterating every run document ever stored,
pulling each one's `results` array through the API process. That is
instant at eighty runs and a timeout at a hundred thousand: the page got
monotonically slower for as long as the instance was used, which is the
worst shape a performance bug can have — it looks fine exactly while you
are testing it.

Counting is what a database is for. Both the spend and the per-status
breakdown are now single aggregations, and neither grows a Python loop
over documents.
"""

import pytest
from fastapi.testclient import TestClient

from evalbench.api.main import app


@pytest.fixture
def client(mock_db):
    with TestClient(app) as c:
        # Startup reads runs once (the status backfill); the endpoints
        # under test must not, and that is what the assertions check.
        mock_db.test_runs.find.reset_mock()
        yield c


def _agg(mock_db, by_status, spend):
    """Stand in for the two aggregations the endpoint runs."""
    calls = []

    def aggregate(pipeline, *a, **k):
        calls.append(pipeline)
        stages = {next(iter(s)) for s in pipeline}

        async def gen():
            if "$unwind" in stages:
                yield {"_id": None, "total": spend}
            else:
                for status, n in by_status.items():
                    yield {"_id": status, "n": n}

        return gen()

    mock_db.test_runs.aggregate = aggregate
    return calls


class TestItAggregates:
    def test_spend_is_summed_by_mongo_not_by_python(self, client, mock_db):
        calls = _agg(mock_db, {"completed": 3, "failed": 1}, 0.4213)
        body = client.get("/admin/stats").json()

        assert body["total_cost_usd"] == 0.4213
        # the giveaway: nothing iterated run documents
        mock_db.test_runs.find.assert_not_called()
        assert any(
            any("$unwind" in s for s in pipeline) for pipeline in calls
        )

    def test_statuses_come_from_one_query_not_four(self, client, mock_db):
        calls = _agg(mock_db, {"completed": 3, "failed": 1}, 0.0)
        body = client.get("/admin/stats").json()

        assert body["runs_by_status"]["completed"] == 3
        assert body["runs_by_status"]["failed"] == 1
        # every state is reported, including the ones with no runs
        assert body["runs_by_status"]["queued"] == 0
        assert body["runs_by_status"]["running"] == 0
        assert len(calls) == 2  # one for statuses, one for spend

    def test_an_empty_instance_reports_zero_not_an_error(self, client, mock_db):
        def aggregate(pipeline, *a, **k):
            async def gen():
                for _ in ():
                    yield {}

            return gen()

        mock_db.test_runs.aggregate = aggregate
        body = client.get("/admin/stats").json()
        assert body["total_cost_usd"] == 0
        assert body["runs_by_status"] == {
            "queued": 0, "running": 0, "completed": 0, "failed": 0
        }

    def test_an_unexpected_status_is_still_reported(self, client, mock_db):
        """A status the code does not know about — from an older version,
        or a future one — must not vanish from an operator's view."""
        _agg(mock_db, {"completed": 1, "cancelled": 2}, 0.0)
        body = client.get("/admin/stats").json()
        assert body["runs_by_status"]["cancelled"] == 2


    def test_runs_with_no_status_are_still_counted(self, client, mock_db):
        """Runs stored before the field existed have none. Dropping them
        left the breakdown disagreeing with the total, with nothing on
        the page to say where the difference went."""
        _agg(mock_db, {"completed": 51, None: 35}, 0.0)
        body = client.get("/admin/stats").json()
        assert body["runs_by_status"]["unknown"] == 35
        assert sum(body["runs_by_status"].values()) == 86
