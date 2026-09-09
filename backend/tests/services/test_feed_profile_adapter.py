from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.interview_answer import InterviewAnswer
from app.models.user import User
from app.services.feed.profile_adapter import (
    PROFILE_ANSWER_LIMIT,
    PROFILE_TEXT_MAX_CHARS,
    read_profile_signal,
)


@pytest.fixture
def db_maker():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=[User.__table__, InterviewAnswer.__table__])

    asyncio.run(_create())
    yield maker
    asyncio.run(engine.dispose())


@pytest.fixture
def no_table_maker():
    """interview_answers가 아예 없는 DB. 다른 세션이 그 테이블을 바꾸거나
    지워도 메인 화면이 500이 되면 안 된다는 계약을 지키는 테스트용."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=[User.__table__])

    asyncio.run(_create())
    yield maker
    asyncio.run(engine.dispose())


async def _add(db, user_id, *, answer, label="교육", facts=None, created_at=None):
    db.add(
        InterviewAnswer(
            id=uuid.uuid4(),
            user_id=user_id,
            session_id=None,
            category_label=label,
            category_type="education",
            question_text="이 기간에 무엇을 하셨나요?",
            question_source="fixed",
            answer_text=answer,
            confirmed_facts=facts or [],
            created_at=created_at or datetime.now(timezone.utc),
        )
    )


async def _user(db) -> uuid.UUID:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@x.com", nickname="U", password_hash="x")
    db.add(user)
    await db.flush()
    return user.id


@pytest.mark.asyncio
async def test_no_answers_yields_an_empty_signal(db_maker):
    async with db_maker() as db:
        user_id = await _user(db)
        await db.commit()
        signal = await read_profile_signal(db, user_id)
    assert signal.is_empty
    assert signal.fingerprint == ""


@pytest.mark.asyncio
async def test_missing_table_degrades_to_an_empty_signal(no_table_maker):
    """다른 세션이 소유한 테이블이라, 사라지거나 바뀌어도 예외가 아니라
    비개인화로 내려가야 한다."""
    async with no_table_maker() as db:
        user_id = await _user(db)
        await db.commit()
        signal = await read_profile_signal(db, user_id)
    assert signal.is_empty


@pytest.mark.asyncio
async def test_text_includes_the_answer_and_confirmed_facts(db_maker):
    async with db_maker() as db:
        user_id = await _user(db)
        await _add(
            db, user_id,
            answer="반도체 공정 부트캠프를 6개월 수료했습니다",
            facts=[{"content": "반도체 공정 교육 수료", "fact_type": "task", "source_type": "user_confirmed"}],
        )
        await db.commit()
        signal = await read_profile_signal(db, user_id)

    assert "반도체 공정 부트캠프를 6개월 수료했습니다" in signal.text
    assert "반도체 공정 교육 수료" in signal.text
    assert "[교육]" in signal.text


@pytest.mark.asyncio
async def test_question_text_is_excluded(db_maker):
    """질문은 질문 은행이 만든 시스템 문구라 사용자 간에 거의 동일하다.
    넣으면 모든 프로필 벡터에 공통 성분이 생겨 개인화가 뭉개진다."""
    async with db_maker() as db:
        user_id = await _user(db)
        await _add(db, user_id, answer="편의점에서 일했습니다")
        await db.commit()
        signal = await read_profile_signal(db, user_id)

    assert "이 기간에 무엇을 하셨나요?" not in signal.text


@pytest.mark.asyncio
async def test_unconfirmed_answers_are_still_included(db_maker):
    """의도적 선택을 고정한다 — 확정 단계를 안 거친 답변도 사용자가 자기에
    대해 실제로 쓴 문장이라 랭킹 입력으로 유효하다. 정직성 가드레일은 생성
    문서의 인용을 규율하는 것이고 피드는 문장을 만들지 않는다."""
    async with db_maker() as db:
        user_id = await _user(db)
        await _add(db, user_id, answer="독학으로 데이터 분석을 공부했습니다", facts=[])
        await db.commit()
        signal = await read_profile_signal(db, user_id)

    assert "독학으로 데이터 분석을 공부했습니다" in signal.text


@pytest.mark.asyncio
async def test_fingerprint_is_stable_for_the_same_rows(db_maker):
    async with db_maker() as db:
        user_id = await _user(db)
        await _add(db, user_id, answer="같은 답변")
        await db.commit()
        first = await read_profile_signal(db, user_id)
        second = await read_profile_signal(db, user_id)
    assert first.fingerprint == second.fingerprint != ""


@pytest.mark.asyncio
async def test_fingerprint_changes_when_a_new_answer_arrives(db_maker):
    async with db_maker() as db:
        user_id = await _user(db)
        await _add(db, user_id, answer="첫 답변")
        await db.commit()
        before = await read_profile_signal(db, user_id)

        await _add(db, user_id, answer="두 번째 답변")
        await db.commit()
        after = await read_profile_signal(db, user_id)

    assert before.fingerprint != after.fingerprint
    assert after.answer_count == 2


@pytest.mark.asyncio
async def test_text_is_capped_and_drops_the_oldest_first(db_maker):
    """상한을 넘으면 오래된 쪽부터 잘린다 — 이게 사실상의 최신 가중치다."""
    async with db_maker() as db:
        user_id = await _user(db)
        base = datetime.now(timezone.utc)
        await _add(db, user_id, answer="오래된 " + "가" * 3000, created_at=base - timedelta(days=10))
        await _add(db, user_id, answer="최신 " + "나" * 3000, created_at=base)
        await db.commit()
        signal = await read_profile_signal(db, user_id)

    assert len(signal.text) <= PROFILE_TEXT_MAX_CHARS
    assert "최신" in signal.text
    assert "오래된" not in signal.text


@pytest.mark.asyncio
async def test_only_the_most_recent_answers_are_read(db_maker):
    async with db_maker() as db:
        user_id = await _user(db)
        base = datetime.now(timezone.utc)
        for n in range(PROFILE_ANSWER_LIMIT + 5):
            await _add(db, user_id, answer=f"답변{n}", created_at=base - timedelta(minutes=n))
        await db.commit()
        signal = await read_profile_signal(db, user_id)

    assert signal.answer_count == PROFILE_ANSWER_LIMIT


@pytest.mark.asyncio
async def test_another_users_answers_do_not_leak_in(db_maker):
    async with db_maker() as db:
        mine = await _user(db)
        theirs = await _user(db)
        await _add(db, mine, answer="내 답변")
        await _add(db, theirs, answer="남의 답변")
        await db.commit()
        signal = await read_profile_signal(db, mine)

    assert "내 답변" in signal.text
    assert "남의 답변" not in signal.text
