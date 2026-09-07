"""Record real model answers for the no-key demo suite.

The /run page lets a visitor run `suites/demo.yaml` with no API key. The
checks execute live, but the model's answers are replayed from what this
script captures, so the demo costs nothing, cannot fail because a
provider is down, and does not need the visitor to sign up anywhere.

    python scripts/capture_demo.py                 # uses GROQ_API_KEY from .env
    python scripts/capture_demo.py --key gsk_...

It records by running the suite for real with every provider call wrapped
in a recorder. That matters: `llm-rubric`, `faithfulness` and
`context-recall` each make their own judge call whose prompt is built at
runtime and contains the model's answer. Capturing only the suite's
`prompt:` fields would miss those, and the demo would report every graded
check as an error.

Writes evalbench/data/demo_recordings.json. Re-run it whenever
suites/demo.yaml changes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
from datetime import datetime, timezone

import yaml

from evalbench.config import settings
from evalbench.core import runner as runner_module
from evalbench.core.providers import get_provider
from evalbench.core.providers.base import LLMResponse, Provider
from evalbench.core.runner import TestRunner
from evalbench.db.schemas import TestSuite

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITE = ROOT / "suites" / "demo.yaml"
OUT = ROOT / "evalbench" / "data" / "demo_recordings.json"


class RecordingProvider(Provider):
    """Passes every call through to a real provider and keeps the result."""

    name = "recording"

    def __init__(self, inner: Provider, sink: list[dict]):
        self._inner = inner
        self._sink = sink
        self.max_concurrency = getattr(inner, "max_concurrency", 4)

    async def generate(
        self, model: str, prompt: str, temperature: float = 0.7
    ) -> LLMResponse:
        resp = await self._inner.generate(
            model=model, prompt=prompt, temperature=temperature
        )
        self._sink.append(
            {
                "prompt": prompt,
                "response": resp.text,
                "model": resp.model,
                "prompt_tokens": resp.prompt_tokens,
                "completion_tokens": resp.completion_tokens,
                "latency_ms": round(resp.latency_ms, 2),
                "captured_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        print(f"  {len(resp.text):>6} chars  <- {prompt[:64]!r}")
        return resp

    async def list_models(self) -> list[str]:
        return await self._inner.list_models()

    async def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if close:
            await close()


async def _capture(suite_dict: dict, key: str) -> list[dict]:
    sink: list[dict] = []
    real: list[Provider] = []

    def _recording_get_provider(name: str, **kwargs):
        inner = get_provider(name, api_key=key, **kwargs)
        real.append(inner)
        return RecordingProvider(inner, sink)

    original = runner_module.get_provider
    runner_module.get_provider = _recording_get_provider
    try:
        suite = TestSuite(**suite_dict)
        r = TestRunner()
        run = await r.run_suite(suite, "capture")
        await r.close()
        passed = sum(1 for x in run.results if x.passed)
        errored = sum(1 for x in run.results if x.error)
        print(
            f"\n  suite ran: {passed}/{run.total_tests} passed, "
            f"{errored} error(s)"
        )
    finally:
        runner_module.get_provider = original
        for p in real:
            close = getattr(p, "close", None)
            if close:
                await close()
    return sink


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=None, help="Groq API key")
    args = ap.parse_args()

    key = args.key or settings.groq_api_key or ""
    if not key:
        print("No Groq key. Pass --key or set GROQ_API_KEY in .env.")
        return 1

    suite_dict = yaml.safe_load(SUITE.read_text(encoding="utf-8"))
    # Capture against the real provider the demo is imitating, not the
    # replay provider it will be served with.
    suite_dict["provider"] = "groq"
    suite_dict["judge_provider"] = "groq"

    print(f"Running {SUITE.name} against groq and recording every call…\n")
    recordings = asyncio.run(_capture(suite_dict, key))

    # Same prompt asked twice keeps the last answer; the map is by prompt.
    seen: dict[str, dict] = {}
    for entry in recordings:
        seen[" ".join(entry["prompt"].split()).lower()] = entry

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "_source": "suites/demo.yaml",
                "_note": (
                    "Real answers from a real run, replayed so the demo "
                    "needs no API key. Includes judge calls. The checks "
                    "run live against this text."
                ),
                "generated": datetime.now(timezone.utc).isoformat(),
                "recordings": list(seen.values()),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(seen)} recordings to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
