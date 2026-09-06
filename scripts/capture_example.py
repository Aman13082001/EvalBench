"""Capture the public /example report.

Runs suites/showcase.yaml against two models and compares them, so the
page can show a real regression verdict rather than a staged one:

    baseline  openai/gpt-oss-120b   (the stronger model)
    candidate allam-2-7b            (smaller and cheaper)

Writes web/lib/fixtures/example.json with both summaries and the
comparison. Runs in-process, so it needs a Groq key but not the API
container.

    python scripts/capture_example.py
    python scripts/capture_example.py --candidate qwen/qwen3.6-27b
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

import yaml

from evalbench.api.summary import summarize_run
from evalbench.config import settings
from evalbench.core.regression import RegressionDetector
from evalbench.core.runner import TestRunner
from evalbench.db.schemas import TestSuite

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITE = ROOT / "suites" / "showcase.yaml"
OUT = ROOT / "web" / "lib" / "fixtures" / "example.json"


async def _run(suite_dict: dict, model: str, key: str):
    suite_dict = {**suite_dict, "model": model}
    suite = TestSuite(**suite_dict)
    runner = TestRunner(provider_key=key)
    try:
        run = await runner.run_suite(suite, "showcase")
    finally:
        await runner.close()

    doc = {
        "results": [r.model_dump() for r in run.results],
        "model": run.model,
        "evaluator": run.evaluator,
        "status": "completed",
    }
    return run, {**summarize_run(doc), "results": doc["results"]}


def _line(tag: str, summary: dict) -> None:
    print(
        f"  {tag:9s} {summary['model']:24s} "
        f"pass {summary['passed']}/{summary['scored_tests']}  "
        f"score {summary['avg_score']:.3f}  "
        f"${summary['total_cost_usd']:.6f}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default="")
    ap.add_argument("--baseline", default="openai/gpt-oss-120b")
    ap.add_argument("--candidate", default="allam-2-7b")
    args = ap.parse_args()

    key = args.key or settings.groq_api_key
    if not key:
        print("No Groq key. Set GROQ_API_KEY in .env or pass --key.")
        return 1

    suite_dict = yaml.safe_load(SUITE.read_text(encoding="utf-8"))

    async def go():
        print(f"Baseline  … {args.baseline}")
        base_run, base_sum = await _run(suite_dict, args.baseline, key)
        print(f"Candidate … {args.candidate}")
        cand_run, cand_sum = await _run(suite_dict, args.candidate, key)
        return base_run, base_sum, cand_run, cand_sum

    base_run, base_sum, cand_run, cand_sum = asyncio.run(go())

    comparison = RegressionDetector().compare(base_run, cand_run)

    payload = {
        "suite_name": suite_dict["name"],
        "baseline": base_sum,
        "candidate": cand_sum,
        "comparison": comparison,
        "_captured_from": "suites/showcase.yaml",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )

    print(f"\nWrote {OUT.relative_to(ROOT)}")
    _line("baseline", base_sum)
    _line("candidate", cand_sum)
    print(
        f"  regression_detected = {comparison.get('regression_detected')}"
        f"  ·  mean_diff {comparison.get('mean_diff')}"
        f"  ·  p {comparison.get('p_value')}"
        f"  ·  d {comparison.get('effect_size')}"
    )
    mc = comparison.get("mcnemar") or {}
    if mc:
        print(
            f"  mcnemar: {mc.get('regressions')} regressed / "
            f"{mc.get('fixes')} fixed (p={mc.get('p_value')})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
