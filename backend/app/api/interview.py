from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sessions import category_label
from app.core.deps import get_owned_session
from app.db.session import get_db
from app.models.activity_category import ActivityCategory
from app.models.confirmed_fact import ConfirmedFact
from app.models.gap_period import GapPeriod
from app.models.session import Session as SessionModel
from app.schemas.session import (
    BasedOnRead,
    CategoryExtractRead,
    CategoryExtractRequest,
    CategorySelect,
    CategorySuggestionRead,
    GapPeriodSet,
    InterviewConfirm,
    InterviewConfirmRead,
    InterviewNextRead,
    RecordExcerptRead,
    RecordsSkipRead,
    StatusRead,
)
from app.services import interview_orchestrator as orchestrator
from app.services.llm.base import (
    AllProvidersFailedError,
    BasedOn,
    ConfirmedFact as LLMConfirmedFact,
    InterviewContext,
    LLMProvider,
    RecordExcerpt as LLMRecordExcerpt,
    Suggestion,
)
from app.services.llm.fallback import FallbackProvider
from app.services.record_pipeline.search import get_chunk_search

router = APIRouter(prefix="/sessions", tags=["interview"])


def get_llm_provider() -> LLMProvider:
    return FallbackProvider()


def _violation_to_409(exc: orchestrator.StateMachineViolation) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _serialize_based_on(based_on: BasedOn) -> dict:
    return {
        "type": based_on.type,
        "excerpts": [
            {"chunk_id": e.chunk_id, "text": e.text, "published_at": e.published_at.isoformat() if e.published_at else None}
            for e in based_on.excerpts
        ],
    }


@router.post("/{session_id}/period", response_model=StatusRead)
async def set_period(
    payload: GapPeriodSet,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
) -> StatusRead:
    try:
        next_status = orchestrator.require_simple_transition("period", session.status)
    except orchestrator.StateMachineViolation as exc:
        raise _violation_to_409(exc) from exc

    db.add(GapPeriod(session_id=session.id, start_date=payload.start_date, end_date=payload.end_date))
    session.status = next_status
    await db.commit()
    return StatusRead(status=session.status)


@router.post("/{session_id}/categories", response_model=StatusRead)
async def select_categories(
    payload: CategorySelect,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
) -> StatusRead:
    try:
        next_status = orchestrator.require_simple_transition("categories", session.status)
    except orchestrator.StateMachineViolation as exc:
        raise _violation_to_409(exc) from exc

    for idx, item in enumerate(payload.categories):
        db.add(
            ActivityCategory(
                session_id=session.id,
                category_type=item.category_type,
                custom_label=item.custom_label,
                order_index=idx,
            )
        )
    session.status = next_status
    await db.commit()
    return StatusRead(status=session.status)


@router.post("/{session_id}/categories/extract", response_model=CategoryExtractRead)
async def extract_categories(
    payload: CategoryExtractRequest,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
) -> CategoryExtractRead:
    try:
        orchestrator.require_status("categories_extract", session.status, "CATEGORY_SELECT")
    except orchestrator.StateMachineViolation as exc:
        raise _violation_to_409(exc) from exc

    gap_period = (
        await db.execute(select(GapPeriod).where(GapPeriod.session_id == session.id))
    ).scalar_one()

    # Nothing is written to the DB here — these are only suggestions. The
    # user must review/edit them and call POST /categories to actually
    # persist anything (honesty guardrail: an AI guess is not a confirmed fact).
    try:
        suggestions = await llm.extract_categories(payload.text, gap_period.start_date, gap_period.end_date)
    except AllProvidersFailedError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc

    return CategoryExtractRead(
        suggestions=[
            CategorySuggestionRead(category_type=s.category_type, custom_label=s.custom_label) for s in suggestions
        ]
    )


@router.post("/{session_id}/records/skip", response_model=RecordsSkipRead)
async def skip_records(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
) -> RecordsSkipRead:
    try:
        next_status = orchestrator.require_simple_transition("records_skip", session.status)
    except orchestrator.StateMachineViolation as exc:
        raise _violation_to_409(exc) from exc

    first_category = (
        await db.execute(
            select(ActivityCategory)
            .where(ActivityCategory.session_id == session.id)
            .order_by(ActivityCategory.order_index)
        )
    ).scalars().first()
    if first_category is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_categories_selected")

    session.status = next_status
    session.current_category_id = first_category.id
    await db.commit()
    return RecordsSkipRead(status=session.status, current_category_id=first_category.id)


@router.get("/{session_id}/interview/next", response_model=InterviewNextRead)
async def interview_next(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    chunk_search=Depends(get_chunk_search),
) -> InterviewNextRead:
    draft_step = session.status
    try:
        confirm_step = orchestrator.require_draft_step(draft_step)
    except orchestrator.StateMachineViolation as exc:
        raise _violation_to_409(exc) from exc

    if session.current_category_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_current_category")

    category = await db.get(ActivityCategory, session.current_category_id)
    label = category_label(category)
    fact_type = orchestrator.FACT_TYPE_BY_STEP[draft_step]

    gap_period = (
        await db.execute(select(GapPeriod).where(GapPeriod.session_id == session.id))
    ).scalar_one()
    confirmed_so_far = (
        await db.execute(select(ConfirmedFact).where(ConfirmedFact.category_id == category.id))
    ).scalars().all()

    try:
        excerpts = await chunk_search(session.id, label)
    except Exception:
        excerpts = []

    context = InterviewContext(
        session_id=str(session.id),
        category_label=label,
        gap_start=gap_period.start_date,
        gap_end=gap_period.end_date,
        confirmed_facts_so_far=[
            LLMConfirmedFact(id=str(f.id), content=f.content, source_type=f.source_type, fact_type=f.fact_type)
            for f in confirmed_so_far
        ],
        record_excerpts=[
            LLMRecordExcerpt(chunk_id=str(e.chunk_id), text=e.text, published_at=e.published_at)
            for e in excerpts
        ],
    )

    try:
        suggestion: Suggestion = await llm.draft_suggestion(context, fact_type)
    except AllProvidersFailedError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc

    based_on_payload = _serialize_based_on(suggestion.based_on)

    session.status = confirm_step
    session.pending_draft = {
        "step": confirm_step,
        "category_id": str(category.id),
        "draft_text": suggestion.draft_text,
        "based_on": based_on_payload,
    }
    await db.commit()

    return InterviewNextRead(
        step=draft_step,
        category_id=category.id,
        ai_draft=suggestion.draft_text,
        based_on=BasedOnRead(
            type=based_on_payload["type"],
            excerpts=[RecordExcerptRead(**e) for e in based_on_payload["excerpts"]],
        ),
    )


@router.post("/{session_id}/interview/confirm", response_model=InterviewConfirmRead)
async def interview_confirm(
    payload: InterviewConfirm,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
) -> InterviewConfirmRead:
    try:
        orchestrator.require_confirm_step(session.status)
    except orchestrator.StateMachineViolation as exc:
        raise _violation_to_409(exc) from exc

    if payload.step != session.status:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="step_mismatch")

    draft = session.pending_draft
    if draft is None or draft.get("step") != session.status:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_pending_draft")

    # 정직성 가드레일: source_type은 클라이언트가 아니라 서버가 캐시해둔 초안의
    # was_edited/based_on으로부터만 결정한다 (임의로 record_cited를 주장하지 못하게).
    based_on = draft.get("based_on") or {"type": "generic_pattern", "excerpts": []}
    source_chunk_id: uuid.UUID | None = None
    if payload.was_edited:
        source_type = "user_edited"
    elif based_on.get("type") == "record" and based_on.get("excerpts"):
        source_type = "record_cited"
        source_chunk_id = uuid.UUID(based_on["excerpts"][0]["chunk_id"])
    else:
        source_type = "user_confirmed"

    category_id = uuid.UUID(draft["category_id"])
    fact_type = orchestrator.FACT_TYPE_BY_STEP[session.status]

    db.add(
        ConfirmedFact(
            category_id=category_id,
            fact_type=fact_type,
            content=payload.final_text,
            source_type=source_type,
            source_record_chunk_id=source_chunk_id,
            ai_draft_text=draft.get("draft_text"),
        )
    )
    session.pending_draft = None

    if session.status == "ACHIEVEMENT_CONFIRM":
        category = await db.get(ActivityCategory, category_id)
        category.status = "DONE"
        categories = (
            await db.execute(select(ActivityCategory).where(ActivityCategory.session_id == session.id))
        ).scalars().all()
        next_status, next_cat = orchestrator.resolve_after_achievement_confirm(list(categories), category)
        session.status = next_status
        session.current_category_id = next_cat.id if next_cat else None
    else:
        session.status = orchestrator.NEXT_STEP_AFTER_CONFIRM[session.status]

    await db.commit()
    return InterviewConfirmRead(status=session.status, current_category_id=session.current_category_id)
