from __future__ import annotations

import asyncio
import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.interview_answer import InterviewAnswer
from app.models.user_attribute import UserAttribute
from app.models.user_consent import UserConsent
from app.services.llm.base import AttributeCandidate
from app.services.profile import attributes as attrs

TODAY = date(2026, 9, 11)


def cand(key: str, value: str, evidence: str) -> AttributeCandidate:
    return AttributeCandidate(key=key, value_label=value, evidence=evidence)


# ── normalize ─────────────────────────────────────────────────────────────


def test_age_is_stored_as_a_birth_year():
    value, norm = attrs.normalize("birth_year", "26살", TODAY)
    assert value == {"label": "2000년생", "year": 2000}
    assert norm == "2000"


def test_implausible_birth_years_are_dropped():
    assert attrs.normalize("birth_year", "3살", TODAY) is None
    assert attrs.normalize("birth_year", "1890", TODAY) is None


def test_residence_must_resolve_to_a_region_code():
    value, norm = attrs.normalize("residence_region", "수원", TODAY)
    assert value["code"] == "41110" and norm == "41110"
    # 광역이 셋이라 코드 하나로 못 담는다 — 매칭의 하드 조건이라 버린다.
    assert attrs.normalize("residence_region", "수도권", TODAY) is None
    # 어휘 밖(모델이 지어낸 지명)도 버린다.
    assert attrs.normalize("residence_region", "강남", TODAY) is None


def test_coded_choices_carry_the_youthcenter_code():
    value, _ = attrs.normalize("education_level", "대학 졸업", TODAY)
    assert value["code"] == "0049007"
    assert attrs.normalize("education_level", "대졸", TODAY) is None  # 목록 밖 표현


def test_monthly_income_is_annualised():
    value, _ = attrs.normalize("annual_income", "월 200", TODAY)
    assert value["amount"] == 2400


# ── validate ──────────────────────────────────────────────────────────────


def test_evidence_that_is_not_in_the_users_words_is_rejected():
    text = "수원에 살고 있고 파이썬을 조금 할 줄 알아요"
    kept, _ = attrs.validate_candidates(
        [
            cand("residence_region", "수원", "수원에 살고 있고"),
            cand("skills", "자바", "자바를 잘 다뤄요"),  # 지어낸 인용
        ],
        text,
        allow_sensitive=False,
    )
    assert [c.key for c in kept] == ["residence_region"]


def test_whitespace_differences_in_the_quote_are_not_fabrication():
    kept, _ = attrs.validate_candidates([cand("skills", "파이썬", "파이썬을조금")], "파이썬을 조금 해요", False)
    assert len(kept) == 1


def test_a_quote_with_only_the_ending_changed_is_accepted():
    # 실모델(qwen2.5:3b)이 "살고 있고"를 "살고 있어요"로 옮겨 적었다 — 지어낸 게 아니다.
    text = "수원에 살고 있고 올해 26살이에요."
    kept, _ = attrs.validate_candidates([cand("residence_region", "수원", "수원에 살고 있어요")], text, False)
    assert len(kept) == 1


def test_a_region_copied_from_the_prompt_example_is_rejected():
    # 실모델이 지명이 없는 말에 프롬프트 예시의 지명과 인용을 그대로 붙여 냈다.
    text = "경기 남부에서 백엔드 개발자로 일하고 싶어요."
    kept, _ = attrs.validate_candidates([cand("residence_region", "수원", "수원에 살고 있어요")], text, False)
    assert kept == []
    # 인용이 진짜여도 지명 자체가 원문에 없으면 거주지로 받지 않는다.
    kept, _ = attrs.validate_candidates([cand("residence_region", "수원", "경기 남부에서")], text, False)
    assert kept == []


def test_sensitive_values_are_dropped_without_consent_but_the_mention_is_flagged():
    text = "한부모 가정이라 지원금이 필요해요"
    kept, mentioned = attrs.validate_candidates([cand("special_groups", "한부모가정", "한부모 가정")], text, False)
    assert kept == [] and mentioned is True

    kept, mentioned = attrs.validate_candidates([cand("special_groups", "한부모가정", "한부모 가정")], text, True)
    assert len(kept) == 1 and mentioned is False


def test_comma_joined_multi_values_are_split():
    text = "파이썬이랑 SQL 정도 할 줄 알아요"
    kept, _ = attrs.validate_candidates([cand("skills", "파이썬, SQL", "파이썬이랑 SQL")], text, False)
    assert [c.value_label for c in kept] == ["파이썬", "SQL"]


def test_free_text_values_must_be_the_users_own_words():
    # 실모델이 "백엔드 개발자"를 "백엔드 개veloper"로 깨뜨려 냈다.
    text = "경기 남부에서 백엔드 개발자로 일하고 싶어요."
    kept, _ = attrs.validate_candidates(
        [
            cand("desired_job", "백엔드 개veloper", "백엔드 개발자로 일하고 싶어요"),
            cand("desired_job", "백엔드 개발자", "백엔드 개발자로 일하고 싶어요"),
        ],
        text,
        False,
    )
    assert [c.value_label for c in kept] == ["백엔드 개발자"]


def test_sensitive_keywords_flag_a_mention_even_when_the_model_misses_it():
    text = "한부모 가정이라 생활비가 빠듯해서 지원금이 있으면 좋겠어요."
    assert attrs.validate_candidates([], text, allow_sensitive=False) == ([], True)
    # 동의가 있으면 표시는 필요 없다(값은 모델이 뽑은 경우에만 저장된다).
    assert attrs.validate_candidates([], text, allow_sensitive=True) == ([], False)


def test_unknown_keys_are_dropped():
    kept, _ = attrs.validate_candidates([cand("blood_type", "A", "A형")], "저는 A형이에요", False)
    assert kept == []


# ── reconcile (SQLite) ────────────────────────────────────────────────────


@pytest.fixture
def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=[InterviewAnswer.__table__, UserAttribute.__table__, UserConsent.__table__],
            )

    asyncio.run(_create())
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


async def _active(db, user_id):
    return [(r.key, r.value["label"], r.status) for r in await attrs.active_attributes(db, user_id)]


@pytest.mark.asyncio
async def test_a_newer_inference_replaces_an_older_one_and_keeps_history(db_session):
    user_id = uuid.uuid4()
    async with db_session() as db:
        await attrs.reconcile(db, user_id, [cand("residence_region", "수원", "수원")], source_kind="interview_answer")
        await attrs.reconcile(db, user_id, [cand("residence_region", "성남", "성남")], source_kind="interview_answer")
        await db.commit()

        assert await _active(db, user_id) == [("residence_region", "성남", "inferred")]
        all_rows = (await db.execute(select(UserAttribute).where(UserAttribute.user_id == user_id))).scalars().all()
        assert len(all_rows) == 2  # 옛 값은 무효화로 남는다


@pytest.mark.asyncio
async def test_a_value_the_user_edited_is_never_overwritten_by_inference(db_session):
    user_id = uuid.uuid4()
    async with db_session() as db:
        await attrs.add_user_value(db, user_id, "residence_region", "수원")
        await attrs.reconcile(db, user_id, [cand("residence_region", "성남", "성남")], source_kind="interview_answer")
        await db.commit()
        assert await _active(db, user_id) == [("residence_region", "수원", "user_edited")]


@pytest.mark.asyncio
async def test_a_value_the_user_deleted_is_not_revived(db_session):
    user_id = uuid.uuid4()
    async with db_session() as db:
        await attrs.reconcile(db, user_id, [cand("skills", "엑셀", "엑셀")], source_kind="interview_answer")
        row = (await attrs.active_attributes(db, user_id))[0]
        row.status = "rejected"
        await attrs.reconcile(db, user_id, [cand("skills", "엑셀", "엑셀")], source_kind="interview_answer")
        await db.commit()
        assert await _active(db, user_id) == []


@pytest.mark.asyncio
async def test_multi_valued_keys_accumulate_and_duplicates_are_ignored(db_session):
    user_id = uuid.uuid4()
    async with db_session() as db:
        await attrs.reconcile(
            db,
            user_id,
            [cand("skills", "파이썬", "파이썬"), cand("skills", "엑셀", "엑셀"), cand("skills", "파이썬 ", "파이썬")],
            source_kind="interview_answer",
        )
        await db.commit()
        assert sorted(label for _, label, _ in await _active(db, user_id)) == ["엑셀", "파이썬"]


@pytest.mark.asyncio
async def test_match_profile_hides_sensitive_values_until_consent(db_session):
    user_id = uuid.uuid4()
    async with db_session() as db:
        await attrs.set_sensitive_consent(db, user_id, True)
        await attrs.reconcile(
            db,
            user_id,
            [cand("special_groups", "한부모가정", "한부모"), cand("birth_year", "26살", "26살")],
            source_kind="interview_answer",
            today=TODAY,
        )
        await db.commit()
        profile = await attrs.load_match_profile(db, user_id)
        assert profile.special_codes == frozenset({"0014004"})
        assert profile.birth_year == 2000

        # 철회하면 민감 값은 완전히 지워진다(무효화가 아니라 삭제).
        await attrs.set_sensitive_consent(db, user_id, False)
        await db.commit()
        profile = await attrs.load_match_profile(db, user_id)
        assert profile.special_codes == frozenset()
        remaining = (await db.execute(select(UserAttribute).where(UserAttribute.sensitive.is_(True)))).scalars().all()
        assert remaining == []


@pytest.mark.asyncio
async def test_desired_regions_feed_the_match_profile_and_capital_area_expands(db_session):
    user_id = uuid.uuid4()
    async with db_session() as db:
        await attrs.add_user_value(db, user_id, "desired_region", "수원")
        await attrs.add_user_value(db, user_id, "desired_region", "수도권")
        await db.commit()
        profile = await attrs.load_match_profile(db, user_id)
        assert profile.desired_region_codes == frozenset({"41110", "11", "41", "28"})
        # 희망지역은 정책 자격(거주지 기준)과 무관하다 — 정책 매칭 입력으로는 비어 있다.
        assert profile.is_empty


@pytest.mark.asyncio
async def test_summary_lines_never_include_sensitive_values(db_session):
    user_id = uuid.uuid4()
    async with db_session() as db:
        await attrs.set_sensitive_consent(db, user_id, True)
        await attrs.reconcile(
            db,
            user_id,
            [cand("residence_region", "수원", "수원"), cand("marital_status", "기혼", "결혼")],
            source_kind="interview_answer",
        )
        await db.commit()
        assert await attrs.profile_summary_lines(db, user_id) == ["거주지: 수원"]


@pytest.mark.asyncio
async def test_forgetting_an_answer_removes_what_was_inferred_from_it(db_session):
    user_id, answer_id = uuid.uuid4(), uuid.uuid4()
    async with db_session() as db:
        await attrs.reconcile(
            db, user_id, [cand("skills", "엑셀", "엑셀")], source_kind="interview_answer", source_answer_id=answer_id
        )
        await attrs.reconcile(
            db, user_id, [cand("residence_region", "수원", "수원")], source_kind="interview_answer", source_answer_id=answer_id
        )
        confirmed = [r for r in await attrs.active_attributes(db, user_id) if r.key == "residence_region"][0]
        confirmed.status = "confirmed"
        await attrs.forget_answer(db, user_id, answer_id)
        await db.commit()

        rows = await attrs.active_attributes(db, user_id)
        assert [(r.key, r.status) for r in rows] == [("residence_region", "confirmed")]
        assert rows[0].evidence_text is None
