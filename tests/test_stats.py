"""Statistical helpers: bootstrap CI, McNemar, Cohen's d, power."""

from evalbench.core.stats import (
    bootstrap_ci,
    cohens_d,
    mcnemar,
    samples_for_mde,
)


class TestBootstrapCI:
    def test_none_below_two_values(self):
        assert bootstrap_ci([]) is None
        assert bootstrap_ci([1.0]) is None

    def test_ci_brackets_the_mean(self):
        vals = [0.8, 0.85, 0.9, 0.82, 0.88, 0.79, 0.91, 0.86]
        lo, hi = bootstrap_ci(vals)
        assert lo <= sum(vals) / len(vals) <= hi
        assert lo < hi

    def test_all_ones_is_degenerate(self):
        assert bootstrap_ci([1, 1, 1, 1, 1]) == (1.0, 1.0)

    def test_deterministic_with_seed(self):
        v = [0.1, 0.9, 0.5, 0.3, 0.7]
        assert bootstrap_ci(v, seed=1) == bootstrap_ci(v, seed=1)


class TestMcNemar:
    def test_none_on_mismatch_or_empty(self):
        assert mcnemar([], []) is None
        assert mcnemar([True], [True, False]) is None

    def test_no_discordant_pairs(self):
        r = mcnemar([True, True, False], [True, True, False])
        assert r["discordant"] == 0
        assert r["p_value"] == 1.0

    def test_counts_regressions_and_fixes(self):
        base = [True, True, True, False, True]
        curr = [False, True, True, True, False]  # 2 regress, 1 fix
        r = mcnemar(base, curr)
        assert r["regressions"] == 2
        assert r["fixes"] == 1
        assert r["net_change"] == -1

    def test_strong_regression_is_significant(self):
        base = [True] * 12
        curr = [False] * 10 + [True] * 2
        assert mcnemar(base, curr)["p_value"] < 0.05


class TestCohensD:
    def test_none_below_two(self):
        assert cohens_d([0.9], [0.8]) is None

    def test_zero_when_no_change(self):
        assert cohens_d([0.9, 0.8, 0.7], [0.9, 0.8, 0.7]) == 0.0

    def test_negative_for_a_drop(self):
        d = cohens_d([0.9, 0.9, 0.9, 0.9], [0.6, 0.65, 0.55, 0.6])
        assert d < 0


class TestSamplesForMDE:
    def test_none_on_bad_input(self):
        assert samples_for_mde(0.0) is None
        assert samples_for_mde(0.1, mde=0) is None

    def test_smaller_effect_needs_more_samples(self):
        assert samples_for_mde(0.2, mde=0.02) > samples_for_mde(0.2, mde=0.1)
