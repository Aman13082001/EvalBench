"""One-off repairs to stored data, driven by the CLI.

Kept apart from the API on purpose: these write straight to the database
and exist to undo the effects of a bug that no longer exists. The
planning half is pure so it can be tested without a database and shown
to the operator before anything is written.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class MergeGroup:
    """Several suites that are really one benchmark."""

    owner: str | None
    name: str
    keep: Any  # _id of the copy that survives
    drop: list[Any] = field(default_factory=list)


def plan_merge(suites: list[dict], claim: str | None = None) -> list[MergeGroup]:
    """Group suites by (owner, name) and pick one to keep per group.

    Until import became create-or-update, `evalbench run` inserted a new
    suite every time it ran, so a database ends up with many copies of
    the same name. The copy kept is the one holding a baseline (a baseline
    is deliberate; nothing else on a suite is), else the newest.

    ``claim`` assigns suites with no owner — created before accounts
    existed — to that username first, so they merge with, and become
    visible as, that user's benchmarks.
    """
    by_key: dict[tuple[str | None, str], list[dict]] = defaultdict(list)
    for s in suites:
        owner = s.get("created_by") or None
        if owner is None and claim:
            owner = claim
        by_key[(owner, s["name"])].append(s)

    groups = []
    for (owner, name), copies in sorted(by_key.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])):
        if len(copies) < 2 and (copies[0].get("created_by") or None) == owner:
            continue  # already one, already owned: nothing to do

        def rank(s: dict):
            return (
                1 if s.get("baseline_run_id") else 0,
                s.get("created_at") or datetime.min.replace(tzinfo=timezone.utc),
            )

        keeper = max(copies, key=rank)
        groups.append(
            MergeGroup(
                owner=owner,
                name=name,
                keep=keeper["_id"],
                drop=[s["_id"] for s in copies if s["_id"] != keeper["_id"]],
            )
        )
    return groups


async def apply_merge(db, groups: list[MergeGroup]) -> dict[str, int]:
    """Carry out a plan: re-point every run to the kept copy, then delete
    the others. Runs are never deleted — that is the whole point."""
    moved = deleted = claimed = 0
    for g in groups:
        if g.drop:
            r = await db.test_runs.update_many(
                {"suite_id": {"$in": [str(i) for i in g.drop]}},
                {"$set": {"suite_id": str(g.keep)}},
            )
            moved += r.modified_count
            d = await db.suites.delete_many({"_id": {"$in": g.drop}})
            deleted += d.deleted_count
        # The keeper takes the owner the group was planned under, which
        # is how an orphan ends up claimed.
        r = await db.suites.update_one(
            {"_id": g.keep, "created_by": {"$ne": g.owner}},
            {"$set": {"created_by": g.owner,
                      "updated_at": datetime.now(timezone.utc)}},
        )
        claimed += r.modified_count
    return {"moved_runs": moved, "deleted_suites": deleted, "claimed": claimed}
