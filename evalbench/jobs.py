"""Async run execution + the queue/inline dispatch.

`execute_run_job(run_id, suite_id)` is the unit of work: it loads the
suite, runs it, and streams status into the run document. It is invoked
either inline via FastAPI ``BackgroundTasks`` (default) or from an RQ
worker, selected by ``settings.job_backend``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bson import ObjectId

from evalbench.config import settings
from evalbench.core.runner import TestRunner
from evalbench.db.mongo import db
from evalbench.db.schemas import TestSuite
from evalbench.metrics import run_status_total

logger = logging.getLogger("evalbench")

RUNS_QUEUE = "evalbench:runs"


async def execute_run_job(run_id: str, suite_id: str) -> None:
    """Run the suite for ``run_id`` and record the outcome."""

    oid = {"_id": ObjectId(run_id)}

    suite_doc = await db.suites.find_one({"_id": ObjectId(suite_id)})
    if not suite_doc:
        await db.test_runs.update_one(
            oid,
            {"$set": {
                "status": "failed",
                "error": "suite not found",
                "finished_at": datetime.now(timezone.utc),
            }},
        )
        run_status_total.labels(status="failed").inc()
        return

    suite_doc["_id"] = str(suite_doc["_id"])
    suite = TestSuite(**suite_doc)

    await db.test_runs.update_one(
        oid,
        {"$set": {
            "status": "running",
            "started_at": datetime.now(timezone.utc),
        }},
    )

    runner = TestRunner()

    async def _report(done: int, total: int) -> None:
        await db.test_runs.update_one(
            oid,
            {"$set": {
                "completed_tests": done,
                "progress": round(done / total, 4) if total else 1.0,
            }},
        )

    try:
        run = await runner.run_suite(suite, suite_id, progress_cb=_report)
        await db.test_runs.update_one(
            oid,
            {"$set": {
                "status": "completed",
                "progress": 1.0,
                "completed_tests": len(run.results),
                "results": [r.model_dump() for r in run.results],
                "model": run.model,
                "evaluator": run.evaluator,
                "finished_at": datetime.now(timezone.utc),
            }},
        )
        run_status_total.labels(status="completed").inc()
    except Exception as e:  # noqa: BLE001 - record failure, don't crash the worker
        logger.exception("Run %s failed", run_id)
        await db.test_runs.update_one(
            oid,
            {"$set": {
                "status": "failed",
                "error": str(e),
                "finished_at": datetime.now(timezone.utc),
            }},
        )
        run_status_total.labels(status="failed").inc()
    finally:
        await runner.close()


def submit_run(run_id: str, suite_id: str, background_tasks) -> None:
    """Dispatch a queued run to the configured backend."""
    if settings.job_backend == "rq":
        from evalbench.jobs_rq import enqueue_run

        enqueue_run(run_id, suite_id)
    else:
        background_tasks.add_task(execute_run_job, run_id, suite_id)
