"""Authentication endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from evalbench.api.auth import (
    create_access_token,
    generate_api_key,
    get_password_hash,
    hash_api_key,
    verify_password,
)
from evalbench.api.deps import client_ip, get_current_user, limiter
from evalbench.config import settings
from evalbench.db.mongo import db

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


class UserCreate(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class ApiKeyResponse(BaseModel):
    api_key: str
    message: str


@router.post("/register", status_code=201)
@limiter.limit("5/hour")
async def register(request: Request, user: UserCreate):
    if not settings.allow_registration:
        raise HTTPException(
            status_code=403,
            detail=(
                "Registration is closed on this instance. "
                "Ask the admin for an account."
            ),
        )

    existing = await db.users.find_one(
        {"username": user.username}
    )

    if existing:
        raise HTTPException(
            status_code=400,
            detail="Username already registered",
        )

    # An account the admin banned does not come back under a new name
    # from the same address. Only addresses a banned account actually
    # used; everyone else at a shared address is unaffected.
    ip = client_ip(request)
    banned = await db.users.find_one({"active": False, "ips": ip})
    if banned:
        raise HTTPException(
            status_code=403,
            detail=(
                "Registration from this address is closed: an account "
                "that used it was banned. Contact the admin."
            ),
        )

    api_key = generate_api_key()

    doc = {
        "username": user.username,
        "hashed_password": get_password_hash(
            user.password
        ),
        # The key is shown once, now, and stored only as a hash.
        "api_key_hash": hash_api_key(api_key),
        "role": "user",
        "created_at": datetime.now(timezone.utc),
        "ips": [ip],
        "last_ip": ip,
    }

    try:
        await db.users.insert_one(doc)
    except DuplicateKeyError as e:
        # Another registration won the race between the check above and
        # this insert. Indistinguishable from the name having been taken
        # earlier, so it reads the same.
        raise HTTPException(
            status_code=400,
            detail="Username already registered",
        ) from e

    return {
        "message": "User created",
        "username": user.username,
        "api_key": api_key,
    }


@router.post(
    "/login",
    response_model=Token,
)
@limiter.limit("5/minute")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    user = await db.users.find_one(
        {"username": form_data.username}
    )

    if not user or not verify_password(
        form_data.password,
        user["hashed_password"],
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={
                "WWW-Authenticate": "Bearer"
            },
        )

    # A banned account gets no token: every request would refuse it
    # anyway, but a token that works nowhere is a confusing thing to be
    # handed. Say it here, once.
    if user.get("active") is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated",
        )

    # Where the account is used from, for the ban to key on.
    ip = client_ip(request)
    await db.users.update_one(
        {"username": user["username"]},
        {
            "$addToSet": {"ips": ip},
            "$set": {"last_ip": ip, "last_login_at": datetime.now(timezone.utc)},
        },
    )

    access_token = create_access_token(
        data={"sub": user["username"]}
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


@router.post(
    "/api-key/rotate",
    response_model=ApiKeyResponse,
)
async def rotate_api_key(
    user=Depends(get_current_user),
):
    new_key = generate_api_key()

    await db.users.update_one(
        {"username": user["username"]},
        {
            "$set": {"api_key_hash": hash_api_key(new_key)},
            # An account from before keys were hashed still carries the
            # old one in the clear; rotating is the moment it goes.
            "$unset": {"api_key": ""},
        },
    )

    return {
        "api_key": new_key,
        "message": "API key rotated successfully",
    }


@router.get("/me")
async def read_me(
    user=Depends(get_current_user),
):
    return {
        "username": user["username"],
        "role": user.get(
            "role",
            "user",
        ),
        "created_at": user.get(
            "created_at"
        ),
    }
