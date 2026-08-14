"""Prometheus metrics for EvalBench."""

from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Histogram, Gauge, Info

# ── FastAPI HTTP auto-instrumentation (latency, status codes, throughput) ──
instrumentator = Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_instrument_requests_inprogress=True,
    excluded_handlers=["/metrics"],
)

# ── Build info ──
evalbench_info = Info("evalbench_build", "EvalBench build information")
evalbench_info.info({"version": "0.1.0", "platform": "EvalBench"})

# ── Counters ──
runs_total = Counter(
    "evalbench_runs_total",
    "Total number of test suite runs completed",
    ["model", "evaluator"],
)

tests_total = Counter(
    "evalbench_tests_total",
    "Total number of individual test cases executed",
    ["model", "evaluator", "status"],  # status: passed | failed | error
)

tokens_total = Counter(
    "evalbench_tokens_total",
    "Total tokens generated across all tests",
    ["model", "evaluator"],
)

# ── Gauges ──
pass_rate_gauge = Gauge(
    "evalbench_pass_rate",
    "Pass rate of the most recent test suite run (0.0–1.0)",
    ["model", "evaluator", "suite_id"],
)

security_score_gauge = Gauge(
    "evalbench_security_score",
    "Security pass rate from adversarial test suite (0.0–1.0)",
    ["model"],
)

# ── Histograms ──
latency_histogram = Histogram(
    "evalbench_latency_seconds",
    "Per-test LLM latency distribution",
    ["model", "evaluator"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)

suite_duration_histogram = Histogram(
    "evalbench_suite_duration_seconds",
    "Total suite execution time distribution",
    ["model", "evaluator"],
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0],
)


def init_metrics(app):
    """Mount /metrics endpoint and instrument all HTTP routes."""
    instrumentator.instrument(app).expose(
        app,
        endpoint="/metrics",
        include_in_schema=False,
        tags=["monitoring"],
    )