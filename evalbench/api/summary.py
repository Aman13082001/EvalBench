"""Turn a stored run document into the summary payload.

Shared by ``GET /runs/{id}/summary`` and the CLI so the two never
drift.
"""

from __future__ import annotations

from evalbench.core.stats import bootstrap_ci


def _errored(r: dict) -> bool:
    # An infra error (excluded from the pass rate) = no sample produced a score.
    return bool(r.get("error")) and not r.get("runs", 0)


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
        "evaluator": doc.get("evaluator"),
        "status": doc.get("status", "completed"),
        "progress": doc.get("progress", 1.0),
        "total_tests": total,
        "scored_tests": total_scored,
        "errors": errors,
        "passed": passed,
        "failed": total_scored - passed,
        "pass_rate": round(passed / total_scored, 4) if total_scored else 0,
        "avg_score": round(sum(scores) / len(scores), 4) if scores else 0,
        "pass_rate_ci": bootstrap_ci(pass_flags),
        "avg_score_ci": bootstrap_ci(scores),
        "avg_latency_ms": (
            round(sum(latencies) / len(latencies), 2) if latencies else 0
        ),
        "total_tokens": sum(tokens),
        "total_prompt_tokens": sum(prompt_tokens),
        "total_completion_tokens": sum(completion_tokens),
        "total_cost_usd": round(sum(costs), 6),
        "rate_limited_samples": rate_limited,
        "by_category": by_category,
        "assertion_types": assertion_types,
    }
