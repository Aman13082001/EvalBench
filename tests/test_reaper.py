"""Which runs are provably dead — and which the API must not touch.

On startup the API used to mark *every* queued or running run as
"interrupted by API restart". That reasoning holds only for
`JOB_BACKEND=inline`, where the run executes inside the API process and
really does die with it. Compose runs `JOB_BACKEND=rq`: the work happens
in a separate worker container that does not restart with the API, so
every deploy failed runs that were executing perfectly well — the worker
then finished and wrote `completed` over the lie. Queued jobs still
sitting in Redis were failed too, and then ran anyway. With more than one
API replica, each replica start reaped everyone's runs.

So the reaper now asks what it can actually prove. Under rq that means a
stale heartbeat, not a restart; and a queued job belongs to Redis, which
the API knows nothing about.
"""

from datetime import datetime, timedelta, timezone

import pytest

from evalbench.reaper import STALE_AFTER, reap_filter

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


class TestInlineBackend:
    def test_everything_unfinished_is_dead(self):
        """The run executed in this process. If it is still marked
        running after a restart, nothing is going to finish it."""
        f = reap_filter("inline", NOW)
        assert f == {"status": {"$in": ["queued", "running"]}}


class TestRqBackend:
    def test_a_restart_alone_reaps_nothing(self):
        """The worker is a different container. An API restart says
        nothing at all about what the worker is doing."""
        f = reap_filter("rq", NOW)
        assert f["status"] == "running"
        assert "queued" not in str(f)

    def test_it_reaps_only_runs_that_stopped_reporting(self):
        f = reap_filter("rq", NOW)
        cutoff = NOW - STALE_AFTER
        clauses = f["$or"]
        assert {"heartbeat_at": {"$lt": cutoff}} in clauses

    def test_a_run_that_never_reported_is_judged_on_its_start(self):
        """Runs stored before heartbeats existed, or killed between
        claiming the job and the first test finishing, have no heartbeat
        to go on."""
        f = reap_filter("rq", NOW)
        cutoff = NOW - STALE_AFTER
        assert {
            "heartbeat_at": {"$exists": False},
            "started_at": {"$lt": cutoff},
        } in f["$or"]

    def test_the_window_is_generous(self):
        """A single slow test — a large model, a retried rate limit —
        must never look like a dead worker."""
        assert STALE_AFTER >= timedelta(minutes=10)

    def test_queued_runs_are_left_to_redis(self):
        """A queued rq job lives in Redis. The API cannot see whether a
        worker is about to pick it up, so failing it is a guess — and the
        worker would run it afterwards regardless."""
        f = reap_filter("rq", NOW)
        assert f["status"] == "running"


class TestUnknownBackend:
    def test_it_refuses_to_guess(self):
        assert reap_filter("something-else", NOW) is None


class TestHeartbeat:
    @pytest.mark.asyncio
    async def test_progress_updates_carry_a_heartbeat(self, mock_db):
        """The heartbeat is what separates "working" from "dead", so it
        has to be written by the thing that proves work is happening."""
        from unittest.mock import patch

        from bson import ObjectId

        from evalbench import jobs

        run_id = "507f191e810c19729de860ea"
        suite_id = "507f1f77bcf86cd799439011"
        mock_db.suites.find_one.return_value = {
            "_id": ObjectId(suite_id), "name": "S", "model": "m",
            "evaluator": "exact",
            "tests": [{"name": "t", "prompt": "p", "expected": "e"}],
        }
        mock_db.test_runs.find_one.return_value = {"_id": ObjectId(run_id)}

        class _Runner:
            def __init__(self, provider_key=None, **_):
                pass

            async def run_suite(self, suite, sid, progress_cb=None):
                await progress_cb(1, 2)
                raise RuntimeError("stop")

            async def close(self):
                pass

        with patch.object(jobs, "db", mock_db), patch.object(
            jobs, "TestRunner", _Runner
        ):
            await jobs.execute_run_job(run_id, suite_id)

        sets = [
            c[0][1]["$set"]
            for c in mock_db.test_runs.update_one.call_args_list
            if "$set" in c[0][1]
        ]
        # the transition to running, and the progress report
        assert any("heartbeat_at" in s and s.get("status") == "running"
                   for s in sets)
        assert any("heartbeat_at" in s and "completed_tests" in s
                   for s in sets)


class TestSweep:
    @pytest.mark.asyncio
    async def test_the_sweep_uses_the_same_rule_as_startup(self, mock_db):
        """A worker can die while the API stays up for weeks, so death by
        silence has to be checked on a clock — with the same filter, or
        the two would disagree about what counts as dead."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from evalbench.api import main

        mock_db.test_runs.update_many = AsyncMock(
            return_value=MagicMock(modified_count=2)
        )
        with patch.object(main, "db", mock_db), patch.object(
            main.settings, "job_backend", "rq"
        ):
            n = await main.reap_abandoned_runs("test")

        assert n == 2
        where = mock_db.test_runs.update_many.call_args[0][0]
        assert where["status"] == "running"
        assert "$or" in where

    @pytest.mark.asyncio
    async def test_an_unknown_backend_reaps_nothing(self, mock_db):
        from unittest.mock import AsyncMock, patch

        from evalbench.api import main

        mock_db.test_runs.update_many = AsyncMock()
        with patch.object(main, "db", mock_db), patch.object(
            main.settings, "job_backend", "mystery"
        ):
            assert await main.reap_abandoned_runs("test") == 0
        mock_db.test_runs.update_many.assert_not_called()
