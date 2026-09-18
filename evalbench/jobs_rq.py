"""RQ glue: enqueue a run, and the sync entrypoint the worker executes.

Only imported when ``settings.job_backend == "rq"``. Keeping it separate
means the default (inline) install never needs Redis or rq.
"""

from __future__ import annotations

import asyncio

from redis import Redis
from rq import Queue, Retry, get_current_job

from evalbench import runkeys
from evalbench.config import settings
from evalbench.jobs import RUNS_QUEUE


def _redis() -> Redis:
    return Redis.from_url(settings.redis_url)


def _queue() -> Queue:
    return Queue(RUNS_QUEUE, connection=_redis())


def enqueue_run(
    run_id: str, suite_id: str, provider_key: str | None = None
) -> None:
    # The key is not a job argument. RQ persists those — for a failed job,
    # by default, for a year. See evalbench/runkeys.py.
    if provider_key:
        runkeys.stash(_redis(), run_id, provider_key)
    _queue().enqueue(
        "evalbench.jobs_rq.run_job_sync",
        run_id,
        suite_id,
        job_id=run_id,
        retry=Retry(max=2, interval=[10, 30]),
        job_timeout=settings.suite_run_timeout,
    )


def run_job_sync(
    run_id: str, suite_id: str, provider_key: str | None = None
) -> None:
    """Sync wrapper RQ calls. Runs the async job on a fresh loop + client.

    ``provider_key`` as an argument is only honoured for jobs queued
    before the key moved out of the payload — refusing them would fail
    every run in flight during a deploy. New jobs carry none; the key is
    read from its stash and deleted once the run cannot need it again.
    """
    from evalbench import jobs
    from evalbench.db.mongo import make_client

    redis = _redis()
    key = provider_key or runkeys.take(redis, run_id)

    async def _go() -> None:
        client = make_client()
        jobs.db = client[settings.mongodb_db]
        try:
            await jobs.execute_run_job(run_id, suite_id, key)
        finally:
            client.close()

    try:
        asyncio.run(_go())
    except BaseException:
        # RQ may run this job again. Keep the key for that, and only for
        # that: once no retries remain, nothing will ever need it.
        job = get_current_job()
        if job is None or not getattr(job, "retries_left", 0):
            runkeys.discard(redis, run_id)
        raise
    else:
        runkeys.discard(redis, run_id)


def queue_position(run_id: str) -> int | None:
    try:
        return _queue().get_job_position(run_id)
    except Exception:
        return None
