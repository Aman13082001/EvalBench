"""Async job model: POST /run returns immediately, work happens in the background."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from bson import ObjectId

from evalbench.db.schemas import TestCase, TestRun, TestSuite

RUN_ID = "507f1f77bcf86cd799439011"
SUITE_ID = "507f191e810c19729de860ea"


def _suite_doc():
    return {
        "_id": ObjectId(SUITE_ID),
        "name": "S",
        "provider": "mock",
        "model": "m",
        "evaluator": "exact",
        "tests": [
            {"name": "t1", "prompt": "p", "expected": "e", "threshold": 0.8},
            {"name": "t2", "prompt": "p", "expected": "e", "threshold": 0.8},
        ],
        "created_at": datetime.now(timezone.utc),
    }


class TestRunEndpointIsAsync:
    def test_run_returns_202_queued_without_blocking(self, client, mock_db):
        mock_db.suites.find_one.return_value = _suite_doc()
        mock_db.test_runs.insert_one.return_value.inserted_id = ObjectId(RUN_ID)

        with patch(
            "evalbench.api.routes.execute_run_job", new_callable=AsyncMock
        ) as job:
            resp = client.post(f"/suites/{SUITE_ID}/run")

        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "queued"
        assert body["run_id"] == RUN_ID
        assert body["test_count"] == 2

        persisted = mock_db.test_runs.insert_one.call_args[0][0]
        assert persisted["status"] == "queued"
        assert persisted["total_tests"] == 2
        assert persisted["progress"] == 0.0

        job.assert_called_once()

    def test_run_unknown_suite_404(self, client, mock_db):
        mock_db.suites.find_one.return_value = None
        resp = client.post(f"/suites/{SUITE_ID}/run")
        assert resp.status_code == 404


class TestStartupReaper:
    def test_orphaned_runs_are_failed_on_startup(self, client, mock_db):
        # The `client` fixture runs the app lifespan on entry.
        mock_db.test_runs.update_many.assert_called()
        flt, update = mock_db.test_runs.update_many.call_args[0]
        assert flt == {"status": {"$in": ["queued", "running"]}}
        assert update["$set"]["status"] == "failed"
        assert "restart" in update["$set"]["error"]


class TestRunStatusEndpoint:
    def test_status_reports_progress(self, client, mock_db):
        mock_db.test_runs.find_one.return_value = {
            "_id": ObjectId(RUN_ID),
            "status": "running",
            "progress": 0.5,
            "completed_tests": 2,
            "total_tests": 4,
            "model": "m",
            "error": None,
        }
        resp = client.get(f"/runs/{RUN_ID}/status")
        assert resp.status_code == 200
        d = resp.json()
        assert d["status"] == "running"
        assert d["progress"] == 0.5
        assert d["completed_tests"] == 2
        assert d["total_tests"] == 4

    def test_status_defaults_for_legacy_run(self, client, mock_db):
        mock_db.test_runs.find_one.return_value = {
            "_id": ObjectId(RUN_ID),
            "model": "m",
        }
        resp = client.get(f"/runs/{RUN_ID}/status")
        d = resp.json()
        assert d["status"] == "completed"
        assert d["progress"] == 1.0

    def test_status_not_found(self, client, mock_db):
        mock_db.test_runs.find_one.return_value = None
        resp = client.get(f"/runs/{RUN_ID}/status")
        assert resp.status_code == 404


class TestExecuteRunJob:
    @pytest.mark.asyncio
    async def test_marks_running_then_completed(self, mock_db):
        from evalbench.api.routes import execute_run_job

        suite = TestSuite(
            name="S",
            provider="mock",
            model="m",
            evaluator="exact",
            tests=[TestCase(name="t1", prompt="p", expected="e")],
        )
        fake_run = TestRun(
            suite_id="s",
            model="m",
            evaluator="exact",
            results=[],
            created_at=datetime.now(timezone.utc),
            status="completed",
            total_tests=1,
            completed_tests=1,
        )

        with patch("evalbench.api.routes.TestRunner") as RunnerCls:
            inst = RunnerCls.return_value
            inst.run_suite = AsyncMock(return_value=fake_run)
            inst.close = AsyncMock()
            await execute_run_job(RUN_ID, "s", suite)

        sets = [c[0][1]["$set"] for c in mock_db.test_runs.update_one.call_args_list]
        assert sets[0]["status"] == "running"
        assert sets[-1]["status"] == "completed"
        assert sets[-1]["progress"] == 1.0
        inst.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_marks_failed_on_exception(self, mock_db):
        from evalbench.api.routes import execute_run_job

        suite = TestSuite(
            name="S",
            provider="mock",
            model="m",
            evaluator="exact",
            tests=[TestCase(name="t1", prompt="p", expected="e")],
        )

        with patch("evalbench.api.routes.TestRunner") as RunnerCls:
            inst = RunnerCls.return_value
            inst.run_suite = AsyncMock(side_effect=RuntimeError("boom"))
            inst.close = AsyncMock()
            await execute_run_job(RUN_ID, "s", suite)

        last_set = mock_db.test_runs.update_one.call_args_list[-1][0][1]["$set"]
        assert last_set["status"] == "failed"
        assert "boom" in last_set["error"]
        inst.close.assert_awaited_once()
