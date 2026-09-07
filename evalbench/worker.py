"""RQ worker entrypoint:  python -m evalbench.worker

Consumes the runs queue. Run one or many of these alongside the API with
JOB_BACKEND=rq.

The worker serves its own Prometheus endpoint. This is not optional
plumbing: with JOB_BACKEND=rq the *runner* executes here, so every run
metric (pass rate, per-category scores, cost, tokens, latency, errors,
flakiness) is emitted in this process. Prometheus scraping only the API
would collect none of them, and the dashboard and alert rules would sit
empty while looking perfectly healthy.
"""

import logging

from prometheus_client import start_http_server
from redis import Redis
from rq import Queue, SimpleWorker

from evalbench.config import settings
from evalbench.jobs import RUNS_QUEUE

log = logging.getLogger("evalbench")


def main() -> None:
    logging.basicConfig(level=settings.log_level.upper())

    # Serve metrics before taking any job, so a scrape landing between
    # startup and the first run sees an endpoint rather than a refused
    # connection. Every replica binds the same port on its own container
    # IP; Prometheus finds them all via DNS service discovery.
    start_http_server(settings.worker_metrics_port)
    log.info("worker metrics on :%d/metrics", settings.worker_metrics_port)

    conn = Redis.from_url(settings.redis_url)

    # SimpleWorker, not Worker, and the reason is the metrics endpoint
    # above. rq.Worker forks a "work horse" per job; the runner would
    # emit every metric into that child's registry and the child would
    # exit, taking them with it. The parent serving this endpoint would
    # never see a single run metric — which is exactly the bug this
    # replaced. SimpleWorker executes in-process, so the metrics land in
    # the registry we actually expose.
    #
    # The trade is losing work-horse isolation: a job that hard-crashes
    # takes the worker down rather than just itself. Acceptable here —
    # these jobs are async network I/O to model providers, the container
    # has a restart policy, and RQ still enforces job timeouts in-process.
    worker = SimpleWorker(
        [Queue(RUNS_QUEUE, connection=conn)], connection=conn
    )
    log.info(
        "worker started on queue %s (redis=%s)", RUNS_QUEUE, settings.redis_url
    )
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
