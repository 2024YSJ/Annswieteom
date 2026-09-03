from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, get_current_user_optional
from app.core.security import (
    create_access_token,
    ensure_utc,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expiry,
    verify_password,
)
from app.db.session import get_db
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.user import LoginRequest, RegisterResponse, TokenPair, UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def _refresh_cookie_kwargs() -> dict:
    if settings.environment == "production":
        return {"httponly": True, "secure": True, "samesite": "none"}
    return {"httponly": True, "secure": False, "samesite": "lax"}


async def _issue_refresh_token(db: AsyncSession, user_id) -> str:
    raw_token = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user_id,
            token_hash=hash_refresh_token(raw_token),
            expires_at=refresh_token_expiry(),
        )
    )
    await db.commit()
    return raw_token


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: UserCreate,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    if current_user is not None and not current_user.is_guest:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already_registered")

    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email_already_exists")

    if current_user is not None:
        # Guest upgrade: keep the same row (and therefore the same sessions,
        # access token, and refresh cookie) instead of creating a new user.
        current_user.email = body.email
        current_user.password_hash = hash_password(body.password)
        current_user.nickname = body.nickname
        current_user.is_guest = False
        await db.commit()
        return RegisterResponse(user_id=current_user.id)

    user = User(email=body.email, password_hash=hash_password(body.password), nickname=body.nickname)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return RegisterResponse(user_id=user.id)


@router.post("/guest", response_model=TokenPair)
async def guest_login(response: Response, db: AsyncSession = Depends(get_db)):
    user = User(email=None, password_hash=None, nickname="게스트", is_guest=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    raw_refresh_token = await _issue_refresh_token(db, user.id)
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_refresh_token,
        path=REFRESH_COOKIE_PATH,
        **_refresh_cookie_kwargs(),
    )
    return TokenPair(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenPair)
async def login(body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == body.email, User.deleted_at.is_(None)))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")

    raw_refresh_token = await _issue_refresh_token(db, user.id)
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_refresh_token,
        path=REFRESH_COOKIE_PATH,
        **_refresh_cookie_kwargs(),
    )
    return TokenPair(access_token=create_access_token(user.id))


@router.post("/refresh", response_model=TokenPair)
async def refresh(request: Request, db: AsyncSession = Depends(get_db)):
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if raw_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_refresh_token")

    token_hash = hash_refresh_token(raw_token)
    stored = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))

    now = datetime.now(timezone.utc)
    if (
        stored is None
        or stored.revoked_at is not None
        or ensure_utc(stored.expires_at) < now
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_refresh_token")

    return TokenPair(access_token=create_access_token(stored.user_id))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if raw_token is not None:
        token_hash = hash_refresh_token(raw_token)
        stored = await db.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.user_id == current_user.id,
            )
        )
        if stored is not None and stored.revoked_at is None:
            stored.revoked_at = datetime.now(timezone.utc)
            await db.commit()

    response.delete_cookie(key=REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)


@router.get("/me", response_model=UserRead)
async def me(current_user: User = Depends(get_current_user)):
    return current_user
