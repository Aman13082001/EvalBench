"""FastAPI dependencies: auth + rate limiting."""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, APIKeyHeader

from slowapi import Limiter
from slowapi.util import get_remote_address

from evalbench.api.auth import decode_token
from evalbench.db.mongo import db

# ── Rate limiter (in-memory; swap to Redis for multi-instance) ──
limiter = Limiter(key_func=get_remote_address)

# ── Auth schemes ──
security = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_current_user(
    credentials=Depends(security),
    api_key: str = Depends(api_key_header),
):
    """Authenticate via API key (CI) or JWT (interactive)."""

    # 1. Try API key first (stateless, perfect for CI)
    if api_key:
        user = await db.users.find_one({"api_key": api_key})
        if user:
            user["_id"] = str(user["_id"])
            return user

    # 2. Fall back to JWT
    if credentials:
        payload = decode_token(credentials.credentials)
        if payload:
            username = payload.get("sub")
            if username:
                user = await db.users.find_one({"username": username})
                if user:
                    user["_id"] = str(user["_id"])
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