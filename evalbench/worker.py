"""RQ worker entrypoint:  python -m evalbench.worker

Consumes the runs queue. Run one or many of these alongside the API with
JOB_BACKEND=rq.
"""

import logging

from redis import Redis
from rq import Queue, Worker

from evalbench.config import settings
from evalbench.jobs import RUNS_QUEUE


def main() -> None:
    logging.basicConfig(level=settings.log_level.upper())
    conn = Redis.from_url(settings.redis_url)
    worker = Worker([Queue(RUNS_QUEUE, connection=conn)], connection=conn)
    logging.getLogger("evalbench").info(
        "worker started on queue %s (redis=%s)", RUNS_QUEUE, settings.redis_url
    )
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
