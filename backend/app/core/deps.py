from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import InvalidTokenError, decode_access_token
from app.db.session import get_db
from app.models.session import Session
from app.models.user import User

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    # auto_error=False + a manual 401 here (rather than HTTPBearer's default
    # auto_error=True) — the latter raises 403 when the header is missing
    # entirely, but spec 9-1 requires 401 for every unauthenticated 🔒 call
    # regardless of whether the header was missing or just invalid.
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token")
    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token")

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token")
    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Like get_current_user, but returns None when no Authorization header is
    sent at all (anonymous request) instead of raising.

    A header that *is* present but invalid/expired still raises 401, same as
    get_current_user — an expired guest token must not be silently treated as
    "no user", or /auth/register would create a second anonymous account
    instead of upgrading the guest's existing one, orphaning their session.
    """
    if credentials is None:
        return None
    return await get_current_user(credentials, db)


async def get_owned_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Session:
    """Load a session and verify it belongs to the caller.

    Every /sessions/{session_id}/... route across the interview, records, and
    document-generation routers should depend on this instead of re-deriving
    ownership checks, so the 403-on-other-users'-sessions guarantee lives
    in exactly one place (spec 9-6).
    """
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session_not_found")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return session
