"""FastAPI dependencies: auth + rate limiting."""

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPBearer
from slowapi import Limiter
from slowapi.util import get_remote_address

from evalbench.api.auth import decode_token
from evalbench.db.mongo import db

# ── Rate limiter (in-memory; swap to Redis for multi-instance) ──
limiter = Limiter(key_func=get_remote_address)

# ── Auth schemes ──
security = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _accept(user: dict | None) -> dict | None:
    """Normalise a user doc, rejecting deactivated accounts."""
    if not user:
        return None
    if user.get("active") is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated",
        )
    user["_id"] = str(user["_id"])
    return user


async def get_current_user(
    credentials=Depends(security),
    api_key: str = Depends(api_key_header),
):
    """Authenticate via API key (CI) or JWT (interactive)."""

    # 1. Try API key first (stateless, perfect for CI)
    if api_key:
        user = _accept(await db.users.find_one({"api_key": api_key}))
        if user:
            return user

    # 2. Fall back to JWT
    if credentials:
        payload = decode_token(credentials.credentials)
        if payload:
            username = payload.get("sub")
            if username:
                user = _accept(
                    await db.users.find_one({"username": username})
                )
                if user:
                    return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_admin(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


# ── Ownership ─────────────────────────────────────────────────────────
# Every suite and run records the username that created it. A normal user
# sees only their own; an admin sees everything, including legacy
# documents written before ownership existed (which carry no owner).


def owner_of(user: dict) -> str:
    return user.get("username", "")


def owner_filter(user: dict) -> dict:
    """Mongo filter restricting a query to what this user may see."""
    if user.get("role") == "admin":
        return {}
    return {"created_by": owner_of(user)}


def mine(user: dict) -> dict:
    """Mongo filter for what this user *owns* — admin included.

    `owner_filter` answers "what may I see" and lets an admin see all of
    it. This answers "which is mine", for writes: an admin importing
    "Safety" must update the admin's "Safety", not the first one found.
    """
    return {"created_by": owner_of(user)}


def owns(doc: dict, user: dict) -> bool:
    if user.get("role") == "admin":
        return True
    return doc.get("created_by") == owner_of(user)


def require_owner(doc: dict, user: dict, what: str = "Resource") -> None:
    """404 rather than 403 — don't confirm that someone else's id exists."""
    if not owns(doc, user):
        raise HTTPException(status_code=404, detail=f"{what} not found")
