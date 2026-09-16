"""Admin endpoints: user management and system stats.

Every route here requires the admin role.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from evalbench.api.deps import get_current_admin, limiter
from evalbench.db.mongo import db

router = APIRouter(prefix="/admin", tags=["admin"])

_PUBLIC_USER_FIELDS = {
    "hashed_password": 0,
    "api_key": 0,  # never re-expose a key, even to an admin
}


@router.get("/users")
async def list_users(admin=Depends(get_current_admin)):
    users = []
    async for doc in db.users.find({}, _PUBLIC_USER_FIELDS).sort(
        "created_at", -1
    ):
        doc["_id"] = str(doc["_id"])
        doc.setdefault("active", True)
        users.append(doc)
    return {"users": users, "count": len(users)}


async def _set_active(username: str, active: bool, admin: dict) -> dict:
    if username == admin.get("username") and not active:
        raise HTTPException(
            status_code=400, detail="You cannot deactivate your own account"
        )

    result = await db.users.update_one(
        {"username": username}, {"$set": {"active": active}}
    )
    if not getattr(result, "matched_count", 0):
        raise HTTPException(status_code=404, detail="User not found")

    return {"username": username, "active": active}


@router.post("/users/{username}/deactivate")
@limiter.limit("20/minute")
async def deactivate_user(
    request: Request, username: str, admin=Depends(get_current_admin)
):
    """Block a user from authenticating without deleting their data."""
    return await _set_active(username, False, admin)


@router.post("/users/{username}/activate")
@limiter.limit("20/minute")
async def activate_user(
    request: Request, username: str, admin=Depends(get_current_admin)
):
    return await _set_active(username, True, admin)


@router.get("/stats")
async def system_stats(admin=Depends(get_current_admin)):
    """Counts an operator actually wants on one screen."""
    users = await db.users.count_documents({})
    suites = await db.suites.count_documents({})
    runs = await db.test_runs.count_documents({})

    # One query for every status, rather than one query per status —
    # and it reports states this code has never heard of, which is what
    # an operator needs from a page like this.
    by_status = dict.fromkeys(
        ("queued", "running", "completed", "failed"), 0
    )
    async for row in db.test_runs.aggregate(
        [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    ):
        # Runs stored before `status` existed have none. Dropping them
        # made the breakdown disagree with the total — 87 runs, 52
        # accounted for — with nothing to say where the rest went.
        by_status[row["_id"] or "unknown"] = row["n"]

    # Total estimated spend. Summed by Mongo: iterating every run to add
    # up its results pulled the whole collection through this process,
    # which is instant at eighty runs and a timeout at a hundred
    # thousand.
    spend = 0.0
    async for row in db.test_runs.aggregate([
        {"$unwind": "$results"},
        {"$group": {"_id": None, "total": {"$sum": "$results.cost_usd"}}},
    ]):
        spend = row.get("total") or 0.0

    return {
        "users": users,
        "suites": suites,
        "runs": runs,
        "runs_by_status": by_status,
        "total_cost_usd": round(spend, 6),
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
