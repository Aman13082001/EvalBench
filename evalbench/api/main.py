import csv
import io
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from evalbench.api.admin import router as admin_router
from evalbench.api.auth import get_password_hash
from evalbench.api.auth_routes import router as auth_router
from evalbench.api.deps import (
    get_current_user,
    limiter,
    owner_filter,
    require_owner,
)
from evalbench.api.playground import router as playground_router
from evalbench.api.routes import router as suites_router
from evalbench.api.summary import summarize_run
from evalbench.config import settings
from evalbench.core.regression import RegressionDetector
from evalbench.db.mongo import client, db
from evalbench.db.schemas import TestRun
from evalbench.metrics import (
    init_metrics,
    regression_detected,
    regression_mean_diff,
    regression_pvalue,
)

logger = logging.getLogger("evalbench")

# Shipped defaults. Booting with any of these is a security hole.
_PLACEHOLDER_SECRETS = {
    "secret_key": "change-this-to-a-random-32-char-string",
    "admin_password": "change-me-in-production",
    "admin_api_key": "eb_admin_change_me_in_production",
}


def _check_secrets() -> None:
    """Refuse to start with shipped placeholder secrets.

    Set EVALBENCH_ALLOW_INSECURE=1 for local dev / CI / demos.
    """
    stale = [
        name
        for name, placeholder in _PLACEHOLDER_SECRETS.items()
        if getattr(settings, name) == placeholder
    ]
    if not stale:
        return

    if os.getenv("EVALBENCH_ALLOW_INSECURE") == "1":
        logger.warning(
            "Running with placeholder %s. EVALBENCH_ALLOW_INSECURE=1 is set "
            "— fine for dev, never for production.",
            ", ".join(stale),
        )
        return

    raise RuntimeError(
        f"Refusing to start: {', '.join(stale)} still set to the shipped "
        f"placeholder. Set real values in .env, or export "
        f"EVALBENCH_ALLOW_INSECURE=1 for local/CI use."
    )


async def _ensure_indexes() -> None:
    """Idempotent index creation for the hot query paths."""
    # Auth does users.find_one({api_key}) / ({username}) on every request.
    await db.users.create_index("api_key")
    await db.users.create_index("username")
    # list_suites sorts by created_at; list_runs filters suite_id + sorts.
    await db.suites.create_index([("created_at", -1)])
    await db.test_runs.create_index([("suite_id", 1), ("created_at", -1)])
    # The startup reaper queries status $in [queued, running].
    await db.test_runs.create_index("status")
    # Playground runs auto-expire after 24h.
    await db.playground_runs.create_index(
        "created_at", expireAfterSeconds=86400
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""

    logging.basicConfig(level=settings.log_level.upper())
    _check_secrets()
    await _ensure_indexes()

    # Create default admin if no users exist.
    count = await db.users.count_documents({})

    if count == 0:

        await db.users.insert_one({
            "username": settings.admin_username,
            "hashed_password": get_password_hash(
                settings.admin_password
            ),
            "api_key": settings.admin_api_key,
            "role": "admin",
            "created_at": datetime.now(timezone.utc),
        })

        logger.info(
            "Default admin created (username=%s). "
            "Rotate the credentials and API key immediately.",
            settings.admin_username,
        )

    # Reap runs orphaned by a crash/restart. Background tasks die with the
    # process, so any run still queued/running is dead — fail it so it
    # doesn't hang forever.
    reaped = await db.test_runs.update_many(
        {"status": {"$in": ["queued", "running"]}},
        {"$set": {
            "status": "failed",
            "error": "interrupted by API restart",
            "finished_at": datetime.now(timezone.utc),
        }},
    )
    if getattr(reaped, "modified_count", 0):
        logger.warning(
            "Marked %d orphaned run(s) as failed on startup",
            reaped.modified_count,
        )

    yield

    # Graceful shutdown:
    # Close the shared MongoDB connection pool.
    client.close()


app = FastAPI(
    title="EvalBench",
    description="Local LLM evaluation and regression testing platform",
    version="0.4.0",
    lifespan=lifespan,
)


# ─────────────────────────────────────────────
# Day 1: Configurable CORS
# ─────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in settings.cors_origins.split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Day 13: Rate limiting + Metrics
# ─────────────────────────────────────────────

app.state.limiter = limiter

app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler,
)

init_metrics(app)


app.include_router(auth_router)
app.include_router(suites_router)
app.include_router(playground_router)
app.include_router(admin_router)


# ─────────────────────────────────────────────
# Day 1: Health / Readiness / Liveness
# ─────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check including database connectivity."""

    try:
        await db.command("ping")

        return {
            "status": "ok",
            "database": "connected",
        }

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(exc),
            },
        ) from exc


@app.get("/live")
async def liveness():
    """Kubernetes liveness probe.

    Returns OK as long as the application process is running.
    """

    return {
        "status": "alive",
    }


@app.get("/ready")
async def readiness():
    """Kubernetes readiness probe.

    The API is ready only when MongoDB is reachable.
    """

    try:
        await db.command("ping")

        return {
            "status": "ready",
            "database": "connected",
        }

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not_ready",
                "database": "disconnected",
                "error": str(exc),
            },
        ) from exc


@app.get("/runs")
async def list_runs(
    limit: int = 20,
    user=Depends(get_current_user),
):
    """The caller's most recent runs across every suite.

    Until now runs could only be listed per suite, so "what have I run
    lately" meant one request per suite. The workspace needs it in one
    call. Results are trimmed to the fields a list needs — the full
    result set is on /runs/{id}.
    """
    limit = max(1, min(limit, 100))
    out = []
    async for doc in (
        db.test_runs.find(
            owner_filter(user),
            {
                "suite_id": 1, "model": 1, "provider": 1, "evaluator": 1,
                "status": 1, "created_at": 1, "finished_at": 1,
                "total_tests": 1, "completed_tests": 1, "error": 1,
                "used_server_key": 1,
                # enough of results to compute a pass rate, nothing more
                "results.passed": 1, "results.error": 1,
                "results.cost_usd": 1,
            },
        )
        .sort("created_at", -1)
        .limit(limit)
    ):
        results = doc.pop("results", []) or []
        scored = [r for r in results if not r.get("error")]
        doc["_id"] = str(doc["_id"])
        doc["passed"] = sum(1 for r in scored if r.get("passed"))
        doc["scored_tests"] = len(scored)
        doc["pass_rate"] = (
            round(doc["passed"] / len(scored), 4) if scored else None
        )
        doc["total_cost_usd"] = round(
            sum(r.get("cost_usd") or 0 for r in results), 6
        )
        out.append(doc)
    return out


@app.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    user=Depends(get_current_user),
):
    if not ObjectId.is_valid(run_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid run ID format",
        )

    doc = await db.test_runs.find_one(
        {"_id": ObjectId(run_id)}
    )

    if not doc:
        raise HTTPException(
            status_code=404,
            detail="Run not found",
        )

    require_owner(doc, user, "Run")

    doc["_id"] = str(doc["_id"])

    return doc


@app.get("/runs/{run_id}/status")
async def get_run_status(
    run_id: str,
    user=Depends(get_current_user),
):
    """Lightweight job-status view — no results payload."""

    if not ObjectId.is_valid(run_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid run ID format",
        )

    doc = await db.test_runs.find_one(
        {"_id": ObjectId(run_id)},
        {"results": 0},
    )

    if not doc:
        raise HTTPException(
            status_code=404,
            detail="Run not found",
        )

    require_owner(doc, user, "Run")

    out = {
        "run_id": run_id,
        "status": doc.get("status", "completed"),
        "progress": doc.get("progress", 1.0),
        "completed_tests": doc.get("completed_tests", 0),
        "total_tests": doc.get("total_tests", 0),
        "error": doc.get("error"),
        "model": doc.get("model"),
        "started_at": doc.get("started_at"),
        "finished_at": doc.get("finished_at"),
    }

    if settings.job_backend == "rq" and out["status"] == "queued":
        try:
            from evalbench.jobs_rq import queue_position

            out["queue_position"] = queue_position(run_id)
        except Exception:  # noqa: BLE001
            pass

    return out


@app.get("/runs/{run_id}/summary")
async def get_run_summary(
    run_id: str,
    user=Depends(get_current_user),
):
    if not ObjectId.is_valid(run_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid run ID format",
        )

    doc = await db.test_runs.find_one(
        {"_id": ObjectId(run_id)}
    )

    if not doc:
        raise HTTPException(
            status_code=404,
            detail="Run not found",
        )

    require_owner(doc, user, "Run")

    return {"run_id": run_id, **summarize_run(doc)}


# ─────────────────────────────────────────────
# Day 14: Result Export
# ─────────────────────────────────────────────

@app.get("/runs/{run_id}/export")
async def export_run(
    run_id: str,
    format: str = "json",
    user=Depends(get_current_user),
):
    """Export a run as JSON or CSV."""

    if format not in ("json", "csv"):
        raise HTTPException(
            status_code=400,
            detail="Format must be 'json' or 'csv'",
        )

    if not ObjectId.is_valid(run_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid run ID format",
        )

    doc = await db.test_runs.find_one(
        {"_id": ObjectId(run_id)}
    )

    if not doc:
        raise HTTPException(
            status_code=404,
            detail="Run not found",
        )

    require_owner(doc, user, "Run")

    results = doc.get("results", [])

    # ─────────────────────────────────────────
    # JSON format
    # ─────────────────────────────────────────

    if format == "json":
        export_data = {
            "run_id": run_id,
            "suite_id": doc.get("suite_id"),
            "model": doc.get("model"),
            "evaluator": doc.get("evaluator"),
            "created_at": str(
                doc.get("created_at")
            ),
            "results": results,
        }

        return {
            "format": "json",
            "filename": f"run_{run_id}.json",
            "data": export_data,
        }

    # ─────────────────────────────────────────
    # CSV format
    # ─────────────────────────────────────────

    if not results:
        raise HTTPException(
            status_code=400,
            detail="No results to export",
        )

    output = io.StringIO()

    writer = csv.DictWriter(
        output,
        fieldnames=[
            "test_name",
            "prompt",
            "expected",
            "actual",
            "score",
            "passed",
            "latency_ms",
            "tokens",
            "error",
        ],
    )

    writer.writeheader()

    for r in results:
        writer.writerow({
            "test_name": r.get(
                "test_name",
                "",
            ),
            "prompt": r.get(
                "prompt",
                "",
            ),
            "expected": r.get(
                "expected",
                "",
            ),
            "actual": r.get(
                "actual",
                "",
            ),
            "score": r.get(
                "score",
                0,
            ),
            "passed": (
                "TRUE"
                if r.get("passed")
                else "FALSE"
            ),
            "latency_ms": r.get(
                "latency_ms",
                0,
            ),
            "tokens": r.get(
                "tokens",
                0,
            ),
            "error": r.get(
                "error",
                "",
            ),
        })

    return {
        "format": "csv",
        "filename": f"run_{run_id}.csv",
        "content": output.getvalue(),
    }


@app.post("/regression")
@limiter.limit("10/minute")
async def check_regression(
    request: Request,
    payload: dict,
    user=Depends(get_current_user),
):
    baseline_id = payload.get("baseline_run_id")
    current_id = payload.get("current_run_id")

    if not baseline_id or not current_id:
        raise HTTPException(
            status_code=400,
            detail="baseline_run_id and current_run_id required",
        )

    for rid in [baseline_id, current_id]:
        if not ObjectId.is_valid(rid):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid run ID: {rid}",
            )

    baseline_doc = await db.test_runs.find_one(
        {"_id": ObjectId(baseline_id)}
    )

    current_doc = await db.test_runs.find_one(
        {"_id": ObjectId(current_id)}
    )

    if not baseline_doc:
        raise HTTPException(
            status_code=404,
            detail="Baseline run not found",
        )

    require_owner(baseline_doc, user, "Baseline run")

    if not current_doc:
        raise HTTPException(
            status_code=404,
            detail="Current run not found",
        )

    require_owner(current_doc, user, "Current run")

    baseline_doc["_id"] = str(
        baseline_doc["_id"]
    )

    current_doc["_id"] = str(
        current_doc["_id"]
    )

    baseline = TestRun(**baseline_doc)
    current = TestRun(**current_doc)

    detector = RegressionDetector()
    result = detector.compare(
        baseline,
        current,
    )

    result["baseline_run_id"] = baseline_id
    result["current_run_id"] = current_id

    # ─────────────────────────────────────────
    # Emit regression metrics
    # ─────────────────────────────────────────

    regression_detected.labels(
        model=baseline.model,
        suite_name=getattr(
            baseline,
            "suite_id",
            "unknown",
        )[:20],
    ).set(
        1 if result.get("regression_detected") else 0
    )

    if result.get("p_value") is not None:
        regression_pvalue.labels(
            model=baseline.model,
            suite_name=getattr(
                baseline,
                "suite_id",
                "unknown",
            )[:20],
        ).set(
            result["p_value"]
        )

    if result.get("mean_diff") is not None:
        regression_mean_diff.labels(
            model=baseline.model,
            suite_name=getattr(
                baseline,
                "suite_id",
                "unknown",
            )[:20],
        ).set(
            result["mean_diff"]
        )

    return result


@app.get(
    "/suites/{suite_id}/regression-history"
)
async def get_regression_history(
    suite_id: str,
    user=Depends(get_current_user),
):
    if not ObjectId.is_valid(suite_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid suite ID",
        )

    runs = []

    async for doc in db.test_runs.find(
        {"suite_id": suite_id, **owner_filter(user)}
    ).sort(
        "created_at",
        1,
    ).limit(50):

        doc["_id"] = str(doc["_id"])

        runs.append(
            TestRun(**doc)
        )

    if len(runs) < 2:
        return {
            "comparisons": [],
            "message": (
                "Need at least 2 runs "
                "for regression analysis"
            ),
        }

    detector = RegressionDetector()

    comparisons = detector.compare_runs(
        runs
    )

    return {
        "suite_id": suite_id,
        "total_runs": len(runs),
        "comparisons": comparisons,
    }
