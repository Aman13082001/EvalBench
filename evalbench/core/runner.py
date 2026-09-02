import asyncio
import statistics
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from fastapi import HTTPException

from evalbench.core.assertions import (
    AssertionContext,
    build_assertions,
    run_assertions,
)
from evalbench.core.evaluators import get_evaluator
from evalbench.core.evaluators.judge import LLMJudgeEvaluator
from evalbench.core.evaluators.security import SecurityEvaluator
from evalbench.core.providers import Provider, get_provider
from evalbench.db.schemas import TestCase, TestResult, TestRun, TestSuite

# ── Day 12: Prometheus metrics ──
from evalbench.metrics import (
    api_requests_total,
    avg_latency_gauge,
    avg_score_gauge,
    category_avg_score_gauge,
    category_pass_rate_gauge,
    cost_usd_total,
    errors_total,
    latency_histogram,
    ollama_model_loaded,
    pass_rate_gauge,
    prompt_tokens_total,
    run_cost_usd_gauge,
    run_errors_gauge,
    runs_total,
    sample_score_std_histogram,
    samples_configured_gauge,
    score_histogram,
    security_latency_histogram,
    security_score_gauge,
    security_tests_total,
    suite_duration_histogram,
    tests_total,
    tokens_total,
)
from evalbench.pricing import estimate_cost

# ────────────────────────────────


class TestRunner:
    def __init__(self):
        self.provider: Provider | None = None
        # Lazily built when a suite uses the judge / security evaluator.
        self._judge_provider: Provider | None = None
        self._evaluator_cache: dict = {}

    def _get_evaluator(self, name: str, suite: TestSuite):
        if name in ("judge", "security"):
            return self._build_llm_evaluator(name, suite)
        if name not in self._evaluator_cache:
            self._evaluator_cache[name] = get_evaluator(name)
        return self._evaluator_cache[name]

    def _build_llm_evaluator(self, name: str, suite: TestSuite):
        cls = LLMJudgeEvaluator if name == "judge" else SecurityEvaluator
        explicit = suite.judge_provider is not None
        jp = (suite.judge_provider or suite.provider).lower()

        # Ollama with no explicit judge override keeps the direct call path
        # (unchanged behavior). Any hosted provider, or an explicit
        # judge_provider, routes the judge call through the provider layer.
        if jp == "ollama" and not explicit:
            return cls()

        if self._judge_provider is None:
            self._judge_provider = get_provider(jp)
        judge_model = suite.judge_model or (
            "llama3.1" if jp == "ollama" else suite.model
        )
        return cls(judge_model=judge_model, provider=self._judge_provider)

    def _judge_target(self, suite: TestSuite):
        """Resolve (provider, model) for judge/rubric assertions.

        Returns ``(None, model)`` for the plain-Ollama path so the evaluator
        falls back to a direct HTTP call.
        """
        explicit = suite.judge_provider is not None
        jp = (suite.judge_provider or suite.provider).lower()
        if jp == "ollama" and not explicit:
            return None, suite.judge_model or "llama3.1"
        if self._judge_provider is None:
            self._judge_provider = get_provider(jp)
        model = suite.judge_model or (
            "llama3.1" if jp == "ollama" else suite.model
        )
        return self._judge_provider, model

    def _needs_llm_judge(self, suite: TestSuite) -> bool:
        for t in suite.tests:
            if (t.evaluator or suite.evaluator) in ("judge", "security"):
                return True
            for a in t.assert_ or []:
                if a.type in ("judge", "llm-rubric"):
                    return True
        return False

    async def validate_model(self, model: str):
        if not await self.provider.has_model(model):
            available = await self.provider.list_models()
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Model '{model}' not available for provider "
                    f"'{self.provider.name}'. Available: {available}"
                ),
            )

    async def _run_one_test(
        self,
        suite: TestSuite,
        test: TestCase,
    ) -> TestResult:
        """Run a single test ``suite.samples`` times and aggregate."""

        evaluator_name = test.evaluator or suite.evaluator

        # The security evaluator stays a dedicated path (refusal classifier).
        use_security = not test.assert_ and evaluator_name == "security"
        if use_security:
            security_eval = self._get_evaluator("security", suite)
            assertions = []
        else:
            security_eval = None
            assertions = build_assertions(
                test.assert_, evaluator_name, test.expected, test.threshold
            )
            judge_provider, judge_model = self._judge_target(suite)

        test_start = time.time()

        scores: list[float] = []
        pass_flags: list[bool] = []
        latencies: list[float] = []
        tokens_seen = 0
        prompt_tokens_seen = 0
        last_response = ""
        last_assertions: list = []
        sample_errors: list[str] = []

        for _ in range(max(1, suite.samples)):
            try:
                resp = await self.provider.generate(
                    model=suite.model,
                    prompt=test.prompt,
                    temperature=suite.temperature,
                )
                response_text = resp.text.strip()
                last_response = response_text
                latencies.append(resp.latency_ms)
                tokens_seen += resp.completion_tokens
                prompt_tokens_seen += resp.prompt_tokens

                if use_security:
                    passed_i, score_i = await security_eval.evaluate(
                        test.expected,
                        response_text,
                        test.prompt,
                        test.threshold,
                    )
                else:
                    ctx = AssertionContext(
                        response_text=response_text,
                        prompt=test.prompt,
                        latency_ms=resp.latency_ms,
                        cost_usd=estimate_cost(
                            suite.model,
                            resp.prompt_tokens,
                            resp.completion_tokens,
                            provider=suite.provider,
                        ),
                        judge_provider=judge_provider,
                        judge_model=judge_model,
                    )
                    passed_i, score_i, outcomes = await run_assertions(
                        assertions, ctx
                    )
                    last_assertions = [
                        {
                            "type": o.type,
                            "passed": o.passed,
                            "score": round(o.score, 4),
                            "detail": o.detail,
                        }
                        for o in outcomes
                    ]

                scores.append(float(score_i))
                pass_flags.append(bool(passed_i))
                api_requests_total.labels(
                    model=suite.model, endpoint="generate", status="ok"
                ).inc()
            except Exception as e:  # noqa: BLE001 - report, don't crash the run
                sample_errors.append(str(e))
                errors_total.labels(
                    model=suite.model,
                    error_type=type(e).__name__,
                ).inc()
                api_requests_total.labels(
                    model=suite.model, endpoint="generate", status="error"
                ).inc()

        if scores:
            runs = len(scores)
            pass_count = sum(pass_flags)
            score_mean = sum(scores) / runs
            score_std = statistics.pstdev(scores) if runs > 1 else 0.0
            # Majority vote across samples.
            passed = (pass_count / runs) >= 0.5
            latency_ms = (
                sum(latencies) / len(latencies) if latencies else 0.0
            )
            # An error in *some* samples is still recorded, but the test
            # is scored on the samples that succeeded.
            error = "; ".join(sorted(set(sample_errors))) or None
        else:
            runs = 0
            pass_count = 0
            score_mean = 0.0
            score_std = None
            passed = False
            latency_ms = (time.time() - test_start) * 1000
            error = "; ".join(sorted(set(sample_errors))) or "unknown error"

        cost_usd = estimate_cost(
            suite.model,
            prompt_tokens_seen,
            tokens_seen,
            provider=suite.provider,
        )

        return TestResult(
            test_name=test.name,
            prompt=test.prompt,
            expected=test.expected,
            actual=last_response,
            latency_ms=round(latency_ms, 2),
            tokens=tokens_seen,
            prompt_tokens=prompt_tokens_seen,
            completion_tokens=tokens_seen,
            cost_usd=cost_usd,
            error=error,
            passed=passed,
            score=round(score_mean, 4),
            timestamp=datetime.now(timezone.utc),
            evaluator=evaluator_name,
            category=test.category,
            difficulty=test.difficulty,
            runs=runs,
            pass_count=pass_count,
            score_std=(
                round(score_std, 4) if score_std is not None else None
            ),
            assertions=last_assertions,
        )

    async def run_suite(
        self,
        suite: TestSuite,
        suite_id: str,
        progress_cb: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> TestRun:

        self.provider = get_provider(suite.provider)
        await self.validate_model(suite.model)

        suite_start = time.time()
        suite_name = getattr(suite, 'name', 'unknown')

        # Build the shared judge provider once, before tests fan out, so
        # concurrent tests don't race to create it.
        if self._needs_llm_judge(suite):
            self._judge_target(suite)

        # Tests run in parallel, bounded by the smaller of the suite setting
        # and the provider's own ceiling. Result order matches suite order.
        limit = max(
            1, min(suite.concurrency, self.provider.max_concurrency)
        )
        semaphore = asyncio.Semaphore(limit)

        total = len(suite.tests)
        completed = 0

        async def _run_guarded(test: TestCase) -> TestResult:
            nonlocal completed
            async with semaphore:
                result = await self._run_one_test(suite, test)
            completed += 1
            if progress_cb is not None:
                await progress_cb(completed, total)
            return result

        results: list[TestResult] = list(
            await asyncio.gather(
                *(_run_guarded(t) for t in suite.tests)
            )
        )

        for test, result in zip(suite.tests, results, strict=True):
            evaluator_name = test.evaluator or suite.evaluator
            status = (
                "error"
                if result.error and result.runs == 0
                else ("passed" if result.passed else "failed")
            )
            latency_sec = result.latency_ms / 1000.0

            latency_histogram.labels(
                model=suite.model,
                evaluator=evaluator_name,
                test_name=test.name,
            ).observe(latency_sec)

            tests_total.labels(
                model=suite.model,
                evaluator=evaluator_name,
                status=status,
                suite_name=suite_name,
                category=test.category or "uncategorized",
            ).inc()

            tokens_total.labels(
                model=suite.model,
                evaluator=evaluator_name,
            ).inc(result.tokens)

            prompt_tokens_total.labels(
                model=suite.model,
                evaluator=evaluator_name,
            ).inc(result.prompt_tokens)

            score_histogram.labels(
                model=suite.model,
                evaluator=evaluator_name,
            ).observe(result.score or 0.0)

            if result.score_std is not None:
                sample_score_std_histogram.labels(
                    model=suite.model,
                    evaluator=evaluator_name,
                ).observe(result.score_std)

            # Security-specific metrics
            if evaluator_name == "security":
                category = test.category or "unknown"
                severity = test.difficulty or "unknown"
                if category == "unknown" or severity == "unknown":
                    try:
                        from evalbench.security.adversarial_suite import (
                            ADVERSARIAL_TESTS,
                        )
                        for t in ADVERSARIAL_TESTS:
                            if t["prompt"] == test.prompt:
                                category = t.get("category", category)
                                severity = t.get("severity", severity)
                                break
                    except Exception:
                        pass

                sec_status = "passed" if result.passed else "failed"
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

        # ── Suite-level metrics ──
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
        # Infrastructure errors are not model failures: exclude fully
        # errored tests from pass rate / average score.
        scored = [r for r in results if not (r.error and r.runs == 0)]
        total_scored = len(scored)

        passed_count = sum(1 for r in scored if r.passed)
        pass_rate = passed_count / total_scored if total_scored else 0.0
        avg_score = (
            sum(r.score for r in scored if r.score is not None) / total_scored
            if total_scored
            else 0.0
        )
        avg_latency = (
            sum(r.latency_ms for r in results) / total if total else 0.0
        )

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

        # ── Per-category breakdown for the most recent run ──
        cat_buckets: dict = {}
        for r in results:
            cat = r.category or "uncategorized"
            b = cat_buckets.setdefault(
                cat, {"passed": 0, "scored": 0, "score_sum": 0.0}
            )
            if r.error and r.runs == 0:
                continue
            b["scored"] += 1
            b["score_sum"] += r.score or 0.0
            if r.passed:
                b["passed"] += 1

        for cat, b in cat_buckets.items():
            n = b["scored"]
            category_pass_rate_gauge.labels(
                model=suite.model,
                suite_name=suite_name,
                category=cat,
            ).set(b["passed"] / n if n else 0.0)
            category_avg_score_gauge.labels(
                model=suite.model,
                suite_name=suite_name,
                category=cat,
            ).set(b["score_sum"] / n if n else 0.0)

        run_errors_gauge.labels(
            model=suite.model,
            evaluator=suite.evaluator,
            suite_name=suite_name,
        ).set(total - total_scored)

        samples_configured_gauge.labels(
            model=suite.model,
            suite_name=suite_name,
        ).set(max(1, suite.samples))

        # ── Estimated cost of this run ──
        total_cost = round(sum(r.cost_usd for r in results), 6)
        run_cost_usd_gauge.labels(
            model=suite.model,
            provider=suite.provider,
            suite_name=suite_name,
        ).set(total_cost)
        if total_cost > 0:
            cost_usd_total.labels(
                model=suite.model,
                provider=suite.provider,
                suite_name=suite_name,
            ).inc(total_cost)

        # Security score reflects ONLY the safety-evaluated tests, not the
        # whole (possibly mixed-evaluator) suite.
        sec_scored = [r for r in scored if r.evaluator == "security"]
        if sec_scored:
            sec_pass_rate = sum(
                1 for r in sec_scored if r.passed
            ) / len(sec_scored)
            security_score_gauge.labels(model=suite.model).set(sec_pass_rate)

        try:
            has_model = await self.provider.has_model(suite.model)
            ollama_model_loaded.labels(model=suite.model).set(
                1 if has_model else 0
            )
        except Exception:
            ollama_model_loaded.labels(model=suite.model).set(0)

        return TestRun(
            suite_id=suite_id,
            model=suite.model,
            evaluator=suite.evaluator,
            results=results,
            created_at=datetime.now(
                timezone.utc
            ),
            status="completed",
            progress=1.0,
            total_tests=total,
            completed_tests=len(results),
        )

    async def close(self):
        if self.provider is not None:
            await self.provider.close()
        if self._judge_provider is not None:
            await self._judge_provider.close()
