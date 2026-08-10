import yaml
from fastapi import APIRouter, HTTPException
from bson import ObjectId
from datetime import datetime

from evalbench.db.mongo import db
from evalbench.db.schemas import TestSuite
from evalbench.core.runner import TestRunner
from evalbench.core.models import OllamaClient
from evalbench.security.adversarial_suite import ADVERSARIAL_TESTS


router = APIRouter(prefix="/suites", tags=["suites"])


@router.post("", status_code=201)
async def create_suite(suite: TestSuite):
    doc = suite.model_dump()
    doc["created_at"] = datetime.utcnow()

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


# MOVED HERE (only change)

@router.get("/models")
async def list_ollama_models():
    client = OllamaClient()

    try:
        models = await client.list_models()
        return {"models": models}
    finally:
        await client.close()


@router.post("/security-suite", status_code=201)
async def create_security_suite(model: str = "llama3.1"):
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
    doc["created_at"] = datetime.utcnow()

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
async def import_suite(payload: dict):
    try:
        suite = TestSuite(**payload)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid suite data: {str(e)}"
        )

    doc = suite.model_dump()
    doc["created_at"] = datetime.utcnow()

    result = await db.suites.insert_one(doc)

    return {
        "id": str(result.inserted_id),
        "message": "Suite imported",
    }


@router.post("/{suite_id}/run", status_code=201)
async def run_suite(suite_id: str):
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

    runner = TestRunner()

    try:
        run = await runner.run_suite(
            suite,
            suite_id
        )
    finally:
        await runner.close()

    run_doc = run.model_dump()

    result = await db.test_runs.insert_one(
        run_doc
    )

    return {
        "run_id": str(result.inserted_id),
        "suite_id": suite_id,
        "model": run.model,
        "evaluator": run.evaluator,
        "test_count": len(run.results),
        "status": "completed",
    }


@router.post("/{suite_id}/compare", status_code=201)
async def compare_models(
    suite_id: str,
    payload: dict
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