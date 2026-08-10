import math
from typing import List

from scipy import stats
from evalbench.db.schemas import TestRun


class RegressionDetector:
    def __init__(self, threshold: float = 0.05):
        self.threshold = threshold

    def _safe_float(self, val):
        """Convert numpy float to Python float, handling nan/inf"""
        if val is None:
            return None

        f = float(val)

        if math.isnan(f) or math.isinf(f):
            return None

        return round(f, 6)

    def compare(self, baseline: TestRun, current: TestRun) -> dict:
        baseline_scores = [
            r.score for r in baseline.results
            if r.score is not None
        ]

        current_scores = [
            r.score for r in current.results
            if r.score is not None
        ]

        if len(baseline_scores) != len(current_scores):
            return {
                "regression_detected": None,
                "reason": "Test count mismatch or missing scores",
                "baseline_count": len(baseline_scores),
                "current_count": len(current_scores),
            }

        if len(baseline_scores) < 2:
            return {
                "regression_detected": False,
                "reason": "Insufficient data (need 2+ scored tests)",
                "baseline_mean": self._safe_float(
                    sum(baseline_scores) / len(baseline_scores)
                ) if baseline_scores else 0,
                "current_mean": self._safe_float(
                    sum(current_scores) / len(current_scores)
                ) if current_scores else 0,
                "mean_diff": self._safe_float(
                    (
                        sum(current_scores) / len(current_scores)
                        if current_scores else 0
                    )
                    -
                    (
                        sum(baseline_scores) / len(baseline_scores)
                        if baseline_scores else 0
                    )
                ),
                "t_statistic": None,
                "p_value": None,
                "significant": False,
                "test_count": len(baseline_scores),
            }

        # Paired t-test
        t_stat, p_value = stats.ttest_rel(
            baseline_scores,
            current_scores
        )

        baseline_mean = sum(baseline_scores) / len(baseline_scores)
        current_mean = sum(current_scores) / len(current_scores)
        mean_diff = current_mean - baseline_mean

        t_stat_safe = self._safe_float(t_stat)
        p_value_safe = self._safe_float(p_value)
        mean_diff_safe = self._safe_float(mean_diff)

        if t_stat_safe is None or p_value_safe is None:
            regression_detected = False
            reason = "Identical scores — no variance to measure"
        else:
            regression_detected = bool(
                (mean_diff_safe < -0.05)
                and
                (p_value_safe < self.threshold)
            )
            reason = None

        return {
            "regression_detected": regression_detected,
            "baseline_mean": self._safe_float(baseline_mean),
            "current_mean": self._safe_float(current_mean),
            "mean_diff": mean_diff_safe,
            "t_statistic": t_stat_safe,
            "p_value": p_value_safe,
            "significant": (
                bool(p_value_safe < self.threshold)
                if p_value_safe is not None
                else False
            ),
            "test_count": len(baseline_scores),
            "reason": reason,
        }

    def compare_runs(self, runs: List[TestRun]) -> List[dict]:
        if len(runs) < 2:
            return []

        baseline = runs[-1]
        comparisons = []

        for current in runs[:-1][::-1]:
            comp = self.compare(baseline, current)
            comparisons.append(comp)

        return comparisons