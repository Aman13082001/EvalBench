"""Small statistical helpers for run summaries and regression checks.

Kept deliberately dependency-light: `scipy.stats` (already a dependency)
for the normal / binomial quantiles, everything else by hand.
"""

from __future__ import annotations

import math
import random

from scipy import stats


def bootstrap_ci(
    values: list[float],
    n_resamples: int = 2000,
    confidence: float = 0.95,
    seed: int = 0,
) -> tuple[float, float] | None:
    """Percentile bootstrap CI for the mean of ``values``.

    Pass a list of 0/1 to get a CI on a pass rate. Returns ``None`` when
    there are fewer than 2 values.
    """
    vals = [float(v) for v in values]
    if len(vals) < 2:
        return None

    rng = random.Random(seed)
    n = len(vals)
    means = sorted(
        sum(vals[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(n_resamples)
    )
    lo_i = int(((1 - confidence) / 2) * n_resamples)
    hi_i = min(int((1 - (1 - confidence) / 2) * n_resamples), n_resamples - 1)
    return round(means[lo_i], 4), round(means[hi_i], 4)


def mcnemar(
    baseline_pass: list[bool], current_pass: list[bool]
) -> dict | None:
    """Exact (binomial) McNemar test on paired pass/fail vectors.

    ``b`` = passed in baseline, failed now (regressions);
    ``c`` = failed in baseline, passed now (fixes).
    """
    if len(baseline_pass) != len(current_pass) or not baseline_pass:
        return None

    pairs = list(zip(baseline_pass, current_pass, strict=True))
    b = sum(1 for x, y in pairs if x and not y)
    c = sum(1 for x, y in pairs if y and not x)
    n = b + c
    if n == 0:
        p = 1.0
    else:
        p = float(
            stats.binomtest(min(b, c), n, 0.5, alternative="two-sided").pvalue
        )
    return {
        "regressions": b,
        "fixes": c,
        "discordant": n,
        "p_value": round(p, 6),
        "net_change": c - b,
    }


def cohens_d(baseline: list[float], current: list[float]) -> float | None:
    """Paired Cohen's d: mean of differences over their standard deviation."""
    if len(baseline) != len(current) or len(baseline) < 2:
        return None

    diffs = [c - b for b, c in zip(baseline, current, strict=True)]
    mean = sum(diffs) / len(diffs)
    var = sum((x - mean) ** 2 for x in diffs) / (len(diffs) - 1)
    sd = var ** 0.5
    if sd == 0:
        return 0.0
    return round(mean / sd, 4)


def mde_for_n(
    n: int,
    std: float,
    power: float = 0.8,
    alpha: float = 0.05,
) -> float | None:
    """The smallest mean shift ``n`` paired tests can detect, at ``power``.

    The inverse of :func:`samples_for_mde`, and the number a benchmark
    reports as its resolution: "a drop smaller than this is invisible to
    this suite". Note the square root — quadrupling a suite only halves
    what it can see, which is why "add a few more tests" rarely rescues
    an underpowered benchmark.

    ``None`` when there is nothing to base it on: fewer than two paired
    tests, or no observed spread at all (zero variance across a handful
    of runs is an artefact, not infinite precision).
    """
    if n < 2 or std <= 0:
        return None
    z_a = float(stats.norm.ppf(1 - alpha / 2))
    z_b = float(stats.norm.ppf(power))
    return round((z_a + z_b) * std / math.sqrt(n), 4)


def samples_for_mde(
    std: float,
    mde: float = 0.05,
    power: float = 0.8,
    alpha: float = 0.05,
) -> int | None:
    """Paired-sample size (per test) to detect a mean shift of ``mde``.

    A back-of-envelope power calculation — enough to answer "is my suite
    big enough to trust a 5-point move?".
    """
    if std <= 0 or mde <= 0:
        return None
    z_a = float(stats.norm.ppf(1 - alpha / 2))
    z_b = float(stats.norm.ppf(power))
    n = ((z_a + z_b) * std / mde) ** 2
    return max(2, math.ceil(n))
