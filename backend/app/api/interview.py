from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_owned_session
from app.db.session import get_db
from app.models.activity_category import ActivityCategory
from app.models.confirmed_fact import ConfirmedFact
from app.models.gap_period import GapPeriod
from app.models.session import Session as SessionModel
from app.schemas.interview import (
    BasedOnRead,
    CategoryExtractRead,
    CategoryExtractRequest,
    CategorySelect,
    CategorySuggestionRead,
    ConfirmedFactRead,
    FactCandidateRead,
    GapPeriodSet,
    InterviewAnswerRead,
    InterviewAnswerRequest,
    InterviewAskRead,
    InterviewConfirmRead,
    InterviewConfirmRequest,
    PeriodExtractRead,
    PeriodExtractRequest,
    RecordExcerptRead,
    RecordsSkipRead,
    StatusRead,
)
from app.services import interview_orchestrator as orchestrator
from app.services.interview_question_bank import next_base_question
from app.services.llm.base import (
    AllProvidersFailedError,
    BasedOn,
    ConfirmedFact as LLMConfirmedFact,
    FactCandidate,
    InterviewContext,
    LLMProvider,
    RecordExcerpt as LLMRecordExcerpt,
)
from app.services.llm.fallback import get_llm_provider
from app.services.record_pipeline.search import get_chunk_search

router = APIRouter(prefix="/sessions", tags=["interview"])


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


async def _build_context(
    db: AsyncSession, session: SessionModel, category: ActivityCategory, chunk_search
) -> tuple[InterviewContext, list]:
    gap_period = (
        await db.execute(select(GapPeriod).where(GapPeriod.session_id == session.id))
    ).scalar_one()
    confirmed_so_far = (
        await db.execute(select(ConfirmedFact).where(ConfirmedFact.category_id == category.id))
    ).scalars().all()

    try:
        excerpts = await chunk_search(session.id, category.label)
    except Exception:
        excerpts = []

    context = InterviewContext(
        session_id=str(session.id),
        category_label=category.label,
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
        asked_questions=[f.source_question_text for f in confirmed_so_far if f.source_question_text],
    )
    return context, list(confirmed_so_far)


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


@router.post("/{session_id}/period/extract", response_model=PeriodExtractRead)
async def extract_period(
    payload: PeriodExtractRequest,
    session: SessionModel = Depends(get_owned_session),
    llm: LLMProvider = Depends(get_llm_provider),
) -> PeriodExtractRead:
    try:
        orchestrator.require_status("period_extract", session.status, "PERIOD_INPUT")
    except orchestrator.StateMachineViolation as exc:
        raise _violation_to_409(exc) from exc

    # Nothing is written to the DB here — same honesty-guardrail reasoning as
    # categories/extract. The real POST /period still owns persisting.
    try:
        suggestion = await llm.extract_period(payload.text, date.today())
    except AllProvidersFailedError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc

    if suggestion is None:
        return PeriodExtractRead(start_date=None, end_date=None)
    return PeriodExtractRead(start_date=suggestion.start_date, end_date=suggestion.end_date)


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


@router.post("/{session_id}/interview/ask", response_model=InterviewAskRead)
async def interview_ask(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    chunk_search=Depends(get_chunk_search),
) -> InterviewAskRead:
    try:
        orchestrator.require_interviewing(session.status)
    except orchestrator.StateMachineViolation as exc:
        raise _violation_to_409(exc) from exc

    if session.current_category_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_current_category")

    category = await db.get(ActivityCategory, session.current_category_id)

    # Idempotent: if a question is already pending and unanswered, return it
    # as-is instead of calling the LLM again (covers refresh/duplicate calls).
    pending = session.pending_turn
    if pending is not None and pending.get("category_id") == str(category.id) and pending.get("candidate_facts") is None:
        return InterviewAskRead(
            category_id=category.id,
            question_text=pending["question_text"],
            question_source=pending["question_source"],
        )

    context, confirmed_so_far = await _build_context(db, session, category, chunk_search)
    answered_fact_types = {f.fact_type for f in confirmed_so_far}
    base_question = next_base_question(category.category_type, answered_fact_types)

    if base_question is not None:
        question_text = base_question.text
        question_source = "base"
        fact_type_hint = base_question.fact_type
    else:
        try:
            question_text = await llm.followup_question(context)
        except AllProvidersFailedError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc
        question_source = "followup"
        fact_type_hint = "followup"

    context_excerpt_ids = [e.chunk_id for e in context.record_excerpts]

    session.pending_turn = {
        "category_id": str(category.id),
        "question_text": question_text,
        "question_source": question_source,
        "fact_type_hint": fact_type_hint,
        "context_excerpt_ids": context_excerpt_ids,
        "candidate_facts": None,
    }
    await db.commit()

    return InterviewAskRead(category_id=category.id, question_text=question_text, question_source=question_source)


@router.post("/{session_id}/interview/answer", response_model=InterviewAnswerRead)
async def interview_answer(
    payload: InterviewAnswerRequest,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    chunk_search=Depends(get_chunk_search),
) -> InterviewAnswerRead:
    try:
        orchestrator.require_interviewing(session.status)
    except orchestrator.StateMachineViolation as exc:
        raise _violation_to_409(exc) from exc

    pending = session.pending_turn
    if pending is None or pending.get("candidate_facts") is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_pending_question")

    category = await db.get(ActivityCategory, uuid.UUID(pending["category_id"]))
    context, _ = await _build_context(db, session, category, chunk_search)

    try:
        candidates: list[FactCandidate] = await llm.extract_facts(
            context, pending["question_text"], payload.text, pending["fact_type_hint"]
        )
    except AllProvidersFailedError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc

    # 정직성 가드레일 강화: 방금 extract_facts에 실제로 넘긴 chunk_id가 아니면
    # record_cited로 인정하지 않는다 — LLM이 근거 자료에 없는 chunk_id를 지어내
    # 인용을 주장할 수 없게. (ask 시점이 아니라 이 호출에서 새로 조회한 context 기준 —
    # 그 사이 새 기록물이 처리 완료됐다면 그것도 유효한 근거로 인정한다.)
    allowed_chunk_ids = {e.chunk_id for e in context.record_excerpts}
    candidate_payload = []
    for candidate in candidates:
        based_on = candidate.based_on
        if based_on.type == "record":
            valid_excerpts = [e for e in based_on.excerpts if e.chunk_id in allowed_chunk_ids]
            based_on = BasedOn(type="record", excerpts=valid_excerpts) if valid_excerpts else BasedOn(type="generic_pattern")
        candidate_payload.append(
            {"content": candidate.content, "fact_type": candidate.fact_type, "based_on": _serialize_based_on(based_on)}
        )

    session.pending_turn = {**pending, "candidate_facts": candidate_payload}
    await db.commit()

    return InterviewAnswerRead(
        candidates=[
            FactCandidateRead(
                index=i,
                content=c["content"],
                fact_type=c["fact_type"],
                based_on=BasedOnRead(**c["based_on"]),
            )
            for i, c in enumerate(candidate_payload)
        ]
    )


@router.post("/{session_id}/interview/confirm", response_model=InterviewConfirmRead)
async def interview_confirm(
    payload: InterviewConfirmRequest,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    chunk_search=Depends(get_chunk_search),
) -> InterviewConfirmRead:
    try:
        orchestrator.require_interviewing(session.status)
    except orchestrator.StateMachineViolation as exc:
        raise _violation_to_409(exc) from exc

    pending = session.pending_turn
    if pending is None or pending.get("candidate_facts") is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_pending_candidates")

    candidate_facts = pending["candidate_facts"]
    category_id = uuid.UUID(pending["category_id"])
    category = await db.get(ActivityCategory, category_id)

    inserted: list[ConfirmedFact] = []
    for confirmation in payload.confirmations:
        if not (0 <= confirmation.index < len(candidate_facts)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="invalid_candidate_index")
        if not confirmation.include:
            continue

        candidate = candidate_facts[confirmation.index]
        based_on = candidate.get("based_on") or {"type": "generic_pattern", "excerpts": []}

        # 정직성 가드레일: source_type은 클라이언트가 아니라 서버가 캐시해둔 후보의
        # was_edited/based_on으로부터만 결정한다 (임의로 record_cited를 주장하지 못하게).
        source_chunk_id: uuid.UUID | None = None
        if confirmation.was_edited:
            source_type = "user_edited"
        elif based_on.get("type") == "record" and based_on.get("excerpts"):
            source_type = "record_cited"
            source_chunk_id = uuid.UUID(based_on["excerpts"][0]["chunk_id"])
        else:
            source_type = "user_confirmed"

        fact = ConfirmedFact(
            category_id=category_id,
            fact_type=candidate["fact_type"],
            content=confirmation.final_text,
            source_type=source_type,
            source_record_chunk_id=source_chunk_id,
            ai_draft_text=candidate["content"],
            source_question_text=pending["question_text"],
        )
        db.add(fact)
        inserted.append(fact)

    session.pending_turn = None
    await db.flush()

    answered_fact_types = {
        f.fact_type
        for f in (await db.execute(select(ConfirmedFact).where(ConfirmedFact.category_id == category_id))).scalars().all()
    }
    remaining_base_question = next_base_question(category.category_type, answered_fact_types)

    if remaining_base_question is not None:
        advance = False
    else:
        # Approximate turn count via row count — a turn can yield 0 or several
        # facts, so this isn't exact, but it only needs to be a safety cap, not
        # a precise counter (see MAX_FOLLOWUPS_PER_CATEGORY).
        followup_fact_ids = (
            await db.execute(
                select(ConfirmedFact.id)
                .where(ConfirmedFact.category_id == category_id, ConfirmedFact.fact_type == "followup")
            )
        ).scalars().all()
        if len(followup_fact_ids) >= orchestrator.MAX_FOLLOWUPS_PER_CATEGORY:
            advance = True
        else:
            try:
                context, _ = await _build_context(db, session, category, chunk_search)
                result = await llm.judge_sufficiency(context)
                advance = result.sufficient
            except AllProvidersFailedError:
                # LLM 판단이 안 되면 안전하게 계속 진행하기보다 멈추지 않도록 다음으로 넘긴다 —
                # 무한정 붙잡아두는 것보다 사용자가 다음 카테고리로 진행할 수 있는 편이 낫다.
                advance = True

    categories = (
        await db.execute(select(ActivityCategory).where(ActivityCategory.session_id == session.id))
    ).scalars().all()

    if advance:
        category.status = "DONE"
        next_status, next_cat = orchestrator.resolve_after_confirm(list(categories), category, advance=True)
    else:
        next_status, next_cat = orchestrator.resolve_after_confirm(list(categories), category, advance=False)

    session.status = next_status
    session.current_category_id = next_cat.id if next_cat else None
    await db.commit()
    for fact in inserted:
        await db.refresh(fact)

    return InterviewConfirmRead(
        status=session.status,
        current_category_id=session.current_category_id,
        category_done=advance,
        confirmed_facts=[ConfirmedFactRead.model_validate(f) for f in inserted],
    )
