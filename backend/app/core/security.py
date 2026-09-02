from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


class InvalidTokenError(Exception):
    pass


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return _pwd_context.verify(plain_password, password_hash)


def create_access_token(user_id: uuid.UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_access_expire_minutes)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    """Return the user id encoded in a valid access token, or raise InvalidTokenError."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return uuid.UUID(payload["sub"])
    except (JWTError, KeyError, ValueError) as exc:
        raise InvalidTokenError("Access token is invalid or expired") from exc


def generate_refresh_token() -> str:
    """A random opaque string. Only its hash is ever stored (see hash_refresh_token)."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_token_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_expire_days)


def ensure_utc(value: datetime) -> datetime:
    """Treat a naive datetime as UTC.

    SQLite (used in tests) doesn't preserve tzinfo across a round trip even
    for DateTime(timezone=True) columns, unlike Postgres/asyncpg. Comparing
    against datetime.now(timezone.utc) directly would raise TypeError for a
    naive value, so normalize before comparing.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
