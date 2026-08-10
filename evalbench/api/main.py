from fastapi import FastAPI, HTTPException
from bson import ObjectId

from evalbench.api.routes import router as suites_router
from evalbench.db.mongo import db
from evalbench.core.regression import RegressionDetector
from evalbench.db.schemas import TestRun

app = FastAPI(
    title="EvalBench",
    description="Local LLM evaluation and regression testing platform",
    version="0.1.0",
)

app.include_router(suites_router)


@app.get("/health")
async def health():
    await db.command("ping")
    return {"status": "ok", "database": "connected"}


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    if not ObjectId.is_valid(run_id):
        raise HTTPException(status_code=400, detail="Invalid run ID format")

    doc = await db.test_runs.find_one({"_id": ObjectId(run_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Run not found")

    doc["_id"] = str(doc["_id"])
    return doc


@app.get("/runs/{run_id}/summary")
async def get_run_summary(run_id: str):
    if not ObjectId.is_valid(run_id):
        raise HTTPException(status_code=400, detail="Invalid run ID format")

    doc = await db.test_runs.find_one({"_id": ObjectId(run_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Run not found")

    results = doc.get("results", [])
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    scores = [r.get("score", 0) for r in results]
    latencies = [r.get("latency_ms", 0) for r in results]
    tokens = [r.get("tokens", 0) for r in results]

    return {
        "run_id": run_id,
        "suite_id": doc.get("suite_id"),
        "model": doc.get("model"),
        "evaluator": doc.get("evaluator"),
        "total_tests": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0,
        "avg_score": round(sum(scores) / len(scores), 4) if scores else 0,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
        "total_tokens": sum(tokens),
    }


@app.post("/regression")
async def check_regression(payload: dict):
    """
    Compare two runs for statistical regression.
    Body: {"baseline_run_id": "...", "current_run_id": "..."}
    """
    baseline_id = payload.get("baseline_run_id")
    current_id = payload.get("current_run_id")

    if not baseline_id or not current_id:
        raise HTTPException(status_code=400, detail="baseline_run_id and current_run_id required")

    for rid in [baseline_id, current_id]:
        if not ObjectId.is_valid(rid):
            raise HTTPException(status_code=400, detail=f"Invalid run ID: {rid}")

    baseline_doc = await db.test_runs.find_one({"_id": ObjectId(baseline_id)})
    current_doc = await db.test_runs.find_one({"_id": ObjectId(current_id)})

    if not baseline_doc:
        raise HTTPException(status_code=404, detail="Baseline run not found")
    if not current_doc:
        raise HTTPException(status_code=404, detail="Current run not found")

    baseline_doc["_id"] = str(baseline_doc["_id"])
    current_doc["_id"] = str(current_doc["_id"])

    baseline = TestRun(**baseline_doc)
    current = TestRun(**current_doc)

    detector = RegressionDetector()
    result = detector.compare(baseline, current)

    result["baseline_run_id"] = baseline_id
    result["current_run_id"] = current_id

    return result


@app.get("/suites/{suite_id}/regression-history")
async def get_regression_history(suite_id: str):
    """Compare all runs of a suite against the oldest run"""
    if not ObjectId.is_valid(suite_id):
        raise HTTPException(status_code=400, detail="Invalid suite ID")

    runs = []
    async for doc in db.test_runs.find({"suite_id": suite_id}).sort("created_at", 1).limit(50):
        doc["_id"] = str(doc["_id"])
        runs.append(TestRun(**doc))

    if len(runs) < 2:
        return {"comparisons": [], "message": "Need at least 2 runs for regression analysis"}

    detector = RegressionDetector()
    comparisons = detector.compare_runs(runs)

    # Enrich with run IDs
    for i, comp in enumerate(comparisons):
        if i < len(runs) - 1:
            comp["current_run_id"] = str(runs[i].created_at) if hasattr(runs[i], 'created_at') else "unknown"

    return {
        "suite_id": suite_id,
        "total_runs": len(runs),
        "comparisons": comparisons,
    }