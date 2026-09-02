"""Production-grade Prometheus metrics for EvalBench."""

from prometheus_client import Counter, Gauge, Histogram, Info
from prometheus_fastapi_instrumentator import Instrumentator

# ── FastAPI HTTP auto-instrumentation ──
instrumentator = Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_instrument_requests_inprogress=True,
    excluded_handlers=["/metrics", "/health"],
)

# ── Build info ──
evalbench_info = Info("evalbench_build", "EvalBench build information")
evalbench_info.info({"version": "0.1.0", "platform": "EvalBench"})

# ═══════════════════════════════════════════════════════════════
# ROW 1: OVERVIEW
# ═══════════════════════════════════════════════════════════════

runs_total = Counter(
    "evalbench_runs_total",
    "Total number of test suite runs completed",
    ["model", "evaluator", "suite_name"],
)

tests_total = Counter(
    "evalbench_tests_total",
    "Total number of individual test cases executed",
    ["model", "evaluator", "status", "suite_name", "category"],
)

tokens_total = Counter(
    "evalbench_tokens_total",
    "Total completion (output) tokens generated across all tests",
    ["model", "evaluator"],
)

prompt_tokens_total = Counter(
    "evalbench_prompt_tokens_total",
    "Total prompt (input) tokens sent across all tests",
    ["model", "evaluator"],
)

cost_usd_total = Counter(
    "evalbench_cost_usd_total",
    "Cumulative estimated USD cost across all runs (0 for local/free models)",
    ["model", "provider", "suite_name"],
)

# ── Gauges (current state) ──
pass_rate_gauge = Gauge(
    "evalbench_pass_rate",
    "Pass rate of the most recent test suite run (0.0–1.0)",
    ["model", "evaluator", "suite_id", "suite_name"],
)

security_score_gauge = Gauge(
    "evalbench_security_score",
    "Security pass rate from adversarial test suite (0.0–1.0)",
    ["model"],
)

avg_score_gauge = Gauge(
    "evalbench_avg_score",
    "Average score of the most recent run",
    ["model", "evaluator", "suite_name"],
)

avg_latency_gauge = Gauge(
    "evalbench_avg_latency_ms",
    "Average latency per test in the most recent run",
    ["model", "evaluator"],
)

# ── Scoring v2: per-category + sampling state ──
category_pass_rate_gauge = Gauge(
    "evalbench_category_pass_rate",
    "Pass rate of the most recent run, broken down by test category (0.0-1.0)",
    ["model", "suite_name", "category"],
)

category_avg_score_gauge = Gauge(
    "evalbench_category_avg_score",
    "Average score of the most recent run, by test category",
    ["model", "suite_name", "category"],
)

run_errors_gauge = Gauge(
    "evalbench_run_errors",
    "Number of tests in the most recent run that errored on every sample "
    "(excluded from the pass rate)",
    ["model", "evaluator", "suite_name"],
)

samples_configured_gauge = Gauge(
    "evalbench_samples_configured",
    "Number of samples per test used by the most recent run",
    ["model", "suite_name"],
)

run_cost_usd_gauge = Gauge(
    "evalbench_run_cost_usd",
    "Estimated USD cost of the most recent run (0 for local/free models)",
    ["model", "provider", "suite_name"],
)

# ═══════════════════════════════════════════════════════════════
# ROW 2: PERFORMANCE
# ═══════════════════════════════════════════════════════════════

latency_histogram = Histogram(
    "evalbench_latency_seconds",
    "Per-test LLM latency distribution",
    ["model", "evaluator", "test_name"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 15.0, 30.0, 60.0, 120.0, 300.0],
)

suite_duration_histogram = Histogram(
    "evalbench_suite_duration_seconds",
    "Total suite execution time distribution",
    ["model", "evaluator", "suite_name"],
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0],
)

# ── Score distribution ──
score_histogram = Histogram(
    "evalbench_score_distribution",
    "Distribution of test scores across all runs",
    ["model", "evaluator"],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

# ── Sample variance (flakiness) — only meaningful when samples > 1 ──
sample_score_std_histogram = Histogram(
    "evalbench_sample_score_std",
    "Per-test std-dev of scores across repeated samples (0 = deterministic)",
    ["model", "evaluator"],
    buckets=[0.0, 0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5],
)

# ═══════════════════════════════════════════════════════════════
# ROW 3: SECURITY
# ═══════════════════════════════════════════════════════════════

security_tests_total = Counter(
    "evalbench_security_tests_total",
    "Total adversarial tests executed",
    ["model", "category", "severity", "status"],
)

security_latency_histogram = Histogram(
    "evalbench_security_latency_seconds",
    "Latency of security test responses",
    ["model", "category"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# ═══════════════════════════════════════════════════════════════
# ROW 4: REGRESSION & QUALITY
# ═══════════════════════════════════════════════════════════════

regression_detected = Gauge(
    "evalbench_regression_detected",
    "1 if regression detected in last comparison, 0 otherwise",
    ["model", "suite_name"],
)

regression_pvalue = Gauge(
    "evalbench_regression_pvalue",
    "P-value of the last regression test",
    ["model", "suite_name"],
)

regression_mean_diff = Gauge(
    "evalbench_regression_mean_diff",
    "Mean score difference in last regression test",
    ["model", "suite_name"],
)

# ═══════════════════════════════════════════════════════════════
# ROW 5: ERRORS & HEALTH
# ═══════════════════════════════════════════════════════════════

errors_total = Counter(
    "evalbench_errors_total",
    "Total errors during test execution",
    ["model", "error_type"],
)

api_requests_total = Counter(
    "evalbench_api_requests_total",
    "Total API requests made to Ollama",
    ["model", "endpoint", "status"],
)

ollama_model_loaded = Gauge(
    "evalbench_ollama_model_loaded",
    "1 if model is available in Ollama, 0 otherwise",
    ["model"],
)


def init_metrics(app):
    """Mount /metrics endpoint and instrument all HTTP routes."""
    instrumentator.instrument(app).expose(
        app,
        endpoint="/metrics",
        include_in_schema=False,
        tags=["monitoring"],
    )
