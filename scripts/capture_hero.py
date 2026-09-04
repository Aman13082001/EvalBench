"""Capture the homepage demo run.

Runs suites/hero.yaml through the live playground endpoint and writes the
response to web/lib/fixtures/hero-run.json. The homepage replays that
recording, so the animation shows a real evaluation rather than
fabricated numbers.

    python scripts/capture_hero.py            # uses GROQ_API_KEY from .env
    python scripts/capture_hero.py --key gsk_...
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import httpx
import yaml

from evalbench.config import settings

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITE = ROOT / "suites" / "hero.yaml"
OUT = ROOT / "web" / "lib" / "fixtures" / "hero-run.json"


def _run_local(suite: dict, key: str) -> dict:
    """Execute in-process, producing the same shape /playground/run returns."""
    import asyncio

    from evalbench.api.summary import summarize_run
    from evalbench.core.runner import TestRunner
    from evalbench.db.schemas import TestSuite

    async def go() -> dict:
        runner = TestRunner(provider_key=key)
        try:
            run = await runner.run_suite(TestSuite(**suite), "hero")
        finally:
            await runner.close()
        doc = {
            "results": [r.model_dump() for r in run.results],
            "model": run.model,
            "evaluator": run.evaluator,
            "suite_name": suite["name"],
            "status": "completed",
        }
        return {**summarize_run(doc), "results": doc["results"]}

    return asyncio.run(go())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--key", default="")
    ap.add_argument(
        "--local",
        action="store_true",
        help="Run in-process instead of through the API container",
    )
    args = ap.parse_args()

    key = args.key or settings.groq_api_key
    if not key:
        print("No Groq key. Set GROQ_API_KEY in .env or pass --key.")
        return 1

    suite = yaml.safe_load(SUITE.read_text(encoding="utf-8"))
    print(f"Running {suite['name']} on {suite['model']} …")

    if args.local:
        data = _run_local(suite, key)
    else:
        r = httpx.post(
            f"{args.api}/playground/run",
            json={"suite": suite, "provider_key": key},
            timeout=180,
        )
        if r.status_code != 201:
            print(f"Failed: HTTP {r.status_code}\n{r.text[:500]}")
            return 1
        data = r.json()
    # The run id is ephemeral (24h TTL); the fixture is a recording, so drop
    # it rather than ship a link that will 404.
    data.pop("run_id", None)
    data["_captured_from"] = "suites/hero.yaml"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8"
    )

    t = data["results"][0]
    print(f"\nWrote {OUT.relative_to(ROOT)}")
    print(f"  passed      : {t['passed']}  score {t['score']}")
    print(f"  latency     : {t['latency_ms']:.0f} ms")
    print(f"  cost        : ${data['total_cost_usd']:.6f}")
    for a in t["assertions"]:
        mark = "PASS" if a["passed"] else "FAIL"
        print(f"  {mark} {a['type']:18s} {a['detail'][:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
