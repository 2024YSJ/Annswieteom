from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.deps import get_owned_session
from app.core.security import hash_password
from app.db.session import Base
from app.models.session import Session
from app.models.user import User


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[User.__table__, Session.__table__])

    session_local = async_sessionmaker(engine, expire_on_commit=False)
    async with session_local() as session:
        yield session

    await engine.dispose()


async def _make_user(db_session, email: str) -> User:
    user = User(email=email, password_hash=hash_password("password123"), nickname=email)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_get_owned_session_returns_session_for_its_owner(db_session):
    owner = await _make_user(db_session, "owner@example.com")
    session_row = Session(user_id=owner.id)
    db_session.add(session_row)
    await db_session.commit()
    await db_session.refresh(session_row)

    result = await get_owned_session(session_row.id, current_user=owner, db=db_session)

    assert result.id == session_row.id


@pytest.mark.asyncio
async def test_get_owned_session_returns_403_for_other_users_session(db_session):
    owner = await _make_user(db_session, "owner@example.com")
    intruder = await _make_user(db_session, "intruder@example.com")
    session_row = Session(user_id=owner.id)
    db_session.add(session_row)
    await db_session.commit()
    await db_session.refresh(session_row)

    with pytest.raises(HTTPException) as exc_info:
        await get_owned_session(session_row.id, current_user=intruder, db=db_session)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_owned_session_returns_404_for_nonexistent_session(db_session):
    owner = await _make_user(db_session, "owner@example.com")

    with pytest.raises(HTTPException) as exc_info:
        await get_owned_session(uuid.uuid4(), current_user=owner, db=db_session)

    assert exc_info.value.status_code == 404
