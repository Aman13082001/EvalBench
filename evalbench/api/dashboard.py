"""Your dashboard: your runs, counted the way a run report counts them.

Grafana reads Prometheus, whose metrics are labelled by model and suite
and never by user. It shows the instance — everyone's runs, one picture,
read-only — and cannot show a person theirs, because it does not know
who is looking. The app does. This endpoint answers with the caller's
own runs over a window: totals, a line per day, a row per model, a row
per category. Every count goes through the same rule as `run_row` and
`summarize_run` (an infra error is excluded from the pass rate, a
failure is not), so the dashboard and a run report cannot disagree.

Grafana stays what it is: the operations view, for the admin.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from evalbench.api.deps import get_current_user, owner_filter
from evalbench.api.summary import _errored
from evalbench.db.mongo import db

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Counts, scores, latency, cost, category. Never the text: a run
# document carries every response, and thirty days of them is megabytes
# to draw four numbers.
_FIELDS = {
    "model": 1,
    "provider": 1,
    "status": 1,
    "created_at": 1,
    "results.passed": 1,
    "results.error": 1,
    "results.runs": 1,
    "results.score": 1,
    "results.latency_ms": 1,
    "results.cost_usd": 1,
    "results.category": 1,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rate(passed: int, scored: int) -> float | None:
    return round(passed / scored, 4) if scored else None


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


@router.get("")
async def my_dashboard(days: int = 30, user=Depends(get_current_user)):
    days = max(1, min(days, 365))
    now = _now()
    since = now - timedelta(days=days)

    cursor = db.test_runs.find(
        {**owner_filter(user), "created_at": {"$gte": since}}, _FIELDS
    ).sort("created_at", 1)

    totals = {
        "runs": 0, "completed": 0, "failed": 0,
        "scored": 0, "passed": 0, "errors": 0, "cost_usd": 0.0,
    }
    latencies: list[float] = []
    by_day: dict[str, dict] = {}
    by_model: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"runs": 0, "scored": 0, "passed": 0, "scores": [], "latencies": [], "cost_usd": 0.0}
    )
    by_cat: dict[str, dict] = defaultdict(lambda: {"scored": 0, "passed": 0})

    # Every day in the window is present, zeros included: a chart with a
    # missing day reads as a gap in the data, not a quiet day.
    for i in range(days):
        day = (since + timedelta(days=i + 1)).date().isoformat()
        by_day[day] = {"day": day, "runs": 0, "scored": 0, "passed": 0}

    async for doc in cursor:
        results = doc.get("results") or []
        scored = [r for r in results if not _errored(r)]
        passed = sum(1 for r in scored if r.get("passed"))
        cost = sum(r.get("cost_usd") or 0 for r in results)

        totals["runs"] += 1
        if doc.get("status") == "failed":
            totals["failed"] += 1
        elif doc.get("status") == "completed":
            totals["completed"] += 1
        totals["scored"] += len(scored)
        totals["passed"] += passed
        totals["errors"] += len(results) - len(scored)
        totals["cost_usd"] += cost
        latencies.extend(r.get("latency_ms") or 0 for r in scored)

        created = doc.get("created_at")
        day = created.date().isoformat() if isinstance(created, datetime) else None
        if day in by_day:
            d = by_day[day]
            d["runs"] += 1
            d["scored"] += len(scored)
            d["passed"] += passed

        # A run from before providers were recorded has none; that is
        # shown as nothing, not as a question mark.
        m = by_model[(doc.get("model") or "?", doc.get("provider") or "")]
        m["runs"] += 1
        m["scored"] += len(scored)
        m["passed"] += passed
        m["scores"].extend((r.get("score") or 0) for r in scored)
        m["latencies"].extend((r.get("latency_ms") or 0) for r in scored)
        m["cost_usd"] += cost

        for r in scored:
            c = by_cat[r.get("category") or "uncategorised"]
            c["scored"] += 1
            c["passed"] += 1 if r.get("passed") else 0

    return {
        "days": days,
        "since": since.isoformat(),
        "totals": {
            **totals,
            "cost_usd": round(totals["cost_usd"], 6),
            "pass_rate": _rate(totals["passed"], totals["scored"]),
            "avg_latency_ms": _mean(latencies),
        },
        "by_day": [
            {**d, "pass_rate": _rate(d["passed"], d["scored"])} for d in by_day.values()
        ],
        "by_model": sorted(
            (
                {
                    "model": model,
                    "provider": provider,
                    "runs": m["runs"],
                    "scored": m["scored"],
                    "passed": m["passed"],
                    "pass_rate": _rate(m["passed"], m["scored"]),
                    "avg_score": _mean(m["scores"]),
                    "avg_latency_ms": _mean(m["latencies"]),
                    "cost_usd": round(m["cost_usd"], 6),
                }
                for (model, provider), m in by_model.items()
            ),
            key=lambda x: (-x["runs"], x["model"]),
        ),
        "by_category": sorted(
            (
                {"category": name, **c, "pass_rate": _rate(c["passed"], c["scored"])}
                for name, c in by_cat.items()
            ),
            key=lambda x: (-x["scored"], x["category"]),
        ),
    }
