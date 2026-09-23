import asyncio
import csv
import io
import json
import logging
import os
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo.errors import DuplicateKeyError, OperationFailure
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from evalbench.answers import judged_tests, suite_needs_judge
from evalbench.api.admin import router as admin_router
from evalbench.api.auth import get_password_hash, hash_api_key
from evalbench.api.auth_routes import router as auth_router
from evalbench.api.dashboard import router as dashboard_router
from evalbench.api.deps import (
    get_current_user,
    limiter,
    owner_filter,
    require_owner,
)
from evalbench.api.routes import router as suites_router
from evalbench.api.summary import RUN_ROW_FIELDS, run_row, summarize_run
from evalbench.benchmarks import load_benchmark
from evalbench.config import settings
from evalbench.core.regression import RegressionDetector
from evalbench.db.mongo import client, db
from evalbench.db.schemas import TestRun, TestSuite
from evalbench.metrics import (
    init_metrics,
    regression_detected,
    regression_mean_diff,
    regression_pvalue,
)
from evalbench.reaper import reap_filter, reap_reason

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
    # Unique, not merely indexed. Registration checks the name first,
    # but a check cannot be atomic with the insert that follows it —
    # two simultaneous registrations both saw a free name and both
    # wrote, leaving one username on two accounts and login returning
    # whichever Mongo reached first.
    # Keys are stored hashed. The old unique index on the plaintext
    # field would refuse a second document without it (missing counts
    # as null, and null must be unique too), so it goes.
    with suppress(OperationFailure):
        await db.users.drop_index("api_key_1")
    await ensure_unique_index(db.users, "api_key_hash")
    await ensure_unique_index(db.users, "username")
    # list_suites sorts by created_at; list_runs filters suite_id + sorts.
    await db.suites.create_index([("created_at", -1)])
    # The benchmarks page: this user's suites, newest first. Without the
    # owner in the index it scans every suite of every user, every load.
    await db.suites.create_index([("created_by", 1), ("created_at", -1)])
    await db.test_runs.create_index([("suite_id", 1), ("created_at", -1)])
    # Serves the recent-runs list and `calls_used_today()`, which sums
    # a user's server-key runs before *every* submission — the quota
    # check sat on the hot path with nothing to use.
    await db.test_runs.create_index([("created_by", 1), ("created_at", -1)])
    # The startup reaper queries status $in [queued, running].
    await db.test_runs.create_index("status")



async def _backfill_api_key_hashes() -> int:
    """Accounts from before keys were hashed carry the key in the clear.
    Each becomes its hash, and the plaintext is removed. The key itself
    keeps working — the lookup hashes what the caller sends."""
    n = 0
    async for u in db.users.find({"api_key": {"$exists": True}}):
        await db.users.update_one(
            {"_id": u["_id"]},
            {
                "$set": {"api_key_hash": hash_api_key(u["api_key"])},
                "$unset": {"api_key": ""},
            },
        )
        n += 1
    if n:
        logger.info("Hashed %d API key(s) that were stored in the clear", n)
    return n


async def _retarget_bundled_copies() -> int:
    """Bring adopted copies back in line with the benchmark they copy.

    `starter-suite.yaml` named no provider, so it inherited the schema
    default — ollama — and every copy anyone adopted carries it. Fixing
    the file does not reach them: they are documents now. On an instance
    with no Ollama the copy cannot run at all, and the benchmark page
    shows `ollama / llama3.1` under a benchmark meant to run anywhere.

    Only copies are touched, and only where the bundled definition
    actually disagrees. A suite somebody wrote themselves may mean
    ollama exactly, and is not ours to rewrite.
    """
    n = 0
    cursor = db.suites.find(
        {"provider": "ollama", "bundled_slug": {"$exists": True}},
        {"bundled_slug": 1, "provider": 1, "model": 1},
    )
    async for doc in cursor:
        # Defensive rather than trusting the filter: a suite with no slug
        # is somebody's own, and the one thing this must never do is
        # rewrite a suite that meant ollama.
        slug = doc.get("bundled_slug")
        bundled = load_benchmark(slug) if slug else None
        if not bundled:
            continue
        provider = bundled.get("provider")
        if not provider or provider == "ollama":
            continue
        await db.suites.update_one(
            {"_id": doc["_id"]},
            {"$set": {"provider": provider, "model": bundled.get("model", doc.get("model"))}},
        )
        n += 1
    if n:
        logger.info("Re-targeted %d adopted copy/copies away from a local model", n)
    return n


async def _backfill_judged_tests() -> int:
    """Count judged tests on suites stored before the count existed.

    `judged_tests` is what the benchmark list needs to show a judge
    floor; it is stored at import. A suite from before that would show
    no floor for ever — honest, but wrong the way a missed migration is
    wrong. Runs once per suite: after this, nothing lacks the field.
    """
    n = 0
    cursor = db.suites.find(
        {"judged_tests": {"$exists": False}}, {"tests": 1, "evaluator": 1}
    )
    async for doc in cursor:
        try:
            suite = TestSuite(name="x", model="x", **{
                k: v for k, v in doc.items() if k in ("tests", "evaluator")
            })
        except Exception:  # noqa: BLE001 - a malformed suite is not a reason to not start
            logger.warning("Could not count judged tests on suite %s", doc.get("_id"))
            continue
        await db.suites.update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "judged_tests": judged_tests(suite),
                "needs_judge": suite_needs_judge(suite),
            }},
        )
        n += 1
    if n:
        logger.info("Backfilled judged_tests on %d suite(s)", n)
    return n


async def _backfill_run_status() -> int:
    """Give runs from before the job model the status they earned.

    Until 2026-09-02 a run executed synchronously and its document was
    written when it finished, so it never needed a `status`. Every list
    that has asked for `status == "completed"` since — run history, the
    resolution estimate, the admin count — has skipped those runs, and
    the admin page files them under "unknown". A run with results and
    no status finished; say so, once. One with no results and no status
    is not guessed at.
    """
    n = 0
    cursor = db.test_runs.find(
        {"status": None}, {"results": 1}
    )
    async for doc in cursor:
        results = doc.get("results") or []
        if not results:
            continue
        await db.test_runs.update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "status": "completed",
                "progress": 1.0,
                "completed_tests": len(results),
                "total_tests": len(results),
            }},
        )
        n += 1
    if n:
        logger.info("Backfilled status on %d pre-job-model run(s)", n)
    return n


async def reap_abandoned_runs(when: str) -> int:
    """Fail runs that can be proven dead, and only those.

    Under `rq` the work runs in a separate worker that does not restart
    with the API, so "the API restarted" is not evidence about any run —
    reaping on that signal failed live runs on every deploy. See
    evalbench/reaper.py for what counts as proof.
    """
    dead = reap_filter(settings.job_backend, datetime.now(timezone.utc))
    if dead is None:
        logger.warning(
            "Unknown JOB_BACKEND %r — not reaping any runs",
            settings.job_backend,
        )
        return 0

    reaped = await db.test_runs.update_many(
        dead,
        {"$set": {
            "status": "failed",
            "error": reap_reason(settings.job_backend),
            "finished_at": datetime.now(timezone.utc),
        }},
    )
    count = getattr(reaped, "modified_count", 0) or 0
    if count:
        logger.warning("Marked %d abandoned run(s) as failed (%s)", count, when)
    return count


async def _reaper_loop() -> None:
    while True:
        await asyncio.sleep(settings.reap_interval_seconds)
        try:
            await reap_abandoned_runs("periodic sweep")
        except Exception:  # noqa: BLE001 - a sweep failing must not end the loop
            logger.exception("Reaper sweep failed")



async def ensure_unique_index(collection, field: str) -> bool:
    """Make `field` a unique index, upgrading one that already exists.

    `create_index(..., unique=True)` does not alter an index that is
    already there without it — MongoDB refuses with a conflict, and the
    API then fails to start. Every database created before the constraint
    existed has the old index, so the upgrade has to be handled here.

    Returns False when the constraint could not be built because the data
    already violates it. That is logged loudly rather than fatal: two
    accounts sharing a name is a problem an operator has to resolve, and
    refusing to boot would take away the tools for resolving it.
    """
    try:
        await collection.create_index(field, unique=True)
        return True
    except DuplicateKeyError:
        logger.error(
            "Cannot make %s.%s unique: the collection already contains "
            "duplicates. Two accounts sharing a username means logins can "
            "land in the wrong one. Merge or remove them, then restart.",
            collection.name if hasattr(collection, "name") else "?", field,
        )
        return False
    except OperationFailure as e:
        # 85 IndexOptionsConflict / 86 IndexKeySpecsConflict: same key,
        # different options. Rebuild it.
        if e.code not in (85, 86):
            raise
        logger.info("Rebuilding index on %s as unique", field)
        await collection.drop_index(f"{field}_1")
        try:
            await collection.create_index(field, unique=True)
            return True
        except DuplicateKeyError:
            logger.error(
                "Cannot make %s unique: existing duplicates. Merge them, "
                "then restart.", field,
            )
            return False


async def _bootstrap_admin() -> None:
    """Create the default admin if no users exist."""
    count = await db.users.count_documents({})
    if count != 0:
        return
    await db.users.insert_one({
        "username": settings.admin_username,
        "hashed_password": get_password_hash(settings.admin_password),
        "api_key_hash": hash_api_key(settings.admin_api_key),
        "role": "admin",
        "created_at": datetime.now(timezone.utc),
    })
    logger.info(
        "Default admin created (username=%s). "
        "Rotate the credentials and API key immediately.",
        settings.admin_username,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""

    logging.basicConfig(level=settings.log_level.upper())
    _check_secrets()
    # Hash before indexing: the unique index on the hash must not meet
    # a collection where every old account still lacks one.
    await _backfill_api_key_hashes()
    await _ensure_indexes()
    await _bootstrap_admin()

    await reap_abandoned_runs("startup")
    await _backfill_judged_tests()
    await _retarget_bundled_copies()
    await _backfill_run_status()

    # Under rq, death is detected by silence rather than by a restart, so
    # it has to be checked on a clock: a worker can die while the API
    # stays up for weeks, and that run must not hang forever.
    reaper = asyncio.create_task(_reaper_loop())

    yield

    # Graceful shutdown:
    reaper.cancel()
    with suppress(asyncio.CancelledError):
        await reaper
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

class BodyLimitMiddleware:
    """Refuse a request body over ``settings.max_body_bytes``.

    Two checks, because a client chooses which one applies. A declared
    Content-Length over the limit is refused before a byte is read. A
    chunked body has no length to declare, so it is counted as it
    streams and cut off the moment it passes the line — the handler's
    ``await request.body()`` then raises, and the handler below turns
    that into a 413. Pure ASGI: no buffering, nothing to add to the hot
    path for the normal case.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = settings.max_body_bytes
        declared = next(
            (v for k, v in scope.get("headers", []) if k == b"content-length"),
            None,
        )
        if declared and declared.isdigit() and int(declared) > limit:
            return await _too_large(send, limit)

        seen = 0

        async def counted():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise BodyTooLarge(limit)
            return message

        await self.app(scope, counted, send)


async def _too_large(send, limit: int):
    body = _too_large_body(limit)
    await send({
        "type": "http.response.start",
        "status": 413,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({"type": "http.response.body", "body": body})


def _too_large_detail(limit: int) -> str:
    shown = f"{limit // 1024} KB" if limit < 1024 * 1024 else f"{limit // (1024 * 1024)} MB"
    return f"Request body too large; the limit is {shown}."


def _too_large_body(limit: int) -> bytes:
    return json.dumps({"detail": _too_large_detail(limit)}).encode()


class BodyTooLarge(HTTPException):
    """An HTTPException, not a plain one: FastAPI turns any other error
    raised while it reads the body into a generic 400 "error parsing
    the body". An HTTPException it re-raises untouched."""

    def __init__(self, limit: int):
        super().__init__(status_code=413, detail=_too_large_detail(limit))



app.add_middleware(BodyLimitMiddleware)


async def _unhandled(request: Request, exc: Exception):
    """A crash is still an answer.

    Starlette answers an unhandled exception from outside the CORS
    layer, so the 500 reaches the browser without CORS headers and the
    page can only say "Failed to fetch" — the person then has nothing to
    report. This names it, and carries the CORS header for an allowed
    origin. The traceback stays in the log, where it belongs.
    """
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    headers = {}
    origin = request.headers.get("origin")
    allowed = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if origin and origin in allowed:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Vary"] = "Origin"
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error — the API log has the traceback."},
        headers=headers,
    )


app.add_exception_handler(Exception, _unhandled)

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
app.include_router(admin_router)
app.include_router(dashboard_router)


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
        db.test_runs.find(owner_filter(user), RUN_ROW_FIELDS)
        .sort("created_at", -1)
        .limit(limit)
    ):
        out.append(run_row(doc))
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

    # Per-test results ride along; the result view maps over them.
    # The web client's RunSummary type has always declared `results`; this
    # endpoint was the one place that didn't honour it, and the result
    # view crashed on `.map` of undefined the first time it was rendered
    # from an authenticated run.
    return {
        "run_id": run_id,
        **summarize_run(doc),
        "results": doc.get("results", []),
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
