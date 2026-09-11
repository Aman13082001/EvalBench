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


async def execute_run_job(
    run_id: str, suite_id: str, provider_key: str | None = None
) -> None:
    """Run the suite for ``run_id`` and record the outcome.

    ``provider_key`` is the caller's own key, if they supplied one. It
    arrives as a job argument rather than from the run document on
    purpose: the document is persisted forever, the argument is not.
    """

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

    # The run document records what was asked for, override included, so
    # it is the source of truth for which model and provider to use — not
    # the suite, which only holds the defaults.
    run_doc = await db.test_runs.find_one(oid) or {}
    if run_doc.get("model"):
        suite.model = run_doc["model"]
    if run_doc.get("provider"):
        suite.provider = run_doc["provider"]

    await db.test_runs.update_one(
        oid,
        {"$set": {
            "status": "running",
            "started_at": datetime.now(timezone.utc),
        }},
    )

    runner = TestRunner(provider_key=provider_key)

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


def submit_run(
    run_id: str,
    suite_id: str,
    background_tasks,
    provider_key: str | None = None,
) -> None:
    """Dispatch a queued run to the configured backend.

    Under ``rq`` a caller-supplied key travels inside the job payload in
    Redis until the job completes. Acceptable on a private network; before
    a public deployment this should become a per-user key stored
    encrypted, so nothing sensitive transits the queue at all.
    """
    if settings.job_backend == "rq":
        from evalbench.jobs_rq import enqueue_run

        enqueue_run(run_id, suite_id, provider_key)
    else:
        background_tasks.add_task(
            execute_run_job, run_id, suite_id, provider_key
        )
