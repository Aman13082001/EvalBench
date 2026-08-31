import time
from datetime import datetime, timezone
from typing import List

from fastapi import HTTPException

from evalbench.core.models import OllamaClient
from evalbench.core.evaluators import get_evaluator
from evalbench.db.schemas import TestResult, TestRun, TestSuite

# ── Day 12: Prometheus metrics ──
from evalbench.metrics import (
    runs_total,
    tests_total,
    tokens_total,
    pass_rate_gauge,
    security_score_gauge,
    avg_score_gauge,
    avg_latency_gauge,
    latency_histogram,
    suite_duration_histogram,
    score_histogram,
    security_tests_total,
    security_latency_histogram,
    errors_total,
    ollama_model_loaded,
)
# ────────────────────────────────


class TestRunner:
    def __init__(self):
        self.ollama = OllamaClient()

    async def validate_model(self, model: str):
        if not await self.ollama.has_model(model):
            available = await self.ollama.list_models()
            raise HTTPException(
                status_code=400,
                detail=f"Model '{model}' not found in Ollama. Available: {available}",
            )

    async def run_suite(
        self,
        suite: TestSuite,
        suite_id: str
    ) -> TestRun:

        await self.validate_model(suite.model)

        evaluator = get_evaluator(suite.evaluator)
        results: List[TestResult] = []

        # ── Day 12 (Enhanced): Suite timing ──
        suite_start = time.time()
        suite_name = getattr(suite, 'name', 'unknown')
        # ────────────────────────────────────

        for test in suite.tests:
            test_start = time.time()
            try:
                ollama_resp = await self.ollama.generate(
                    model=suite.model,
                    prompt=test.prompt,
                )
                response_text = ollama_resp.get("response", "").strip()
                latency_ms = ollama_resp.get("total_duration", 0) / 1_000_000
                tokens = ollama_resp.get("eval_count", 0)
                error = None
            except Exception as e:
                response_text = ""
                latency_ms = (time.time() - test_start) * 1000
                tokens = 0
                error = str(e)
                errors_total.labels(
                    model=suite.model,
                    error_type=type(e).__name__,
                ).inc()

            passed, score = await evaluator.evaluate(
                test.expected, response_text, test.prompt
            )

            results.append(
                TestResult(
                    test_name=test.name,
                    prompt=test.prompt,
                    expected=test.expected,
                    actual=response_text,
                    latency_ms=round(latency_ms, 2),
                    tokens=tokens,
                    error=error,
                    passed=passed,
                    score=round(score, 4),
                    timestamp=datetime.now(timezone.utc),
                )
            )

            # ── Enhanced per-test metrics ──
            status = "error" if error else ("passed" if passed else "failed")
            latency_sec = latency_ms / 1000.0

            latency_histogram.labels(
                model=suite.model,
                evaluator=suite.evaluator,
                test_name=test.name,
            ).observe(latency_sec)

            tests_total.labels(
                model=suite.model,
                evaluator=suite.evaluator,
                status=status,
                suite_name=suite_name,
            ).inc()

            tokens_total.labels(
                model=suite.model,
                evaluator=suite.evaluator,
            ).inc(tokens)

            score_histogram.labels(
                model=suite.model,
                evaluator=suite.evaluator,
            ).observe(score)

            # Security-specific metrics
            if suite.evaluator == "security":
                # Find category from adversarial suite if possible
                category = "unknown"
                severity = "unknown"
                try:
                    from evalbench.security.adversarial_suite import ADVERSARIAL_TESTS
                    for t in ADVERSARIAL_TESTS:
                        if t["prompt"] == test.prompt:
                            category = t.get("category", "unknown")
                            severity = t.get("severity", "unknown")
                            break
                except Exception:
                    pass

                sec_status = "passed" if passed else "failed"
                security_tests_total.labels(
                    model=suite.model,
                    category=category,
                    severity=severity,
                    status=sec_status,
                ).inc()
                security_latency_histogram.labels(
                    model=suite.model,
                    category=category,
                ).observe(latency_sec)

        # ── Enhanced suite-level metrics ──
        suite_duration = time.time() - suite_start
        suite_duration_histogram.labels(
            model=suite.model,
            evaluator=suite.evaluator,
            suite_name=suite_name,
        ).observe(suite_duration)

        runs_total.labels(
            model=suite.model,
            evaluator=suite.evaluator,
            suite_name=suite_name,
        ).inc()

        total = len(results)
        passed_count = sum(1 for r in results if r.passed)
        pass_rate = passed_count / total if total else 0.0
        avg_score = sum(r.score for r in results if r.score is not None) / total if total else 0.0
        avg_latency = sum(r.latency_ms for r in results) / total if total else 0.0

        pass_rate_gauge.labels(
            model=suite.model,
            evaluator=suite.evaluator,
            suite_id=suite_id,
            suite_name=suite_name,
        ).set(pass_rate)

        avg_score_gauge.labels(
            model=suite.model,
            evaluator=suite.evaluator,
            suite_name=suite_name,
        ).set(avg_score)

        avg_latency_gauge.labels(
            model=suite.model,
            evaluator=suite.evaluator,
        ).set(avg_latency)

        if suite.evaluator == "security":
            security_score_gauge.labels(model=suite.model).set(pass_rate)

        # Check model availability metric
        try:
            has_model = await self.ollama.has_model(suite.model)
            ollama_model_loaded.labels(model=suite.model).set(1 if has_model else 0)
        except Exception:
            ollama_model_loaded.labels(model=suite.model).set(0)

        # ──────────────────────────────────

        return TestRun(
            suite_id=suite_id,
            model=suite.model,
            evaluator=suite.evaluator,
            results=results,
            created_at=datetime.now(
                timezone.utc
            ),
        )

    async def close(self):
        await self.ollama.close()
