"""How small a change a benchmark can actually detect.

`research/REPORT.md` measured what happens when an eval suite is too
small: at ten tests, a genuine regression is caught about 21% of the
time. Left as a report, that is a fact someone might read once. Attached
to each benchmark, it becomes the number that decides whether a result
means anything.

The estimate is deliberately empirical. Two runs of the same benchmark
against the same model do not score identically — judges wobble, sampling
wobbles, providers time out — and it is the size of that wobble, not the
number of tests, that sets the floor on what a comparison can see. So the
spread is measured from the benchmark's own run history, and a benchmark
that has not been run twice reports no resolution rather than a guess.
"""

from __future__ import annotations

from dataclasses import dataclass

from evalbench.core.stats import mde_for_n

# A comparison is only as good as the tests both runs actually scored.
MIN_PAIRS = 2


@dataclass
class Resolution:
    """What a benchmark can resolve, and why it can't when it can't."""

    mde: float | None
    """Smallest detectable mean shift, as a score fraction (0.08 = 8 points)."""

    runs_used: int
    tests: int
    reason: str | None = None
    """Set when ``mde`` is None: what is missing, in the user's words."""


def _scores(run: dict) -> dict[str, float]:
    """Test name → score, for tests this run actually scored.

    "Errored" means no sample produced a score — the rule the summary and
    the run lists use. An `error` string alone is not enough: a test that
    lost one sample to a rate limit and was answered on another has both
    an error and a perfectly good score, and discarding it threw away
    most of the evidence. On real data that left a 51-test benchmark
    reporting "too few tests scored in both runs" when 26 of them were
    scored in one and 16 in the other.

    A test that genuinely never answered is dropped rather than read as
    zero, which would invent a swing the model never produced.
    """
    out: dict[str, float] = {}
    for r in run.get("results") or []:
        name, score = r.get("test_name"), r.get("score")
        errored = bool(r.get("error")) and not r.get("runs", 0)
        if name and score is not None and not errored:
            out[name] = float(score)
    return out


def resolution_from_runs(runs: list[dict]) -> Resolution:
    """Estimate the benchmark's resolution from its own run history.

    Consecutive runs are paired by test name — never by position, since a
    benchmark that gained or lost a test would otherwise compare
    unrelated prompts and manufacture variance. Every pair's per-test
    differences are pooled, and their spread drives the power
    calculation.
    """
    usable = [
        r for r in runs
        if r.get("status") == "completed" and r.get("results")
    ]
    usable.sort(key=lambda r: r.get("created_at") or "")

    if not usable:
        return Resolution(None, 0, 0, "Not yet measured — run it once.")
    if len(usable) < 2:
        return Resolution(
            None,
            1,
            len(_scores(usable[0])),
            "Needs a second run — one measurement cannot show its own spread.",
        )

    diffs: list[float] = []
    paired_tests = 0
    for before, after in zip(usable, usable[1:], strict=False):
        a, b = _scores(before), _scores(after)
        shared = a.keys() & b.keys()
        paired_tests = len(shared)  # the most recent pair is the honest n
        diffs.extend(b[name] - a[name] for name in shared)

    if len(diffs) < MIN_PAIRS:
        return Resolution(
            None,
            len(usable),
            paired_tests,
            "Too few tests scored in both runs to estimate the spread.",
        )

    mean = sum(diffs) / len(diffs)
    var = sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1)
    mde = mde_for_n(paired_tests, var ** 0.5)

    if mde is None:
        # Every paired difference was exactly zero. State the observation
        # rather than a cause: a deterministic suite (temperature 0, cheap
        # string checks) genuinely does not move, and a stochastic one
        # that happened to hold still looks identical from here. Either
        # way there is no spread to turn into a floor.
        return Resolution(
            None,
            len(usable),
            paired_tests,
            f"Identical scores across {len(usable)} runs — no spread to "
            "measure yet.",
        )
    return Resolution(mde, len(usable), paired_tests)
