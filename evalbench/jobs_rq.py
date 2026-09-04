"""RQ glue: enqueue a run, and the sync entrypoint the worker executes.

Only imported when ``settings.job_backend == "rq"``. Keeping it separate
means the default (inline) install never needs Redis or rq.
"""

from __future__ import annotations

import asyncio

from redis import Redis
from rq import Queue, Retry

from evalbench.config import settings
from evalbench.jobs import RUNS_QUEUE


def _queue() -> Queue:
    return Queue(RUNS_QUEUE, connection=Redis.from_url(settings.redis_url))


def enqueue_run(run_id: str, suite_id: str) -> None:
    _queue().enqueue(
        "evalbench.jobs_rq.run_job_sync",
        run_id,
        suite_id,
        job_id=run_id,
        retry=Retry(max=2, interval=[10, 30]),
        job_timeout=settings.suite_run_timeout,
    )


def run_job_sync(run_id: str, suite_id: str) -> None:
    """Sync wrapper RQ calls. Runs the async job on a fresh loop + client."""
    from evalbench import jobs
    from evalbench.db.mongo import make_client

    async def _go() -> None:
        client = make_client()
        jobs.db = client[settings.mongodb_db]
        try:
            await jobs.execute_run_job(run_id, suite_id)
        finally:
            client.close()

    asyncio.run(_go())


def queue_position(run_id: str) -> int | None:
    try:
        return _queue().get_job_position(run_id)
    except Exception:
        return None
