from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.interview_answer import InterviewAnswer
from app.models.user_attribute import ATTRIBUTE_KEYS, MULTI_VALUED_KEYS, SENSITIVE_KEYS, UserAttribute
from app.models.user_consent import UserConsent
from app.models.user_preference import UserPreference
from app.models.user import User
from app.schemas.profile import (
    ArchivedAnswerRead,
    ArchiveSummaryRead,
    AttributeCreate,
    AttributeKeyRead,
    AttributeRead,
    AttributesRead,
    AttributeUpdate,
    ConsentRead,
    ConsentUpdate,
    PreferenceRead,
    PreferenceUpdate,
)
from app.services.profile import attributes as attrs
from app.services.profile.vocabulary import CHOICES, KEY_LABELS

router = APIRouter(prefix="/me", tags=["profile"])


def _require_registered(user: User) -> None:
    """문답 아카이브는 이메일로 등록된 계정에만 열어준다.

    게스트 계정은 세션을 하나만 가질 수 있어서(app/api/sessions.py의
    guest_session_limit_reached) 애초에 "세션을 넘어 쌓인 기록"이라는 게
    성립하지 않는다. 기록 자체는 게스트 세션에서도 user_id를 달고 저장되고,
    게스트가 이메일로 회원가입하면 같은 user 행이 승격되므로(app/api/auth.py)
    그 시점부터 여기서 그대로 보인다 — 승격 과정에서 잃는 것은 없다.
    """
    if user.is_guest:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="registered_account_required")


@router.get("/answers", response_model=list[ArchivedAnswerRead])
async def list_archived_answers(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    category_type: str | None = None,
    exclude_session_id: uuid.UUID | None = None,
    confirmed_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[InterviewAnswer]:
    """이 계정에 쌓인 문답 기록, 최신순.

    `exclude_session_id`는 "지금 진행 중인 세션 말고, 예전에 뭐라고 답했더라"를
    보여주기 위한 것이다 — 새 세션이 늘 백지에서 시작하던 이유가 바로 이 조회
    경로가 없어서였다. 여기서 제안된 내용도 결국 인터뷰의 확인 단계를 다시
    거치므로 정직성 가드레일은 그대로다.
    """
    _require_registered(current_user)

    stmt = select(InterviewAnswer).where(InterviewAnswer.user_id == current_user.id)
    if category_type is not None:
        stmt = stmt.where(InterviewAnswer.category_type == category_type)
    if exclude_session_id is not None:
        # session_id IS NULL(원본 세션이 삭제된 기록)은 남겨야 한다 — SQL의
        # `!=`는 NULL을 걸러버리므로 명시적으로 OR로 살린다.
        stmt = stmt.where(
            (InterviewAnswer.session_id.is_(None)) | (InterviewAnswer.session_id != exclude_session_id)
        )
    if confirmed_only:
        # 답변만 하고 확인 단계에서 이탈한 턴은 confirmed_facts가 빈 배열로 남는다.
        stmt = stmt.where(InterviewAnswer.confirmed_facts != [])

    stmt = stmt.order_by(InterviewAnswer.created_at.desc()).limit(limit).offset(offset)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/answers/summary", response_model=ArchiveSummaryRead)
async def get_archive_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ArchiveSummaryRead:
    _require_registered(current_user)

    total_answers = await db.scalar(
        select(func.count()).select_from(InterviewAnswer).where(InterviewAnswer.user_id == current_user.id)
    )
    rows = list(
        (
            await db.execute(
                select(InterviewAnswer.category_type, InterviewAnswer.confirmed_facts).where(
                    InterviewAnswer.user_id == current_user.id
                )
            )
        ).all()
    )
    return ArchiveSummaryRead(
        total_answers=total_answers or 0,
        total_confirmed_facts=sum(len(facts or []) for _, facts in rows),
        category_types=sorted({category_type for category_type, _ in rows}),
    )


@router.delete("/answers/{answer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_archived_answer(
    answer_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """아카이브에서 한 건을 지운다 — 답변 원문이 계정에 계속 남는 이상,
    지울 방법도 같이 있어야 한다.

    그 답변에서 추정한 프로필 속성과 거기 복제된 원문 인용도 같이 지운다
    (attributes.forget_answer) — 원문을 지웠는데 그 일부가 프로필에 남으면 안 된다.

    No `-> None` annotation — 204 응답 본문 assertion 때문(sessions.delete_session 주석 참고).
    """
    _require_registered(current_user)

    answer = await db.get(InterviewAnswer, answer_id)
    if answer is None or answer.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="answer_not_found")
    await attrs.forget_answer(db, current_user.id, answer_id)
    await db.delete(answer)
    await db.commit()


@router.get("/preferences", response_model=PreferenceRead)
async def get_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PreferenceRead:
    """직접 쓴 맞춤 정보. 아직 없으면 빈 문자열을 돌려준다(404가 아니다) —
    화면은 "아직 안 썼음"과 "불러오기 실패"를 구분해야 하고, 전자는 정상이다."""
    _require_registered(current_user)
    row = await db.get(UserPreference, current_user.id)
    if row is None:
        return PreferenceRead(wish_text="", updated_at=None)
    return PreferenceRead(wish_text=row.wish_text or "", updated_at=row.updated_at)


@router.put("/preferences", response_model=PreferenceRead)
async def put_preferences(
    payload: PreferenceUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    extractor=Depends(attrs.get_profile_extractor),
) -> PreferenceRead:
    """맞춤 정보 저장(upsert). 빈 문자열이면 지운 것으로 본다.

    저장만 하고 임베딩은 여기서 다시 계산하지 않는다 — 로컬 Ollama 호출이
    수 초씩 걸려서 "저장" 버튼이 그만큼 멈춰 보인다. 다음 맞춤 공고 조회가
    지문 변화를 감지해 백그라운드로 갱신한다(profile_needs_refresh). 항목
    수집과 같은 stale-while-revalidate 방식이다. 속성 추출도 같은 이유로
    백그라운드에서 돈다.
    """
    _require_registered(current_user)

    user_id = current_user.id
    wish = payload.wish_text.strip()
    row = await db.get(UserPreference, user_id)
    if row is None:
        row = UserPreference(user_id=user_id, wish_text=wish)
        db.add(row)
    else:
        row.wish_text = wish
    await db.commit()
    await db.refresh(row)
    if wish:
        background_tasks.add_task(extractor, user_id, "wish_text", wish)
    return PreferenceRead(wish_text=row.wish_text or "", updated_at=row.updated_at)


# ── 대화로 알게 된 프로필 속성 ────────────────────────────────────────────
#
# 게스트에게도 연다. 속성은 대화 중에 이미 게스트 계정에 쌓이고(인터뷰 답변
# 추출), 맞춤 추천도 게스트를 받는다 — 쌓인 걸 보고 고치고 지울 수단이 없으면
# 안 된다. 가입하면 같은 user 행이 승격되므로 잃는 것도 없다. 단, **민감정보
# 동의는 가입 계정만** 줄 수 있다(아래 PUT /consents/...).


def _attribute_read(row: UserAttribute) -> AttributeRead:
    return AttributeRead(
        id=row.id,
        key=row.key,
        key_label=KEY_LABELS.get(row.key, row.key),
        label=str((row.value or {}).get("label") or ""),
        status=row.status,
        sensitive=row.sensitive,
        source_kind=row.source_kind,
        evidence_text=row.evidence_text,
        created_at=row.created_at,
    )


def _consent_read(row: UserConsent | None) -> ConsentRead:
    if row is None:
        return ConsentRead(granted=False, granted_at=None, sensitive_mentioned=False)
    return ConsentRead(
        granted=row.granted,
        granted_at=row.granted_at if row.granted else None,
        sensitive_mentioned=row.sensitive_mentioned_at is not None and not row.granted,
    )


async def _owned_active_attribute(db: AsyncSession, user_id: uuid.UUID, attribute_id: uuid.UUID) -> UserAttribute:
    row = await db.get(UserAttribute, attribute_id)
    if row is None or row.user_id != user_id or row.invalidated_at is not None or row.status == "rejected":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="attribute_not_found")
    return row


@router.get("/attributes", response_model=AttributesRead)
async def list_attributes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AttributesRead:
    """지금 유효한 속성 전부 + 편집 화면에 필요한 키 목록·선택지·동의 상태."""
    user_id = current_user.id
    rows = await attrs.active_attributes(db, user_id)
    consent = await attrs.get_sensitive_consent(db, user_id)
    return AttributesRead(
        attributes=[_attribute_read(r) for r in rows],
        keys=[
            AttributeKeyRead(
                key=key,
                label=KEY_LABELS[key],
                sensitive=key in SENSITIVE_KEYS,
                multi_valued=key in MULTI_VALUED_KEYS,
                choices=list(CHOICES.get(key, ())),
            )
            for key in ATTRIBUTE_KEYS
        ],
        consent=_consent_read(consent),
    )


@router.post("/attributes", response_model=AttributeRead, status_code=status.HTTP_201_CREATED)
async def create_attribute(
    payload: AttributeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AttributeRead:
    """프로필 화면에서 직접 입력. 단일값 키면 기존 값을 대체한다."""
    user_id = current_user.id
    if payload.key not in ATTRIBUTE_KEYS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_attribute_key")
    if payload.key in SENSITIVE_KEYS and not await attrs.has_sensitive_consent(db, user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="sensitive_consent_required")
    try:
        row = await attrs.add_user_value(db, user_id, payload.key, payload.value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(row)
    return _attribute_read(row)


@router.patch("/attributes/{attribute_id}", response_model=AttributeRead)
async def update_attribute(
    attribute_id: uuid.UUID,
    payload: AttributeUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AttributeRead:
    row = await _owned_active_attribute(db, current_user.id, attribute_id)
    try:
        await attrs.edit_value(db, row, payload.value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(row)
    return _attribute_read(row)


@router.post("/attributes/{attribute_id}/confirm", response_model=AttributeRead)
async def confirm_attribute(
    attribute_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AttributeRead:
    """"맞아요" — 대화 추정 값을 확인한다. 이후 대화 추정이 이 값을 덮어쓰지 않는다."""
    row = await _owned_active_attribute(db, current_user.id, attribute_id)
    if row.status == "inferred":
        row.status = "confirmed"
    await db.commit()
    await db.refresh(row)
    return _attribute_read(row)


@router.delete("/attributes/{attribute_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attribute(
    attribute_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """지운 값은 `rejected`로 남긴다 — 다음 대화에서 같은 값이 다시 추출돼도
    되살리지 않기 위해서다. 민감정보는 그런 기억조차 남기지 않고 완전히 지운다.

    No `-> None` annotation — 204 응답 본문 assertion 때문(sessions.delete_session 주석 참고).
    """
    row = await _owned_active_attribute(db, current_user.id, attribute_id)
    if row.sensitive:
        await db.delete(row)
    else:
        row.status = "rejected"
        row.invalidated_at = datetime.now(timezone.utc)
        row.evidence_text = None
    await db.commit()


@router.get("/consents/sensitive-profiling", response_model=ConsentRead)
async def get_sensitive_consent(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConsentRead:
    return _consent_read(await attrs.get_sensitive_consent(db, current_user.id))


@router.put("/consents/sensitive-profiling", response_model=ConsentRead)
async def put_sensitive_consent(
    payload: ConsentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConsentRead:
    """소득·특화분야(장애·수급·한부모 등)·혼인 정보 수집 동의/철회.

    가입 계정만 동의할 수 있다 — 게스트 계정은 이메일도 없이 기기에 묶인 임시
    계정이라, 민감정보를 맡겼다가 기기를 잃으면 사용자가 지울 방법조차 없다.
    철회하면 민감 속성을 즉시 완전히 지운다.
    """
    user_id = current_user.id
    if payload.granted:
        _require_registered(current_user)
    row = await attrs.set_sensitive_consent(db, user_id, payload.granted)
    await db.commit()
    await db.refresh(row)
    return _consent_read(row)
