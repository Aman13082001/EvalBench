import math

from scipy import stats

from evalbench.db.schemas import TestRun


class RegressionDetector:
    def __init__(self, threshold: float = 0.05):
        self.threshold = threshold

    def _safe_float(self, val):
        """Convert numpy float to Python float, handling nan/inf."""
        if val is None:
            return None

        f = float(val)

        if math.isnan(f) or math.isinf(f):
            return None

        return round(f, 6)

    def _per_test(self, baseline: TestRun, current: TestRun) -> list[dict]:
        """Score delta for each test, aligned by position."""
        if len(baseline.results) != len(current.results):
            return []
        rows = []
        for b, c in zip(baseline.results, current.results, strict=True):
            bs = self._safe_float(b.score) if b.score is not None else None
            cs = self._safe_float(c.score) if c.score is not None else None
            delta = None
            regressed = False
            if bs is not None and cs is not None:
                delta = round(cs - bs, 6)
                regressed = delta < -0.05
            rows.append({
                "test_name": c.test_name,
                "baseline_score": bs,
                "current_score": cs,
                "delta": delta,
                "regressed": regressed,
            })
        return rows

    def compare(self, baseline: TestRun, current: TestRun) -> dict:
        per_test = self._per_test(baseline, current)

        baseline_scores = [
            r.score
            for r in baseline.results
            if r.score is not None
        ]

        current_scores = [
            r.score
            for r in current.results
            if r.score is not None
        ]

        if len(baseline_scores) != len(current_scores):
            return {
                "regression_detected": None,
                "reason": "Test count mismatch or missing scores",
                "baseline_count": len(baseline_scores),
                "current_count": len(current_scores),
                "per_test": per_test,
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
                        if current_scores
                        else 0
                    )
                    -
                    (
                        sum(baseline_scores) / len(baseline_scores)
                        if baseline_scores
                        else 0
                    )
                ),
                "t_statistic": None,
                "p_value": None,
                "significant": False,
                "test_count": len(baseline_scores),
                "per_test": per_test,
            }

        baseline_mean = sum(baseline_scores) / len(baseline_scores)
        current_mean = sum(current_scores) / len(current_scores)
        mean_diff = current_mean - baseline_mean

        # Paired differences
        differences = [
            current - baseline
            for baseline, current in zip(
                baseline_scores,
                current_scores,
                strict=True,
            )
        ]

        # If every test changed by exactly the same amount,
        # scipy's paired t-test cannot calculate variance.
        # In that case, use the mean difference directly.
        differences_identical = all(
            math.isclose(
                diff,
                differences[0],
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            for diff in differences
        )

        if differences_identical:
            if mean_diff < -0.05:
                regression_detected = True
                significant = True
                reason = (
                    "Consistent score decrease across all tests"
                )
            else:
                regression_detected = False
                significant = False
                reason = (
                    "No significant score decrease"
                )

            return {
                "regression_detected": regression_detected,
                "baseline_mean": self._safe_float(baseline_mean),
                "current_mean": self._safe_float(current_mean),
                "mean_diff": self._safe_float(mean_diff),
                "t_statistic": None,
                "p_value": 0.0 if significant else None,
                "significant": significant,
                "test_count": len(baseline_scores),
                "reason": reason,
                "per_test": per_test,
            }

        # Normal case: paired t-test
        t_stat, p_value = stats.ttest_rel(
            baseline_scores,
            current_scores,
        )

        t_stat_safe = self._safe_float(t_stat)
        p_value_safe = self._safe_float(p_value)
        mean_diff_safe = self._safe_float(mean_diff)

        if t_stat_safe is None or p_value_safe is None:
            regression_detected = False
            significant = False
            reason = "Unable to determine statistical significance"
        else:
            significant = bool(
                p_value_safe < self.threshold
            )

            regression_detected = bool(
                mean_diff_safe < -0.05
                and significant
            )

            reason = None

        return {
            "regression_detected": regression_detected,
            "baseline_mean": self._safe_float(baseline_mean),
            "current_mean": self._safe_float(current_mean),
            "mean_diff": mean_diff_safe,
            "t_statistic": t_stat_safe,
            "p_value": p_value_safe,
            "significant": significant,
            "test_count": len(baseline_scores),
            "reason": reason,
            "per_test": per_test,
        }

    def compare_runs(self, runs: list[TestRun]) -> list[dict]:
        """
        Compare each run against the immediately previous run.

        Example:
            run1 -> run2
            run2 -> run3
        """
        if len(runs) < 2:
            return []

        comparisons = []

        for i in range(1, len(runs)):
            baseline = runs[i - 1]
            current = runs[i]

            comparison = self.compare(
                baseline,
                current,
            )

            comparisons.append(comparison)

        return comparisons
