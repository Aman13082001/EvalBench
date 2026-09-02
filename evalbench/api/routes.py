import logging
from datetime import datetime, timezone

import yaml
from bson import ObjectId
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
)

from evalbench.api.deps import get_current_user, limiter
from evalbench.core.providers import get_provider
from evalbench.core.runner import TestRunner
from evalbench.db.mongo import db
from evalbench.db.schemas import TestRun, TestSuite
from evalbench.security.adversarial_suite import ADVERSARIAL_TESTS

logger = logging.getLogger("evalbench")

router = APIRouter(prefix="/suites", tags=["suites"])


@router.post("", status_code=201)
@limiter.limit("20/minute")
async def create_suite(
    request: Request,
    suite: TestSuite,
    user=Depends(get_current_user),
):
    doc = suite.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)

    result = await db.suites.insert_one(doc)

    return {
        "id": str(result.inserted_id),
        "message": "Suite created"
    }


@router.get("")
async def list_suites():
    suites = []

    async for doc in db.suites.find().sort("created_at", -1).limit(50):
        doc["_id"] = str(doc["_id"])
        suites.append(doc)

    return suites


@router.get("/models")
async def list_models(provider: str = "ollama"):
    client = get_provider(provider)
    try:
        return {"provider": provider, "models": await client.list_models()}
    finally:
        await client.close()


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

    result = await db.suites.insert_one(doc)

    return {
        "id": str(result.inserted_id),
        "message": "Security suite created",
        "test_count": len(ADVERSARIAL_TESTS),
        "categories": list(
            set(t["category"] for t in ADVERSARIAL_TESTS)
        ),
    }


@router.get("/{suite_id}")
async def get_suite(suite_id: str):
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

    doc["_id"] = str(doc["_id"])

    return doc


@router.get("/{suite_id}/export")
async def export_suite(suite_id: str):
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

    doc = suite.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)

    result = await db.suites.insert_one(doc)

    return {
        "id": str(result.inserted_id),
        "message": "Suite imported",
    }


async def execute_run_job(run_id: str, suite_id: str, suite: TestSuite):
    """Background worker: run the suite and stream status into the run doc."""

    oid = {"_id": ObjectId(run_id)}
    await db.test_runs.update_one(
        oid,
        {"$set": {
            "status": "running",
            "started_at": datetime.now(timezone.utc),
        }},
    )

    runner = TestRunner()

    async def _report(done: int, total: int):
        await db.test_runs.update_one(
            oid,
            {"$set": {
                "completed_tests": done,
                "progress": round(done / total, 4) if total else 1.0,
            }},
        )

    try:
        run = await runner.run_suite(suite, suite_id, progress_cb=_report)
        await db.test_runs.update_one(
            oid,
            {"$set": {
                "status": "completed",
                "progress": 1.0,
                "completed_tests": len(run.results),
                "results": [r.model_dump() for r in run.results],
                "model": run.model,
                "evaluator": run.evaluator,
                "finished_at": datetime.now(timezone.utc),
            }},
        )
    except Exception as e:  # noqa: BLE001 - record failure, don't crash the worker
        logger.exception("Run %s failed", run_id)
        await db.test_runs.update_one(
            oid,
            {"$set": {
                "status": "failed",
                "error": str(e),
                "finished_at": datetime.now(timezone.utc),
            }},
        )
    finally:
        await runner.close()


@router.post("/{suite_id}/run", status_code=202)
@limiter.limit("10/minute")
async def run_suite(
    request: Request,
    suite_id: str,
    background_tasks: BackgroundTasks,
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

    doc["_id"] = str(doc["_id"])

    suite = TestSuite(**doc)

    queued = TestRun(
        suite_id=suite_id,
        model=suite.model,
        evaluator=suite.evaluator,
        results=[],
        created_at=datetime.now(timezone.utc),
        status="queued",
        progress=0.0,
        total_tests=len(suite.tests),
        completed_tests=0,
    )

    result = await db.test_runs.insert_one(queued.model_dump())
    run_id = str(result.inserted_id)

    background_tasks.add_task(execute_run_job, run_id, suite_id, suite)

    return {
        "run_id": run_id,
        "suite_id": suite_id,
        "model": suite.model,
        "evaluator": suite.evaluator,
        "test_count": len(suite.tests),
        "status": "queued",
    }


@router.get("/{suite_id}/baseline")
async def get_baseline(suite_id: str):
    if not ObjectId.is_valid(suite_id):
        raise HTTPException(status_code=400, detail="Invalid suite ID format")
    doc = await db.suites.find_one({"_id": ObjectId(suite_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Suite not found")
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

    run = await db.test_runs.find_one({"_id": ObjectId(run_id)})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
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


@router.post("/{suite_id}/compare", status_code=201)
@limiter.limit("10/minute")
async def compare_models(
    request: Request,
    suite_id: str,
    payload: dict,
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

    models = payload.get("models", [])

    evaluator = payload.get(
        "evaluator",
        doc.get("evaluator", "exact")
    )

    if not models:
        raise HTTPException(
            status_code=400,
            detail="No models provided"
        )

    run_ids = []

    runner = TestRunner()

    try:
        for model in models:
            suite_data = {
                **doc,
                "_id": str(doc["_id"])
            }

            suite_data["model"] = model
            suite_data["evaluator"] = evaluator

            suite = TestSuite(**suite_data)

            run = await runner.run_suite(
                suite,
                suite_id
            )

            run_doc = run.model_dump()

            result = await db.test_runs.insert_one(
                run_doc
            )

            run_ids.append(
                str(result.inserted_id)
            )

    finally:
        await runner.close()

    return {
        "suite_id": suite_id,
        "models_tested": models,
        "evaluator": evaluator,
        "run_ids": run_ids,
        "status": "completed",
    }


@router.get("/{suite_id}/runs")
async def list_runs(suite_id: str):
    if not ObjectId.is_valid(suite_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid suite ID format"
        )

    runs = []

    async for doc in db.test_runs.find(
        {"suite_id": suite_id}
    ).sort(
        "created_at",
        -1
    ).limit(20):

        doc["_id"] = str(doc["_id"])
        runs.append(doc)

    return runs
