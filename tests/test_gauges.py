"""What the gauges are allowed to claim.

The dashboard and the run report describe the same run, so they must not
compute it differently — and an alert rule reads the gauges, so a wrong
number there wakes somebody up.

Two things went wrong. `pass_rate` fell back to 0.0 when nothing scored,
so a provider outage — zero answers, nothing measured — published a 0%
pass rate and tripped `evalbench_pass_rate < 0.75`: paged for a model
quality collapse that never happened, on a number nobody computed. And
`avg_latency` averaged over every result while the API summary averaged
over scored ones only, because a timed-out request's latency is the
timeout, not the model. Same run, two answers.

A gauge with nothing to say must say nothing. Prometheus handles an
absent series; it cannot handle a fabricated one.
"""

import pytest

from evalbench.core.runner import publishable_metrics


def _r(passed, score, latency, error=None, runs=1):
    return {"passed": passed, "score": score, "latency_ms": latency,
            "error": error, "runs": runs}


class TestNothingScored:
    def test_pass_rate_is_absent_rather_than_zero(self):
        """0% means "every answer was wrong". Nothing scored means "we
        could not measure" — the alert rule cannot tell those apart, so
        the gauge must not offer the first when it means the second."""
        m = publishable_metrics([_r(False, None, 0, error="boom", runs=0)])
        assert "pass_rate" not in m
        assert "avg_score" not in m

    def test_an_empty_run_publishes_nothing(self):
        assert publishable_metrics([]) == {}

    def test_latency_is_absent_too(self):
        m = publishable_metrics([_r(False, None, 30000, error="timeout", runs=0)])
        assert "avg_latency_ms" not in m


class TestScoredRuns:
    def test_the_ordinary_case_publishes_everything(self):
        m = publishable_metrics([_r(True, 1.0, 100), _r(False, 0.0, 300)])
        assert m["pass_rate"] == 0.5
        assert m["avg_score"] == 0.5
        assert m["avg_latency_ms"] == 200

    def test_latency_ignores_tests_that_never_answered(self):
        """A request that timed out at 30s reports the timeout, not the
        model's speed. Averaging it in publishes the provider's bad day
        as the model being slow."""
        m = publishable_metrics([_r(True, 1.0, 100), _r(False, None, 30000,
                                                        error="timeout", runs=0)])
        assert m["avg_latency_ms"] == 100

    def test_a_partly_rate_limited_test_still_counts(self):
        """It has an error string but answered on another sample, so it
        was measured — the same rule the summary uses."""
        m = publishable_metrics([
            _r(True, 1.0, 100),
            _r(False, 0.0, 200, error="rate limited", runs=2),
        ])
        assert m["pass_rate"] == 0.5
        assert m["avg_latency_ms"] == 150


class TestItAgreesWithTheSummary:
    @pytest.mark.parametrize("results", [
        [_r(True, 1.0, 100), _r(False, 0.0, 300)],
        [_r(True, 1.0, 50), _r(False, None, 9000, error="timeout", runs=0)],
        [_r(True, 0.5, 10), _r(True, 1.0, 20), _r(False, 0.0, 30)],
    ])
    def test_same_run_same_numbers(self, results):
        """The gauge and the run report are two views of one run. If they
        disagree, one of them is lying and the reader cannot tell which."""
        from evalbench.api.summary import summarize_run

        gauge = publishable_metrics(results)
        report = summarize_run({"results": results})

        assert gauge.get("pass_rate") == report["pass_rate"]
        assert gauge.get("avg_score") == report["avg_score"]
        assert gauge.get("avg_latency_ms") == report["avg_latency_ms"]


class TestTheReportSaysTheSame:
    def test_a_run_where_nothing_scored_reports_no_rate(self):
        """"0%" is a measurement — it says every answer was wrong. A run
        where no answer arrived has not measured anything, and the report
        has to be able to say so rather than pick a number."""
        from evalbench.api.summary import summarize_run

        s = summarize_run({"results": [
            {"test_name": "a", "error": "timeout", "runs": 0},
            {"test_name": "b", "error": "timeout", "runs": 0},
        ]})
        assert s["pass_rate"] is None
        assert s["avg_score"] is None
        assert s["avg_latency_ms"] is None
        assert s["errors"] == 2 and s["scored_tests"] == 0

    def test_a_normal_run_is_unaffected(self):
        from evalbench.api.summary import summarize_run

        s = summarize_run({"results": [
            {"test_name": "a", "passed": True, "score": 1.0, "latency_ms": 10},
            {"test_name": "b", "passed": False, "score": 0.0, "latency_ms": 30},
        ]})
        assert s["pass_rate"] == 0.5 and s["avg_latency_ms"] == 20
