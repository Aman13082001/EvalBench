import time
from datetime import datetime
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
    latency_histogram,
    suite_duration_histogram,
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

    async def run_suite(self, suite: TestSuite, suite_id: str) -> TestRun:
        await self.validate_model(suite.model)
        evaluator = get_evaluator(suite.evaluator)
        results: List[TestResult] = []

        # ── Day 12: Suite timing ──
        suite_start = time.time()
        # ──────────────────────────

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

            passed, score = await evaluator.evaluate(
                test.expected,
                response_text,
                test.prompt,
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
                    timestamp=datetime.utcnow(),
                )
            )

            # ── Day 12: Per-test metrics ──
            status = "error" if error else ("passed" if passed else "failed")

            latency_sec = latency_ms / 1000.0

            latency_histogram.labels(
                model=suite.model,
                evaluator=suite.evaluator,
            ).observe(latency_sec)

            tests_total.labels(
                model=suite.model,
                evaluator=suite.evaluator,
                status=status,
            ).inc()

            tokens_total.labels(
                model=suite.model,
                evaluator=suite.evaluator,
            ).inc(tokens)
            # ──────────────────────────────

        # ── Day 12: Suite-level metrics ──
        suite_duration = time.time() - suite_start

        suite_duration_histogram.labels(
            model=suite.model,
            evaluator=suite.evaluator,
        ).observe(suite_duration)

        runs_total.labels(
            model=suite.model,
            evaluator=suite.evaluator,
        ).inc()

        total = len(results)
        passed_count = sum(1 for r in results if r.passed)
        pass_rate = passed_count / total if total else 0.0

        pass_rate_gauge.labels(
            model=suite.model,
            evaluator=suite.evaluator,
            suite_id=suite_id,
        ).set(pass_rate)

        if suite.evaluator == "security":
            security_score_gauge.labels(
                model=suite.model
            ).set(pass_rate)
        # ──────────────────────────────────

        return TestRun(
            suite_id=suite_id,
            model=suite.model,
            evaluator=suite.evaluator,
            results=results,
            created_at=datetime.utcnow(),
        )

    async def close(self):
        await self.ollama.close()