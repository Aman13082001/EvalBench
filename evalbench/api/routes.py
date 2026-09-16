from dataclasses import asdict
from datetime import datetime, timezone

import yaml
from bson import ObjectId
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
)
from pydantic import BaseModel, Field

from evalbench.api.deps import (
    get_current_user,
    limiter,
    mine,
    owner_filter,
    owner_of,
    require_owner,
)
from evalbench.api.summary import RUN_ROW_FIELDS, run_row
from evalbench.benchmarks import describe_benchmarks, load_benchmark
from evalbench.config import settings
from evalbench.core.providers import (
    available_providers,
    get_provider,
    is_chat_model,
)
from evalbench.db.mongo import db
from evalbench.db.schemas import TestRun, TestSuite
from evalbench.jobs import submit_run
from evalbench.resolution import resolution_from_runs
from evalbench.security.adversarial_suite import ADVERSARIAL_TESTS

router = APIRouter(prefix="/suites", tags=["suites"])


# Fields that make a suite *this* suite rather than a definition of one.
# A re-import rewrites the definition and leaves these alone.
_IDENTITY = ("created_at", "created_by", "bundled_slug", "baseline_run_id")


async def _upsert_suite(suite: TestSuite, user, response: Response) -> dict:
    """Create the suite, or update the caller's suite of the same name.

    A benchmark's identity is its name within an account. `evalbench run`
    imports before every run; when that was a plain insert, every run left
    another copy behind — 70 suites with 18 names in one database, run
    history scattered across them, a baseline on one copy meaning nothing
    to the next. Now the second import of "Safety" *is* "Safety".
    """
    owner = owner_of(user)
    doc = suite.model_dump()
    existing = await db.suites.find_one(
        {"name": suite.name, **mine(user)}, {"_id": 1}
    )
    if existing:
        changes = {k: v for k, v in doc.items() if k not in _IDENTITY}
        # A baseline in the payload is an explicit choice; None is silence.
        if doc.get("baseline_run_id"):
            changes["baseline_run_id"] = doc["baseline_run_id"]
        changes["updated_at"] = datetime.now(timezone.utc)
        await db.suites.update_one({"_id": existing["_id"]}, {"$set": changes})
        response.status_code = 200
        return {"id": str(existing["_id"]), "created": False,
                "message": "Suite updated"}

    doc["created_at"] = datetime.now(timezone.utc)
    doc["created_by"] = owner
    result = await db.suites.insert_one(doc)
    response.status_code = 201
    return {"id": str(result.inserted_id), "created": True,
            "message": "Suite created"}


@router.post("", status_code=201)
@limiter.limit("20/minute")
async def create_suite(
    request: Request,
    response: Response,
    suite: TestSuite,
    user=Depends(get_current_user),
):
    return await _upsert_suite(suite, user, response)


@router.get("")
async def list_suites(user=Depends(get_current_user)):
    """The list page: name, what it measures, how many tests, and what it
    can resolve — one query, all of it projected. The test bodies stay
    out (50 suites' worth of prompts was 129 KB to print a count) and the
    resolution is read, not recomputed. The definition loads when you
    open one.
    """
    pipeline = [
        {"$match": owner_filter(user)},
        {"$sort": {"created_at": -1}},
        {"$limit": 200},
        {"$addFields": {"test_count": {"$size": {"$ifNull": ["$tests", []]}}}},
        {"$project": {"tests": 0}},
    ]
    suites = []
    async for doc in db.suites.aggregate(pipeline):
        doc["_id"] = str(doc["_id"])
        suites.append(doc)

    # A copy adopted before descriptions existed still *is* that bundled
    # benchmark. Reading the wording from the file keeps one source of
    # truth and spares every old copy a migration — but never overwrites
    # what the user wrote themselves.
    bundled = {b["slug"]: b["description"] for b in describe_benchmarks()}
    never_measured = asdict(resolution_from_runs([]))
    for s in suites:
        # Stored when a run finishes; benchmarks that predate that, or
        # have never been run, fall back to saying so. Computing it here
        # meant reading run history on every page load, and a window
        # shared across benchmarks that silently reported "not yet
        # measured" for older ones once a busier benchmark filled it.
        s.setdefault("resolution", never_measured)
        if not s.get("description") and s.get("bundled_slug"):
            s["description"] = bundled.get(s["bundled_slug"])
    return suites


@router.get("/models")
async def list_models(
    provider: str = "ollama",
    user=Depends(get_current_user),
):
    client = get_provider(provider)
    try:
        models = await client.list_models()
    finally:
        await client.close()
    # Providers list speech, audio and classifier models alongside chat
    # ones. Only chat models are useful here; the rest are hidden from
    # suggestions (a caller can still name any model explicitly).
    return {
        "provider": provider,
        "models": [m for m in models if is_chat_model(m)],
        "hidden": [m for m in models if not is_chat_model(m)],
    }


@router.post("/security-suite", status_code=201)
@limiter.limit("10/minute")
async def create_security_suite(
    request: Request,
    model: str = "llama3.1",
    user=Depends(get_current_user),
):
    """Create a built-in security/adversarial test suite."""

    suite = {
        "name": "Security & Safety Baseline",
        "model": model,
        "evaluator": "security",
        "tests": [
            {
                "name": t["name"],
                "prompt": t["prompt"],
                "expected": t["expected"],
                "threshold": 1.0,
            }
            for t in ADVERSARIAL_TESTS
        ],
    }

    suite_obj = TestSuite(**suite)

    doc = suite_obj.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    doc["created_by"] = owner_of(user)

    result = await db.suites.insert_one(doc)

    return {
        "id": str(result.inserted_id),
        "message": "Security suite created",
        "test_count": len(ADVERSARIAL_TESTS),
        "categories": list(
            set(t["category"] for t in ADVERSARIAL_TESTS)
        ),
    }


class RunRequest(BaseModel):
    """Optional overrides for a run. All fields optional so the existing
    body-less call keeps working unchanged."""

    # Run this suite against a different model/provider than the suite
    # declares. This is what lets "compare two models" run one suite twice
    # without importing a copy of it per model.
    model: str | None = None
    provider: str | None = None
    # The caller's own provider key. Never written to the database; it is
    # handed to the job and discarded. Runs made with it do not count
    # against the daily cap, since they spend the caller's quota, not ours.
    provider_key: str | None = Field(default=None, repr=False)


def _day_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def runs_used_today(user: dict) -> int:
    """Runs this user started today on the server's key."""
    return await db.test_runs.count_documents(
        {
            **owner_filter(user),
            "created_at": {"$gte": _day_start()},
            "used_server_key": True,
        }
    )


@router.get("/quota")
async def run_quota(user=Depends(get_current_user)):
    """How many server-key runs the caller has left today. Admins are
    uncapped. Surfaced in the UI so the cap is visible before a run,
    not discovered as a 429 after clicking."""
    if user.get("role") == "admin":
        return {"cap": None, "used": 0, "remaining": None}
    used = await runs_used_today(user)
    return {
        "cap": settings.daily_run_cap,
        "used": used,
        "remaining": max(settings.daily_run_cap - used, 0),
    }


@router.get("/bundled")
async def list_bundled(user=Depends(get_current_user)):
    """The benchmarks EvalBench ships. Read from the files, so counts are
    always what is actually there."""
    return describe_benchmarks()


@router.post("/bundled/{slug}/adopt", status_code=200)
@limiter.limit("20/minute")
async def adopt_bundled(
    request: Request, slug: str, user=Depends(get_current_user)
):
    """Give the caller their own copy of a bundled benchmark — once.

    Idempotent: a second call returns the copy they already have rather
    than making another. Repeated `evalbench run` imports are how one
    person ended up with 69 suites; the workspace must not repeat that.
    """
    existing = await db.suites.find_one(
        {**owner_filter(user), "bundled_slug": slug},
        {"_id": 1, "name": 1},
    )
    if existing:
        return {
            "id": str(existing["_id"]),
            "name": existing["name"],
            "created": False,
        }

    data = load_benchmark(slug)
    if data is None:
        raise HTTPException(status_code=404, detail="No such benchmark")

    suite = TestSuite(**data)
    doc = suite.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    doc["created_by"] = owner_of(user)
    doc["bundled_slug"] = slug
    result = await db.suites.insert_one(doc)
    return {"id": str(result.inserted_id), "name": suite.name, "created": True}


@router.get("/{suite_id}")
async def get_suite(suite_id: str, user=Depends(get_current_user)):
    if not ObjectId.is_valid(suite_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid suite ID format"
        )

    doc = await db.suites.find_one(
        {"_id": ObjectId(suite_id)}
    )

    if not doc:
        raise HTTPException(
            status_code=404,
            detail="Suite not found"
        )

    require_owner(doc, user, "Suite")

    doc["_id"] = str(doc["_id"])

    return doc


@router.get("/{suite_id}/export")
async def export_suite(suite_id: str, user=Depends(get_current_user)):
    if not ObjectId.is_valid(suite_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid suite ID format"
        )

    doc = await db.suites.find_one(
        {"_id": ObjectId(suite_id)}
    )

    if not doc:
        raise HTTPException(
            status_code=404,
            detail="Suite not found"
        )

    require_owner(doc, user, "Suite")

    export_data = {
        "name": doc["name"],
        "model": doc["model"],
        "evaluator": doc["evaluator"],
        "tests": doc["tests"],
    }

    yaml_content = yaml.dump(
        export_data,
        sort_keys=False,
        allow_unicode=True
    )

    return {
        "suite_id": suite_id,
        "yaml": yaml_content
    }


@router.post("/import", status_code=201)
@limiter.limit("20/minute")
async def import_suite(
    request: Request,
    response: Response,
    payload: dict,
    user=Depends(get_current_user),
):
    try:
        suite = TestSuite(**payload)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid suite data: {e}",
        ) from e

    return await _upsert_suite(suite, user, response)


@router.post("/{suite_id}/run", status_code=202)
@limiter.limit("10/minute")
async def run_suite(
    request: Request,
    suite_id: str,
    background_tasks: BackgroundTasks,
    body: RunRequest | None = None,
    user=Depends(get_current_user),
):
    if not ObjectId.is_valid(suite_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid suite ID format"
        )

    doc = await db.suites.find_one(
        {"_id": ObjectId(suite_id)}
    )

    if not doc:
        raise HTTPException(
            status_code=404,
            detail="Suite not found"
        )

    require_owner(doc, user, "Suite")

    doc["_id"] = str(doc["_id"])

    suite = TestSuite(**doc)
    body = body or RunRequest()

    provider = (body.provider or suite.provider).lower()
    if body.provider and provider not in available_providers():
        raise HTTPException(
            status_code=400, detail=f"Unknown provider '{provider}'"
        )

    # Local providers cost nothing; hosted ones spend a key. If the caller
    # did not bring their own, it is ours, and that is what the cap is for.
    uses_server_key = (
        provider not in ("ollama", "mock", "demo") and not body.provider_key
    )
    if uses_server_key and user.get("role") != "admin":
        used = await runs_used_today(user)
        if used >= settings.daily_run_cap:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Daily limit of {settings.daily_run_cap} runs on "
                    "EvalBench's key reached. Add your own provider key to "
                    "keep going, or try again tomorrow."
                ),
            )

    queued = TestRun(
        suite_id=suite_id,
        # The run record says what was actually run, override included.
        model=body.model or suite.model,
        evaluator=suite.evaluator,
        results=[],
        created_at=datetime.now(timezone.utc),
        status="queued",
        progress=0.0,
        total_tests=len(suite.tests),
        completed_tests=0,
    )

    run_doc = queued.model_dump()
    run_doc["created_by"] = owner_of(user)
    run_doc["provider"] = provider
    run_doc["used_server_key"] = uses_server_key
    # How many samples were *asked* for. Without it, a run that lost
    # samples to rate limits cannot say so — it only knows how many
    # came back.
    run_doc["samples"] = suite.samples
    result = await db.test_runs.insert_one(run_doc)
    run_id = str(result.inserted_id)

    submit_run(run_id, suite_id, background_tasks, body.provider_key)

    return {
        "run_id": run_id,
        "suite_id": suite_id,
        "model": suite.model,
        "evaluator": suite.evaluator,
        "test_count": len(suite.tests),
        "status": "queued",
    }


@router.get("/{suite_id}/baseline")
async def get_baseline(suite_id: str, user=Depends(get_current_user)):
    if not ObjectId.is_valid(suite_id):
        raise HTTPException(status_code=400, detail="Invalid suite ID format")
    doc = await db.suites.find_one({"_id": ObjectId(suite_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Suite not found")
    require_owner(doc, user, "Suite")
    return {
        "suite_id": suite_id,
        "baseline_run_id": doc.get("baseline_run_id"),
    }


@router.post("/{suite_id}/baseline", status_code=200)
@limiter.limit("20/minute")
async def set_baseline(
    request: Request,
    suite_id: str,
    payload: dict,
    user=Depends(get_current_user),
):
    """Promote a completed run as this suite's regression baseline."""

    run_id = payload.get("run_id")
    if not run_id or not ObjectId.is_valid(suite_id) or not ObjectId.is_valid(
        run_id
    ):
        raise HTTPException(
            status_code=400, detail="Valid suite_id and run_id are required"
        )

    suite = await db.suites.find_one({"_id": ObjectId(suite_id)})
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")
    require_owner(suite, user, "Suite")

    run = await db.test_runs.find_one({"_id": ObjectId(run_id)})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    # Owning the suite is not enough — the run has to be yours too, or a
    # baseline could be pinned to someone else's run and silently break
    # this suite's regression gate.
    require_owner(run, user, "Run")
    if run.get("status", "completed") != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Run is '{run.get('status')}', only completed runs "
            f"can be a baseline",
        )

    await db.suites.update_one(
        {"_id": ObjectId(suite_id)},
        {"$set": {"baseline_run_id": run_id}},
    )
    return {"suite_id": suite_id, "baseline_run_id": run_id}


@router.get("/{suite_id}/runs")
async def list_runs(suite_id: str, user=Depends(get_current_user)):
    if not ObjectId.is_valid(suite_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid suite ID format"
        )

    runs = []

    async for doc in db.test_runs.find(
        {"suite_id": suite_id, **owner_filter(user)}, RUN_ROW_FIELDS
    ).sort(
        "created_at",
        -1
    ).limit(20):

        runs.append(run_row(doc))

    return runs
