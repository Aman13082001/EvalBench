"""A run has a deadline, and the deadline is kept here.

`suite_run_timeout` was handed to RQ as `job_timeout` and otherwise
trusted. It was not kept: one run held the only worker for 660 minutes
against a declared limit of 15, and a second run sat in the queue behind
it for eleven and a half hours before it began. A rate-limited free tier
is where this shows up — every 429 is a backoff, and a 228-call suite
can spend the night making no progress anyone can see.

So the deadline is enforced where the work happens, on the loop that
runs it, rather than delegated to a mechanism whose failure is silent.
An overrun is a failed run with a reason, not a run that says "running"
into the morning.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from bson import ObjectId

from evalbench import jobs

RUN_ID = "507f1f77bcf86cd799439011"
SUITE_ID = "507f191e810c19729de860ea"


def _suite_doc():
    return {
        "_id": ObjectId(SUITE_ID),
        "name": "S",
        "provider": "mock",
        "model": "m",
        "evaluator": "exact",
        "tests": [{"name": "t1", "prompt": "p", "expected": "e"}],
        "created_at": datetime.now(timezone.utc),
    }


def _last_set(mock_db):
    """The fields of the final update_one on the run document."""
    return mock_db.test_runs.update_one.call_args[0][1]["$set"]


class TestARunThatOverrunsIsFailed:
    @pytest.mark.asyncio
    async def test_it_does_not_run_past_its_deadline(self, mock_db):
        mock_db.suites.find_one.return_value = _suite_doc()
        mock_db.test_runs.find_one.return_value = {"_id": ObjectId(RUN_ID)}

        async def never_finishes(*a, **k):
            await asyncio.sleep(60)

        with (
            patch.object(jobs.settings, "suite_run_timeout", 0.05),
            patch.object(jobs.TestRunner, "run_suite", side_effect=never_finishes),
            patch.object(jobs.TestRunner, "close", new=AsyncMock()),
        ):
            await asyncio.wait_for(
                jobs.execute_run_job(RUN_ID, SUITE_ID), timeout=10
            )

        fields = _last_set(mock_db)
        assert fields["status"] == "failed"
        assert "finished_at" in fields

    @pytest.mark.asyncio
    async def test_the_reason_says_it_ran_out_of_time(self, mock_db):
        """Not "TimeoutError". The person reading it needs to know what
        to do differently: fewer samples, a smaller benchmark, own key."""
        mock_db.suites.find_one.return_value = _suite_doc()
        mock_db.test_runs.find_one.return_value = {"_id": ObjectId(RUN_ID)}

        async def never_finishes(*a, **k):
            await asyncio.sleep(60)

        with (
            patch.object(jobs.settings, "suite_run_timeout", 0.05),
            patch.object(jobs.TestRunner, "run_suite", side_effect=never_finishes),
            patch.object(jobs.TestRunner, "close", new=AsyncMock()),
        ):
            await jobs.execute_run_job(RUN_ID, SUITE_ID)

        error = _last_set(mock_db)["error"].lower()
        # It says a limit was passed, and what to do about it.
        assert "limit" in error and "stopped" in error
        assert "samples" in error or "smaller" in error or "own key" in error

    @pytest.mark.asyncio
    async def test_a_run_inside_its_deadline_is_untouched(self, mock_db):
        mock_db.suites.find_one.return_value = _suite_doc()
        mock_db.test_runs.find_one.return_value = {"_id": ObjectId(RUN_ID)}

        class _Run:
            results, model, evaluator = [], "m", "exact"

        with (
            patch.object(jobs.settings, "suite_run_timeout", 30),
            patch.object(jobs.TestRunner, "run_suite", new=AsyncMock(return_value=_Run())),
            patch.object(jobs.TestRunner, "close", new=AsyncMock()),
            patch.object(jobs, "record_resolution", new=AsyncMock()),
        ):
            await jobs.execute_run_job(RUN_ID, SUITE_ID)

        assert _last_set(mock_db)["status"] == "completed"


class TestTheDeclaredLimitIsRealistic:
    def test_a_full_sized_run_is_given_room(self):
        """The ceiling on a run is 250 calls. A free tier answers a few a
        minute. Fifteen minutes was not a limit anyone could meet, so it
        was being ignored rather than met."""
        from evalbench.config import Settings

        assert Settings.model_fields["suite_run_timeout"].default >= 1800
