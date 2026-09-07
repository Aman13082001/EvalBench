"""Anything that runs a suite must be scraped by Prometheus.

This exists because of a bug that was invisible for a long time. Docker
Compose defaults to ``JOB_BACKEND=rq``, so the runner executes in the
worker process and emits every run metric there — pass rate, per-category
scores, cost, tokens, latency, errors, flakiness. Prometheus scraped only
``api:8000``. So all of it was collected into a process nobody read and
discarded when the job finished.

Nothing failed. The API was up, the worker was up, Prometheus was up, and
the dashboard rendered 42 panels of "No data" that looked exactly like an
idle system. Only comparing a completed run against ``/metrics`` revealed
it.

These tests pin the wiring so it cannot silently come apart again.
"""

import pathlib
from unittest.mock import patch

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
PROM = yaml.safe_load(
    (ROOT / "prometheus" / "prometheus.yml").read_text(encoding="utf-8")
)


def _scrape_targets() -> set[str]:
    """Every hostname Prometheus will scrape, static or DNS-discovered."""
    hosts: set[str] = set()
    for job in PROM.get("scrape_configs", []):
        for sc in job.get("static_configs", []) or []:
            for target in sc.get("targets", []) or []:
                hosts.add(target.split(":")[0])
        for dns in job.get("dns_sd_configs", []) or []:
            hosts.update(dns.get("names", []) or [])
    return hosts


def _services_running_evalbench() -> set[str]:
    """Compose services built from the *root* Dockerfile — the Python
    image — which are the ones that can execute a suite and therefore
    emit run metrics.

    Keyed on the build context rather than "has a build:" because the
    web app also builds from a Dockerfile and cannot run anything; it
    has no metrics to expose and must not be demanded as a target.
    """
    out = set()
    for name, svc in (COMPOSE.get("services") or {}).items():
        build = svc.get("build")
        if isinstance(build, dict) and build.get("context") == ".":
            out.add(name)
        elif build == ".":
            out.add(name)
    return out


def test_every_service_that_can_run_a_suite_is_scraped():
    running = _services_running_evalbench()
    scraped = _scrape_targets()
    assert running, "no compose service builds the evalbench image"
    missing = sorted(running - scraped)
    assert not missing, (
        f"{missing} run the evalbench image and can execute a suite, but "
        f"Prometheus does not scrape them (it scrapes {sorted(scraped)}). "
        "Metrics emitted there are collected and thrown away, and the "
        "dashboard shows 'No data' while everything looks healthy."
    )


def test_worker_is_discovered_by_dns_so_scaling_works():
    """`docker compose up --scale worker=3` must not need a config edit.
    A static target would only ever scrape one replica."""
    worker_jobs = [
        j
        for j in PROM["scrape_configs"]
        if any("worker" in n for d in j.get("dns_sd_configs", []) or []
               for n in d.get("names", []))
    ]
    assert worker_jobs, "the worker must be discovered via dns_sd_configs"
    dns = worker_jobs[0]["dns_sd_configs"][0]
    assert dns["type"] == "A"
    assert dns["port"] == COMPOSE["services"]["worker"]["environment"][
        "WORKER_METRICS_PORT"
    ], "the scrape port and the worker's configured port have drifted apart"


def test_worker_does_not_fork_or_the_metrics_endpoint_is_pointless():
    """rq.Worker forks a work horse per job. The runner would emit every
    metric into that child, the child would exit, and the endpoint this
    process serves would show nothing but build_info — which is precisely
    the bug that motivated this file. SimpleWorker runs in-process, so
    the metrics land in the registry we expose."""
    import rq

    from evalbench import worker as worker_module

    assert getattr(worker_module, "SimpleWorker", None) is rq.SimpleWorker, (
        "the worker must use rq.SimpleWorker: metrics emitted in a forked "
        "work horse die with it, leaving /metrics empty"
    )
    # rq.Worker must not have been imported here by a later edit.
    assert "Worker" not in [
        n for n in vars(worker_module) if n == "Worker"
    ], "rq.Worker forks; importing it here invites the old bug back"


def test_worker_serves_metrics_before_taking_work():
    """If the server started after `worker.work()` it would never start —
    that call blocks forever."""
    from evalbench import worker as worker_module

    calls = []

    with patch.object(
        worker_module, "start_http_server", side_effect=lambda p: calls.append(p)
    ), patch.object(worker_module, "Redis"), patch.object(
        worker_module, "Queue"
    ), patch.object(worker_module, "SimpleWorker") as mock_worker:
        mock_worker.return_value.work.side_effect = lambda **_: calls.append(
            "work"
        )
        worker_module.main()

    assert calls, "the worker never started a metrics server"
    assert calls[0] != "work", "metrics server must start before work()"
    assert calls[0] == worker_module.settings.worker_metrics_port
