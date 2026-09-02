from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.main import app
from app.models.refresh_token import RefreshToken
from app.models.user import User


@pytest.fixture
def client():
    """A TestClient wired to a fresh in-memory SQLite DB per test.

    Only the users/refresh_tokens tables are created (not the full model
    graph) since some other tables use pgvector's Vector type, which has no
    SQLite compiler.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def _create_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=[User.__table__, RefreshToken.__table__])

    asyncio.run(_create_tables())

    test_session_local = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with test_session_local() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())
