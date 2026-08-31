"""Authentication endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from evalbench.api.auth import (
    create_access_token,
    generate_api_key,
    get_password_hash,
    verify_password,
)
from evalbench.api.deps import get_current_user, limiter
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
async def register(user: UserCreate):
    existing = await db.users.find_one(
        {"username": user.username}
    )

    if existing:
        raise HTTPException(
            status_code=400,
            detail="Username already registered",
        )

    api_key = generate_api_key()

    doc = {
        "username": user.username,
        "hashed_password": get_password_hash(
            user.password
        ),
        "api_key": api_key,
        "role": "user",
        "created_at": datetime.now(timezone.utc),
    }

    await db.users.insert_one(doc)

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
        {"$set": {"api_key": new_key}},
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
