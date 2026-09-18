"""Turn a stored run document into the summary payload.

Shared by ``GET /runs/{id}/summary`` and the CLI so the two never
drift.
"""

from __future__ import annotations

from bson import ObjectId

from evalbench.core.stats import bootstrap_ci


def _errored(r: dict) -> bool:
    # An infra error (excluded from the pass rate) = no sample produced a score.
    return bool(r.get("error")) and not r.get("runs", 0)


# What a run-history row needs, and nothing else. A whole run document
# carries every response and every assertion — megabytes to draw twenty
# rows, which is what the per-suite history used to fetch.
RUN_ROW_FIELDS = {
    "suite_id": 1,
    "model": 1,
    "provider": 1,
    "evaluator": 1,
    "status": 1,
    "created_at": 1,
    "finished_at": 1,
    "total_tests": 1,
    "completed_tests": 1,
    "error": 1,
    "used_server_key": 1,
    "base_url": 1,
    "results.passed": 1,
    "results.error": 1,
    "results.runs": 1,
    "results.rate_limited": 1,
    "results.cost_usd": 1,
}


def run_row(doc: dict) -> dict:
    """One row of run history, counted the way the summary counts.

    Both run lists call this so they cannot disagree about a pass rate.
    In particular a test that lost some samples to rate limits but was
    answered on others is *scored* here, exactly as in `summarize_run` —
    reading it as a failure would report the provider's bad minute as the
    model's.
    """
    results = doc.pop("results", []) or []
    scored = [r for r in results if not _errored(r)]
    passed = sum(1 for r in scored if r.get("passed"))

    row = dict(doc)
    if isinstance(row.get("_id"), ObjectId):
        row["_id"] = str(row["_id"])
    row["passed"] = passed
    row["scored_tests"] = len(scored)
    row["errors"] = len(results) - len(scored)
    row["pass_rate"] = round(passed / len(scored), 4) if scored else None
    row["rate_limited_samples"] = sum(
        r.get("rate_limited", 0) for r in results
    )
    row["total_cost_usd"] = round(
        sum(r.get("cost_usd") or 0 for r in results), 6
    )
    return row


def summarize_run(doc: dict) -> dict:
    results = doc.get("results", [])
    total = len(results)

    scored = [r for r in results if not _errored(r)]
    total_scored = len(scored)
    errors = total - total_scored
    passed = sum(1 for r in scored if r.get("passed"))

    scores = [r.get("score", 0) or 0 for r in scored]
    pass_flags = [1 if r.get("passed") else 0 for r in scored]
    # Over scored tests only. A timed-out request's latency is the
    # timeout, not the model — averaging it in reports the provider's
    # bad day as the model's speed.
    latencies = [r.get("latency_ms", 0) for r in scored]
    tokens = [r.get("tokens", 0) for r in results]
    prompt_tokens = [r.get("prompt_tokens", 0) for r in results]
    completion_tokens = [r.get("completion_tokens", 0) for r in results]
    costs = [r.get("cost_usd", 0) or 0 for r in results]
    rate_limited = sum(r.get("rate_limited", 0) for r in results)

    # `samples: 3` exists so a pass/fail is a majority vote rather than one
    # draw. A test scored on fewer samples than asked for is back toward a
    # coin flip: its interval widens and the benchmark's resolution drops.
    # That is the real cost of a rate limit, and it is invisible in the
    # error count because the test *was* answered.
    sample_counts = [r.get("runs", 1) for r in scored]
    requested = doc.get("samples") or (max(sample_counts) if sample_counts else 1)
    undersampled = sum(1 for n in sample_counts if n < requested)

    assertion_types: dict = {}
    for r in results:
        for a in r.get("assertions") or []:
            b = assertion_types.setdefault(
                a.get("type", "?"), {"passed": 0, "failed": 0}
            )
            b["passed" if a.get("passed") else "failed"] += 1

    by_category: dict = {}
    for r in results:
        cat = r.get("category") or "uncategorized"
        b = by_category.setdefault(
            cat, {"total": 0, "passed": 0, "errors": 0, "_score_sum": 0.0}
        )
        b["total"] += 1
        if _errored(r):
            b["errors"] += 1
            continue
        if r.get("passed"):
            b["passed"] += 1
        b["_score_sum"] += r.get("score", 0) or 0

    for b in by_category.values():
        n = b["total"] - b["errors"]
        # None, not 0, when nothing in the category could be scored. "0%"
        # reads as "the model failed every one"; the truth is "no answer
        # was obtained", which is a different finding entirely.
        b["scored"] = n
        b["pass_rate"] = round(b["passed"] / n, 4) if n else None
        b["avg_score"] = round(b["_score_sum"] / n, 4) if n else None
        del b["_score_sum"]

    return {
        "suite_id": doc.get("suite_id"),
        "model": doc.get("model"),
        # "answers" means the caller supplied them; the view says so
        # instead of reporting a latency that was never measured.
        "provider": doc.get("provider"),
        # Where a custom run went. The address is part of what was run.
        "base_url": doc.get("base_url"),
        "evaluator": doc.get("evaluator"),
        "status": doc.get("status", "completed"),
        "progress": doc.get("progress", 1.0),
        "total_tests": total,
        "scored_tests": total_scored,
        "errors": errors,
        "passed": passed,
        "failed": total_scored - passed,
        # None, not 0 — the same distinction the per-category rows make.
        # "0%" is a measurement meaning every answer was wrong; a run
        # where nothing was scored has measured nothing at all.
        "pass_rate": round(passed / total_scored, 4) if total_scored else None,
        "avg_score": round(sum(scores) / len(scores), 4) if scores else None,
        "pass_rate_ci": bootstrap_ci(pass_flags),
        "avg_score_ci": bootstrap_ci(scores),
        # Supplied answers were never called for, so there is no
        # time-to-answer; the replay's 0 ms is not the model's speed.
        "avg_latency_ms": (
            None
            if doc.get("provider") == "answers" or not latencies
            else round(sum(latencies) / len(latencies), 2)
        ),
        "total_tokens": sum(tokens),
        "total_prompt_tokens": sum(prompt_tokens),
        "total_completion_tokens": sum(completion_tokens),
        "total_cost_usd": round(sum(costs), 6),
        "rate_limited_samples": rate_limited,
        "samples_requested": requested,
        "undersampled_tests": undersampled,
        "by_category": by_category,
        "assertion_types": assertion_types,
    }
