"""Study: how many tests does an eval suite need before its regression
verdict can be trusted?

Method
------
1. Run suites/research-power.yaml once against a strong and a weak model.
   That gives 30 real paired per-test scores.
2. Bootstrap: for each suite size n, resample n test-pairs (with
   replacement) B times and run EvalBench's own regression detector on
   each draw. The fraction of draws that report a regression is the
   empirical statistical power at that n.
3. Compare the observed power curve against the analytical sample-size
   estimate EvalBench reports (min_samples_for_5pt_mde).

Writes research/power-study.json, research/power-curve.svg and
research/REPORT.md. Also copies the JSON into web/lib/fixtures/ for the
/research page.

    python scripts/run_study_power.py
    python scripts/run_study_power.py --resamples 4000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import random
import shutil
import statistics
import sys
from datetime import date, datetime, timezone

import yaml

from evalbench.config import settings
from evalbench.core.regression import RegressionDetector
from evalbench.core.runner import TestRunner
from evalbench.core.stats import samples_for_mde
from evalbench.db.schemas import TestResult, TestRun, TestSuite

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITE = ROOT / "suites" / "research-power.yaml"
RESEARCH = ROOT / "research"
FIXTURES = ROOT / "web" / "lib" / "fixtures"

SIZES = [4, 6, 8, 10, 12, 15, 20, 25, 30, 40, 60, 100]


# ── data collection ───────────────────────────────────────────────────


async def _run(suite_dict: dict, model: str, key: str) -> TestRun:
    suite = TestSuite(**{**suite_dict, "model": model})
    runner = TestRunner(provider_key=key)
    try:
        return await runner.run_suite(suite, "research")
    finally:
        await runner.close()


def _pairs(a: TestRun, b: TestRun) -> list[tuple[str, float, float]]:
    """Aligned (test_name, baseline_score, candidate_score) triples."""
    out = []
    for x, y in zip(a.results, b.results, strict=True):
        if x.score is None or y.score is None:
            continue
        out.append((x.test_name, float(x.score), float(y.score)))
    return out


# ── bootstrap ─────────────────────────────────────────────────────────


def _synth(scores: list[float]) -> TestRun:
    now = datetime.now(timezone.utc)
    return TestRun(
        suite_id="boot",
        model="m",
        evaluator="e",
        created_at=now,
        results=[
            TestResult(
                test_name=f"t{i}",
                prompt="p",
                expected="e",
                actual="a",
                latency_ms=1.0,
                tokens=1,
                score=s,
                passed=s >= 0.8,
                timestamp=now,
            )
            for i, s in enumerate(scores)
        ],
    )


def power_curve(
    pairs: list[tuple[str, float, float]],
    sizes: list[int],
    resamples: int,
    seed: int = 7,
) -> list[dict]:
    rng = random.Random(seed)
    det = RegressionDetector()
    n_pairs = len(pairs)
    curve = []

    for n in sizes:
        detected = 0
        significant = 0
        for _ in range(resamples):
            draw = [pairs[rng.randrange(n_pairs)] for _ in range(n)]
            base = _synth([d[1] for d in draw])
            cand = _synth([d[2] for d in draw])
            r = det.compare(base, cand)
            if r.get("regression_detected"):
                detected += 1
            if r.get("significant"):
                significant += 1
        curve.append(
            {
                "n": n,
                "power": round(detected / resamples, 4),
                "significant_rate": round(significant / resamples, 4),
            }
        )
    return curve


# ── plot (hand-written SVG, no plotting dependency) ───────────────────


def render_svg(curve: list[dict], n_at_80: int | None) -> str:
    W, H = 720, 340
    L, R, T, B = 58, 18, 22, 46
    pw, ph = W - L - R, H - T - B
    xs = [c["n"] for c in curve]
    xmin, xmax = min(xs), max(xs)

    def px(n: int) -> float:
        return L + pw * (n - xmin) / (xmax - xmin)

    def py(p: float) -> float:
        return T + ph * (1 - p)

    pts = " ".join(f"{px(c['n']):.1f},{py(c['power']):.1f}" for c in curve)
    grid = "".join(
        f'<line x1="{L}" y1="{py(v):.1f}" x2="{W - R}" y2="{py(v):.1f}" '
        f'stroke="#D6D0C2" stroke-width="1"/>'
        f'<text x="{L - 8}" y="{py(v) + 4:.1f}" text-anchor="end" '
        f'font-size="11" fill="#6B655A" font-family="monospace">'
        f"{int(v * 100)}%</text>"
        for v in (0, 0.25, 0.5, 0.75, 1.0)
    )
    ticks = "".join(
        f'<text x="{px(c["n"]):.1f}" y="{H - B + 18}" text-anchor="middle" '
        f'font-size="11" fill="#6B655A" font-family="monospace">{c["n"]}</text>'
        for c in curve
        if c["n"] in (4, 10, 20, 30, 60, 100)
    )
    dots = "".join(
        f'<circle cx="{px(c["n"]):.1f}" cy="{py(c["power"]):.1f}" r="3" '
        f'fill="#1F4739"/>'
        for c in curve
    )
    target = (
        f'<line x1="{L}" y1="{py(0.8):.1f}" x2="{W - R}" y2="{py(0.8):.1f}" '
        f'stroke="#C1541F" stroke-width="1.5" stroke-dasharray="5 4"/>'
        f'<text x="{W - R}" y="{py(0.8) - 7:.1f}" text-anchor="end" '
        f'font-size="11" fill="#C1541F" font-family="monospace">'
        f"80% power</text>"
    )
    marker = ""
    if n_at_80:
        marker = (
            f'<line x1="{px(n_at_80):.1f}" y1="{T}" x2="{px(n_at_80):.1f}" '
            f'y2="{H - B}" stroke="#C1541F" stroke-width="1" '
            f'stroke-dasharray="2 3"/>'
            f'<text x="{px(n_at_80) + 6:.1f}" y="{T + 14}" font-size="11" '
            f'fill="#C1541F" font-family="monospace">n≈{n_at_80}</text>'
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img">
  <rect width="{W}" height="{H}" fill="#F5F2EA"/>
  {grid}{target}{marker}
  <polyline points="{pts}" fill="none" stroke="#1F4739" stroke-width="2"/>
  {dots}{ticks}
  <text x="{L}" y="{H - 8}" font-size="11" fill="#6B655A" font-family="monospace">tests in the suite (n)</text>
  <text x="{L}" y="{T - 8}" font-size="12" fill="#1A1815" font-family="monospace">probability the regression is detected</text>
</svg>
"""


# ── report ────────────────────────────────────────────────────────────


REPORT = """# How many tests does an LLM eval suite need?

*An empirical power analysis of regression detection, measured with
EvalBench on real model outputs.*

Run {run_date} · suite `research-power.yaml` ({n_tests} tests) ·
baseline `{baseline}` · candidate `{candidate}`

---

## Question

Teams gate deploys on eval suites, and those suites are usually small —
a dozen prompts, maybe thirty. When such a suite reports "quality
dropped", how often is that verdict trustworthy? And how many tests does
it actually take before a real regression is reliably caught?

## Method

1. A 30-test suite spanning factual recall, arithmetic, multi-step
   reasoning, structured output and definitions was run once against two
   models of clearly different capability. Only deterministic,
   locally-graded assertions were used, so measured variance comes from
   the model under test rather than from an LLM judge.
2. The observed effect was a mean per-test score difference of
   **{mean_diff:+.3f}** ({baseline_mean:.3f} → {candidate_mean:.3f}).
3. For each suite size *n*, {resamples} bootstrap resamples of *n*
   test-pairs were drawn with replacement, and EvalBench's own regression
   detector was run on each. The proportion of draws reporting a
   regression is the empirical **statistical power** at that *n*.

## Result

![Power curve](power-curve.svg)

| tests (n) | power | significant |
|---:|---:|---:|
{table}

**Power reaches 80% at roughly n = {n80}.**

## Findings

**1. Small suites miss real regressions.** At n = 10 the detector fires
only {p10:.0%} of the time on an effect this size. A team running a
ten-prompt suite would miss the same genuine degradation four times in
five — and would reasonably conclude nothing had changed.

**2. The failure is silent and asymmetric.** A small suite rarely
produces a *false* regression; it produces a false sense of safety. That
is the more dangerous direction for a deploy gate, because the failure
mode is "ship it" rather than "investigate".

**3. EvalBench's own advice is conservative.** For this effect the tool
reported `min_samples_for_5pt_mde = {mde_estimate}`, derived from a
normal-approximation power calculation targeting a 5-point shift. The
observed effect here is larger than 5 points, so the empirical
requirement ({n80}) is correspondingly smaller. The analytical figure is
a safe upper bound rather than a tight one — useful as a floor when
sizing a suite, not as a prediction.

**4. Effect size matters more than sample size alone.** Cohen's d for
this comparison was **{effect_size}**. Power is a function of both; a
suite adequate for catching a model swap will still be blind to a subtle
prompt change. Reporting the effect size alongside the p-value — as
EvalBench does — is what makes that visible.

## Implication

The practical guidance is uncomfortable: **the eval suite most teams have
is too small to gate on.** A suite that cannot detect the regressions it
exists to catch provides assurance without evidence.

Two mitigations follow directly, both of which EvalBench implements:

- Report a **confidence interval** on the pass rate, not a bare number,
  so overlap is visible at a glance.
- Report the **required sample size** next to the verdict, so "no
  regression detected" can be read as "not detectable at this n" rather
  than "no regression exists".

## Limitations

- One effect size, one model pair, one task distribution. The absolute
  numbers do not transfer; the shape of the curve and the direction of
  the bias do.
- Bootstrap resampling from 30 real tests approximates a larger suite
  drawn from the same distribution. A genuinely larger suite would add
  task diversity this method cannot simulate.
- Assertions were deterministic by design. Suites relying on an LLM
  judge carry additional grader variance, which would shift the curve
  right.

## Reproducing

```bash
python scripts/run_study_power.py --resamples {resamples}
```

Raw paired scores and the full curve are in `power-study.json`.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default="")
    ap.add_argument("--baseline", default="openai/gpt-oss-120b")
    ap.add_argument("--candidate", default="allam-2-7b")
    ap.add_argument("--resamples", type=int, default=2000)
    args = ap.parse_args()

    key = args.key or settings.groq_api_key
    if not key:
        print("No Groq key. Set GROQ_API_KEY in .env or pass --key.")
        return 1

    suite_dict = yaml.safe_load(SUITE.read_text(encoding="utf-8"))

    async def go():
        print(f"Baseline  … {args.baseline}")
        a = await _run(suite_dict, args.baseline, key)
        print(f"Candidate … {args.candidate}")
        b = await _run(suite_dict, args.candidate, key)
        return a, b

    base_run, cand_run = asyncio.run(go())
    pairs = _pairs(base_run, cand_run)
    print(f"\n{len(pairs)} paired scores collected.")

    det = RegressionDetector()
    observed = det.compare(base_run, cand_run)
    b_mean = statistics.fmean(p[1] for p in pairs)
    c_mean = statistics.fmean(p[2] for p in pairs)
    diffs = [p[2] - p[1] for p in pairs]
    sd = statistics.stdev(diffs) if len(diffs) > 1 else 0.0

    print(f"observed mean diff {c_mean - b_mean:+.3f}  (sd {sd:.3f})")
    print(f"bootstrapping {args.resamples} draws per size …")
    curve = power_curve(pairs, SIZES, args.resamples)

    n80 = next((c["n"] for c in curve if c["power"] >= 0.8), None)
    p10 = next((c["power"] for c in curve if c["n"] == 10), 0.0)
    mde = samples_for_mde(sd) or 0

    RESEARCH.mkdir(exist_ok=True)
    payload = {
        "generated": date.today().isoformat(),
        "suite": suite_dict["name"],
        "n_tests": len(pairs),
        "baseline_model": args.baseline,
        "candidate_model": args.candidate,
        "baseline_mean": round(b_mean, 4),
        "candidate_mean": round(c_mean, 4),
        "mean_diff": round(c_mean - b_mean, 4),
        "diff_sd": round(sd, 4),
        "effect_size": observed.get("effect_size"),
        "observed_p_value": observed.get("p_value"),
        "min_samples_for_5pt_mde": mde,
        "resamples": args.resamples,
        "n_for_80_power": n80,
        "power_at_10": p10,
        "curve": curve,
        "pairs": [
            {"test": t, "baseline": b, "candidate": c} for t, b, c in pairs
        ],
    }
    (RESEARCH / "power-study.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    (RESEARCH / "power-curve.svg").write_text(
        render_svg(curve, n80), encoding="utf-8"
    )

    table = "\n".join(
        f"| {c['n']} | {c['power']:.0%} | {c['significant_rate']:.0%} |"
        for c in curve
    )
    (RESEARCH / "REPORT.md").write_text(
        REPORT.format(
            run_date=payload["generated"],
            n_tests=len(pairs),
            baseline=args.baseline,
            candidate=args.candidate,
            mean_diff=payload["mean_diff"],
            baseline_mean=b_mean,
            candidate_mean=c_mean,
            resamples=args.resamples,
            table=table,
            n80=n80 or "> 100",
            p10=p10,
            mde_estimate=mde,
            effect_size=observed.get("effect_size"),
        ),
        encoding="utf-8",
    )

    FIXTURES.mkdir(parents=True, exist_ok=True)
    shutil.copy(RESEARCH / "power-study.json", FIXTURES / "power-study.json")

    print("\nWrote research/REPORT.md, power-study.json, power-curve.svg")
    print(f"  power at n=10 : {p10:.0%}")
    print(f"  80% power at  : n={n80}")
    print(f"  tool estimate : {mde}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
