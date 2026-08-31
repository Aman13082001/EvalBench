"""Unit tests for statistical regression detection."""

from datetime import datetime, timezone

import pytest

from evalbench.core.regression import RegressionDetector
from evalbench.db.schemas import TestResult, TestRun


def make_run(scores: list[float]) -> TestRun:
    results = [
        TestResult(
            test_name=f"test_{i}",
            prompt="p",
            expected="e",
            actual="a",
            latency_ms=100.0,
            tokens=10,
            score=s,
            passed=s >= 0.8,
            timestamp=datetime.now(timezone.utc),
        )
        for i, s in enumerate(scores)
    ]

    return TestRun(
        suite_id="suite_1",
        model="llama3.1",
        evaluator="semantic",
        results=results,
        created_at=datetime.now(timezone.utc),
    )


class TestRegressionDetector:
    @pytest.fixture
    def detector(self):
        return RegressionDetector(threshold=0.05)

    def test_no_regression_identical_scores(self, detector):
        baseline = make_run([0.9, 0.85, 0.9, 0.88])
        current = make_run([0.9, 0.85, 0.9, 0.88])

        result = detector.compare(baseline, current)

        assert result["regression_detected"] is False
        assert result["mean_diff"] == 0.0

    def test_regression_detected(self, detector):
        baseline = make_run([0.9, 0.9, 0.9, 0.9])
        current = make_run([0.5, 0.4, 0.5, 0.4])

        result = detector.compare(baseline, current)

        assert result["regression_detected"] is True
        assert result["mean_diff"] < -0.05
        assert result["p_value"] < 0.05

    def test_insufficient_data(self, detector):
        baseline = make_run([0.9])
        current = make_run([0.5])

        result = detector.compare(baseline, current)

        assert result["regression_detected"] is False
        assert "Insufficient data" in result["reason"]

    def test_mismatched_counts(self, detector):
        baseline = make_run([0.9, 0.8])
        current = make_run([0.5])

        result = detector.compare(baseline, current)

        assert result["regression_detected"] is None
        assert "mismatch" in result["reason"].lower()

    def test_compare_runs_chain(self, detector):
        runs = [
            make_run([0.9, 0.9]),
            make_run([0.8, 0.8]),
            make_run([0.5, 0.4]),
        ]

        comparisons = detector.compare_runs(runs)

        assert len(comparisons) == 2

        # Last comparison should show regression
        assert comparisons[0]["regression_detected"] is True
