"""Public "try it" endpoint — no account, bring-your-own key, ephemeral.

Suites are capped small, execution is synchronous, and results land in a
TTL collection (``playground_runs``) so a permalink works for a day.
"""

from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from evalbench.api.deps import limiter
from evalbench.api.summary import summarize_run
from evalbench.core.assertions import available_assertion_types
from evalbench.core.providers import available_providers
from evalbench.core.runner import TestRunner
from evalbench.db.mongo import db
from evalbench.db.schemas import TestSuite

router = APIRouter(prefix="/playground", tags=["playground"])

MAX_TESTS = 12
MAX_SAMPLES = 3

# Not reachable from a public deployment, so never offered.
_LOCAL = {"ollama", "mock"}

# Replays recorded answers, so it needs no key and costs nothing. This is
# what a visitor without a provider account actually runs — without it the
# playground is a form a stranger cannot submit.
DEMO_PROVIDER = "demo"


class PlaygroundRunRequest(BaseModel):
    suite: dict
    provider_key: str = Field(
        default="", description="Your own API key for the hosted provider"
    )


def _validate(suite: TestSuite, key: str) -> None:
    if not suite.tests:
        raise HTTPException(status_code=400, detail="Suite has no tests")
    if len(suite.tests) > MAX_TESTS:
        raise HTTPException(
            status_code=400,
            detail=f"Playground suites are capped at {MAX_TESTS} tests",
        )
    if suite.samples > MAX_SAMPLES:
        raise HTTPException(
            status_code=400,
            detail=f"Playground samples are capped at {MAX_SAMPLES}",
        )

    provider = suite.provider.lower()
    if provider == DEMO_PROVIDER:
        # Nothing to authenticate and nothing to spend.
        return
    if provider == "ollama":
        raise HTTPException(
            status_code=400,
            detail="The public playground can't reach a local Ollama — "
            "pick a hosted provider (groq, gemini, ...).",
        )
    if provider not in _LOCAL and not key:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider}' needs a key — paste your free "
            f"{provider} API key (nothing is stored).",
        )


@router.post("/run", status_code=201)
@limiter.limit("5/minute")
async def playground_run(request: Request, payload: PlaygroundRunRequest):
    try:
        suite = TestSuite(**payload.suite)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail=f"Invalid suite: {e}"
        ) from e

    _validate(suite, payload.provider_key)

    runner = TestRunner(provider_key=payload.provider_key or None)
    try:
        run = await runner.run_suite(suite, "playground")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"Run failed: {e}"
        ) from e
    finally:
        await runner.close()

    doc = {
        "results": [r.model_dump() for r in run.results],
        "model": run.model,
        "evaluator": run.evaluator,
        "suite_name": suite.name,
        "status": "completed",
        "created_at": datetime.now(timezone.utc),
    }
    res = await db.playground_runs.insert_one(doc)

    return {
        "run_id": str(res.inserted_id),
        **summarize_run(doc),
        "results": doc["results"],
    }


@router.get("/runs/{run_id}")
async def playground_get(run_id: str):
    if not ObjectId.is_valid(run_id):
        raise HTTPException(status_code=400, detail="Invalid run id")
    doc = await db.playground_runs.find_one({"_id": ObjectId(run_id)})
    if not doc:
        raise HTTPException(
            status_code=404, detail="Playground run not found or expired"
        )
    doc.pop("_id", None)
    return {
        "run_id": run_id,
        **summarize_run(doc),
        "results": doc.get("results", []),
    }


@router.get("/providers")
async def playground_providers():
    """What the playground will accept. The UI reads its limits from
    here rather than hardcoding them, so MAX_TESTS can change in one
    place without the page copy quietly becoming a lie."""
    return {
        "providers": [p for p in available_providers() if p not in _LOCAL],
        "demo_provider": DEMO_PROVIDER,
        "max_tests": MAX_TESTS,
        "max_samples": MAX_SAMPLES,
        "assertion_types": available_assertion_types(),
    }
