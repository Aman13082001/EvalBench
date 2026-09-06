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

    by_status = {}
    for state in ("queued", "running", "completed", "failed"):
        by_status[state] = await db.test_runs.count_documents(
            {"status": state}
        )

    # Total estimated spend across every stored run.
    spend = 0.0
    async for doc in db.test_runs.find({}, {"results.cost_usd": 1}):
        for r in doc.get("results") or []:
            spend += r.get("cost_usd") or 0.0

    return {
        "users": users,
        "suites": suites,
        "runs": runs,
        "runs_by_status": by_status,
        "total_cost_usd": round(spend, 6),
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
