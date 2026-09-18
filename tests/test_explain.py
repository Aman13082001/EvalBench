"""The plain-language layer must stay honest, not just readable.

Softening a real regression into friendly words would be worse than the
jargon it replaces, so these tests pin the meaning as well as the tone.
"""

import pathlib
import re

import pytest

from evalbench.explain import (
    explain_assertion,
    explain_comparison,
    explain_run,
)


class TestAssertions:
    @pytest.mark.parametrize(
        "atype",
        [
            "exact", "equals", "contains", "icontains", "regex",
            "json-schema", "semantic", "judge", "llm-rubric", "latency",
            "cost", "faithfulness", "context-recall", "context-precision",
        ],
    )
    def test_every_assertion_type_has_wording(self, atype):
        """A type with no sentence falls back to "Passed this check",
        which tells the reader nothing. Every real type needs words."""
        for passed in (True, False):
            text = explain_assertion(atype, passed=passed)
            assert text not in ("Passed this check.", "Failed this check.")
            assert text[0].isupper() and text.endswith(".")

    def test_unknown_type_still_returns_something(self):
        assert explain_assertion("brand-new-check", passed=True)

    def test_no_jargon_leaks_into_the_sentences(self):
        """The point is to avoid the terms, not repeat them."""
        banned = ("cosine", "p_value", "pass_rate", "threshold", "mde")
        for atype in ("semantic", "faithfulness", "context-precision"):
            for passed in (True, False):
                text = explain_assertion(atype, passed=passed).lower()
                assert not any(b in text for b in banned), text


class TestRun:
    def test_counts_are_reported_plainly(self):
        text = explain_run(
            {"scored_tests": 6, "passed": 5, "errors": 0}
        )
        assert "5 out of 6" in text

    def test_errors_are_called_out_as_not_the_models_fault(self):
        text = explain_run({"scored_tests": 6, "passed": 5, "errors": 2})
        assert "2 test" in text
        assert "not the model" in text.lower()

    def test_nothing_scored(self):
        assert "No tests" in explain_run({"scored_tests": 0, "passed": 0})


class TestComparison:
    def test_insignificant_difference_is_called_noise(self):
        """The case that prompted this: 5.3 points apart, p = 0.43."""
        text = explain_comparison(
            {
                "mean_diff": 0.0526,
                "p_value": 0.429,
                "test_count": 19,
                "regression_detected": False,
                "min_samples_for_5pt_mde": 253,
            }
        )
        assert "5.3 points" in text
        assert "not a real change" in text
        # and it should say what would be needed instead
        assert "253" in text

    def test_significant_difference_is_not_softened(self):
        text = explain_comparison(
            {
                "mean_diff": 0.22,
                "p_value": 0.001,
                "test_count": 80,
                "regression_detected": False,
            }
        )
        assert "real difference" in text
        assert "not a real change" not in text

    def test_a_detected_regression_says_so_bluntly(self):
        text = explain_comparison(
            {
                "mean_diff": -0.18,
                "p_value": 0.004,
                "test_count": 60,
                "regression_detected": True,
            }
        )
        assert "really did drop" in text
        assert "worse" in text
        assert "investigat" in text

    def test_missing_data_does_not_invent_a_verdict(self):
        text = explain_comparison({"mean_diff": None})
        assert "Not enough" in text


def test_cli_and_web_wording_stay_in_step():
    """web/lib/explain.ts is the same layer for the website. If the two
    drift, the same result reads differently depending on where you look
    at it — which is worse than having only one of them."""
    ts = pathlib.Path(__file__).resolve().parents[1] / "web" / "lib" / "explain.ts"
    if not ts.exists():
        pytest.skip("web app not present")
    web = ts.read_text(encoding="utf-8")

    for atype in ("faithfulness", "context-recall", "semantic", "cost"):
        for passed in (True, False):
            sentence = explain_assertion(atype, passed=passed)
            # compare on the distinctive opening words, ignoring wrapping
            head = " ".join(re.findall(r"[A-Za-z']+", sentence)[:5])
            assert head in " ".join(web.split()), (
                f"CLI wording for {atype}/{passed} has no match in "
                f"explain.ts: {sentence!r}"
            )


def test_supplied_answers_do_not_blame_the_provider():
    """Nothing was called, so "a connection problem" is the wrong story
    for a test that was simply absent from the file."""
    from evalbench.explain import explain_run

    text = explain_run({"provider": "answers", "scored_tests": 3, "passed": 2, "errors": 1})
    assert "no answer in the file" in text
    assert "provider" not in text
