import csv
import io
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from evalbench.api.auth import get_password_hash
from evalbench.api.auth_routes import router as auth_router
from evalbench.api.deps import get_current_user, limiter
from evalbench.api.routes import router as suites_router
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""

    logging.basicConfig(level=settings.log_level.upper())

    # Create default admin if no users exist.
    count = await db.users.count_documents({})

    if count == 0:
        if settings.admin_password == "change-me-in-production":
            logger.warning(
                "ADMIN_PASSWORD is still the default placeholder. "
                "Set a strong ADMIN_PASSWORD before deploying."
            )

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
    version="0.1.0",
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

    return {
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

    results = doc.get("results", [])

    total = len(results)

    def _errored(r: dict) -> bool:
        # A test counts as an infrastructure error (excluded from the
        # pass rate) only when no sample produced a score.
        return bool(r.get("error")) and not r.get("runs", 0)

    scored = [r for r in results if not _errored(r)]
    errors = total - len(scored)
    total_scored = len(scored)

    passed = sum(1 for r in scored if r.get("passed"))

    scores = [r.get("score", 0) or 0 for r in scored]
    latencies = [r.get("latency_ms", 0) for r in results]
    tokens = [r.get("tokens", 0) for r in results]
    prompt_tokens = [r.get("prompt_tokens", 0) for r in results]
    completion_tokens = [r.get("completion_tokens", 0) for r in results]
    costs = [r.get("cost_usd", 0) or 0 for r in results]

    # ── Per-assertion-type rollup ──
    assertion_types: dict = {}
    for r in results:
        for a in r.get("assertions") or []:
            bucket = assertion_types.setdefault(
                a.get("type", "?"), {"passed": 0, "failed": 0}
            )
            bucket["passed" if a.get("passed") else "failed"] += 1

    # ── Per-category breakdown ──
    by_category: dict = {}
    for r in results:
        cat = r.get("category") or "uncategorized"
        bucket = by_category.setdefault(
            cat,
            {"total": 0, "passed": 0, "errors": 0, "_score_sum": 0.0},
        )
        bucket["total"] += 1
        if _errored(r):
            bucket["errors"] += 1
            continue
        if r.get("passed"):
            bucket["passed"] += 1
        bucket["_score_sum"] += r.get("score", 0) or 0

    for bucket in by_category.values():
        n_scored = bucket["total"] - bucket["errors"]
        bucket["pass_rate"] = (
            round(bucket["passed"] / n_scored, 4) if n_scored else 0
        )
        bucket["avg_score"] = (
            round(bucket["_score_sum"] / n_scored, 4) if n_scored else 0
        )
        del bucket["_score_sum"]

    return {
        "run_id": run_id,
        "suite_id": doc.get("suite_id"),
        "model": doc.get("model"),
        "evaluator": doc.get("evaluator"),
        "status": doc.get("status", "completed"),
        "progress": doc.get("progress", 1.0),
        "total_tests": total,
        "scored_tests": total_scored,
        "errors": errors,
        "passed": passed,
        "failed": total_scored - passed,
        "pass_rate": (
            round(passed / total_scored, 4)
            if total_scored
            else 0
        ),
        "avg_score": (
            round(sum(scores) / len(scores), 4)
            if scores
            else 0
        ),
        "avg_latency_ms": (
            round(
                sum(latencies) / len(latencies),
                2,
            )
            if latencies
            else 0
        ),
        "total_tokens": sum(tokens),
        "total_prompt_tokens": sum(prompt_tokens),
        "total_completion_tokens": sum(completion_tokens),
        "total_cost_usd": round(sum(costs), 6),
        "by_category": by_category,
        "assertion_types": assertion_types,
    }


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

    if not current_doc:
        raise HTTPException(
            status_code=404,
            detail="Current run not found",
        )

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
        {"suite_id": suite_id}
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
