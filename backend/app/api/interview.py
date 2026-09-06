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

# 카테고리마다 실제 콘텐츠 질문에 앞서 딱 한 번 묻는 구조적 질문(예산에 포함 안 됨) —
# "공모전"처럼 포괄적인 카테고리 하나에 서로 다른 활동이 여러 개 섞여 있으면, 근거가
# 풍부한 하나에 대해서만 질문하고 끝나버리는 문제(2026-09-06)를 막기 위해 소분류로
# 쪼갤지부터 확인한다. activity_split_checked=True가 되기 전까지만 나온다.
ACTIVITY_BREAKDOWN_QUESTION = (
    "이 카테고리 안에 서로 다른 개별 활동이 여러 개 있나요? "
    "있다면 쉼표나 줄바꿈으로 구분해서 각각 적어주세요. 하나뿐이면 '하나뿐이에요'라고 답해주세요."
)


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
        excerpts = await chunk_search(session.id, category.id)
        # 소분류는 자체 기록물 요청 단계가 없다(부모의 기록물을 공유하기로 확정,
        # 2026-09-06) — 소분류 자신에게 붙은 기록물이 없으면 부모 카테고리의 풀로
        # 한 번 더 검색해본다.
        if not excerpts and category.parent_category_id is not None:
            excerpts = await chunk_search(session.id, category.parent_category_id)
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

    if not payload.categories:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="at_least_one_category_required")

    new_categories = [
        ActivityCategory(
            session_id=session.id,
            category_type=item.category_type,
            custom_label=item.custom_label,
            order_index=idx,
        )
        for idx, item in enumerate(payload.categories)
    ]
    db.add_all(new_categories)
    await db.flush()

    session.status = next_status
    # 기록물 요청 단계도 인터뷰처럼 카테고리를 하나씩 순회한다 — 그 순회의 시작점을
    # 여기서 첫 번째(order_index 0) 카테고리로 잡아둔다.
    session.current_category_id = new_categories[0].id
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
    """현재 카테고리의 기록물 요청을 넘긴다 — 자료를 올렸든 안 올렸든 호출은 동일하다
    (프론트는 이미 올린 게 있으면 "다음 카테고리로", 없으면 "자료 없이 넘어가기"로 라벨만
    바꿔 보여준다). 남은 카테고리가 있으면 그쪽 기록물 요청으로, 마지막이었으면 인터뷰를
    시작한다 (resolve_after_records)."""
    try:
        orchestrator.require_status("records_skip", session.status, "RECORD_UPLOAD")
    except orchestrator.StateMachineViolation as exc:
        raise _violation_to_409(exc) from exc

    current_category = await db.get(ActivityCategory, session.current_category_id) if session.current_category_id else None
    if current_category is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_categories_selected")

    categories = (
        await db.execute(select(ActivityCategory).where(ActivityCategory.session_id == session.id))
    ).scalars().all()

    next_status, next_category = orchestrator.resolve_after_records(list(categories), current_category)
    session.status = next_status
    session.current_category_id = next_category.id
    await db.commit()
    return RecordsSkipRead(status=session.status, current_category_id=next_category.id)


async def _build_pending_turn(
    llm: LLMProvider,
    context: InterviewContext,
    category: ActivityCategory,
    question_text: str,
    question_source: str,
    fact_type_hint: str,
    is_structural: bool = False,
) -> dict:
    """`is_structural=True` is for the "여러 활동 있나요?" check only — it's
    routing info, not a content question, so it shouldn't eat into
    MAX_QUESTIONS_PER_CATEGORY's budget, and there's nothing meaningful for
    the AI to draft an answer to."""
    if is_structural:
        draft_answer = ""
    else:
        try:
            draft_answer = await llm.draft_answer(context, question_text)
        except AllProvidersFailedError:
            # The composer prefill is a convenience, not a required part of
            # the flow (the user can always type from a blank box), so a
            # failure here shouldn't block the question itself from being shown.
            draft_answer = ""

    # Every fresh question — whether the next fixed one, an interleaved
    # drill-down, or a post-base followup — goes through this one function,
    # so incrementing here (rather than at each of its call sites) is the
    # single place that keeps ActivityCategory.questions_asked accurate
    # against MAX_QUESTIONS_PER_CATEGORY.
    if not is_structural:
        category.questions_asked += 1

    return {
        "category_id": str(category.id),
        "question_text": question_text,
        "question_source": question_source,
        "fact_type_hint": fact_type_hint,
        "context_excerpt_ids": [e.chunk_id for e in context.record_excerpts],
        "draft_answer": draft_answer,
        "candidate_facts": None,
    }


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
            draft_answer=pending.get("draft_answer", ""),
        )

    context, confirmed_so_far = await _build_context(db, session, category, chunk_search)

    is_structural = False
    if not category.activity_split_checked:
        question_text = ACTIVITY_BREAKDOWN_QUESTION
        question_source = "split_check"
        fact_type_hint = "activity_breakdown"
        is_structural = True
    else:
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

    session.pending_turn = await _build_pending_turn(
        llm, context, category, question_text, question_source, fact_type_hint, is_structural=is_structural
    )
    draft_answer = session.pending_turn["draft_answer"]
    await db.commit()

    return InterviewAskRead(
        category_id=category.id, question_text=question_text, question_source=question_source, draft_answer=draft_answer
    )


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

    if pending["fact_type_hint"] == "activity_breakdown":
        # 이 답변은 서사적 사실이 아니라 "이 카테고리를 소분류로 쪼갤지" 라우팅
        # 정보다 — extract_facts(정직성 가드레일이 적용되는 일반 경로) 대신 전용
        # 파서를 쓰고, 결과를 candidate_facts와 같은 모양으로 감싸 리뷰 UI를
        # 그대로 재사용한다(interview_confirm의 activity_breakdown 분기가 처리).
        try:
            items = await llm.extract_activity_items(category.label, payload.text)
        except AllProvidersFailedError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc

        candidate_payload = [
            {"content": item, "fact_type": "activity_breakdown", "based_on": _serialize_based_on(BasedOn(type="generic_pattern"))}
            for item in items
        ]
        session.pending_turn = {**pending, "candidate_facts": candidate_payload}
        await db.commit()
        return InterviewAnswerRead(
            candidates=[
                FactCandidateRead(index=i, content=c["content"], fact_type=c["fact_type"], based_on=BasedOnRead(**c["based_on"]))
                for i, c in enumerate(candidate_payload)
            ]
        )

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
            # fact_type is always forced to the hint the question was actually
            # asked under, never the LLM's own free choice — a base question
            # maps 1:1 to one fact_type, and next_base_question() decides
            # whether a category is done purely by checking which fact_types
            # have a confirmed row. A weaker model that echoes back the wrong
            # fact_type (observed with the local dev model: it kept relabeling
            # a hardship_and_coping answer as study_goal/study_method) would
            # otherwise make that fact_type look permanently unanswered and
            # the same base question would repeat forever — this is the fix
            # for the "질문에 답해도 다음 단계로 안 넘어감" bug (2026-09-05).
            {"content": candidate.content, "fact_type": pending["fact_type_hint"], "based_on": _serialize_based_on(based_on)}
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

    if pending["fact_type_hint"] == "activity_breakdown":
        # "활동 목록"은 인용 가능한 서사적 사실이 아니라 라우팅 정보이므로, 일반
        # ConfirmedFact 삽입/충분성 판단 로직을 완전히 건너뛴다.
        items = [
            candidate_facts[c.index]["content"]
            for c in payload.confirmations
            if c.include and 0 <= c.index < len(candidate_facts) and candidate_facts[c.index]["content"].strip()
        ]
        category.activity_split_checked = True
        if len(items) >= 2:
            children = [
                ActivityCategory(
                    session_id=session.id,
                    category_type=category.category_type,
                    custom_label=item,
                    parent_category_id=category.id,
                    order_index=idx,
                    activity_split_checked=True,
                )
                for idx, item in enumerate(items)
            ]
            db.add_all(children)
            await db.flush()
            category.status = "DONE"  # 컨테이너 — 직접 인터뷰되지 않음
            session.current_category_id = children[0].id
        session.pending_turn = None
        await db.commit()
        return InterviewConfirmRead(
            status=session.status,
            current_category_id=session.current_category_id,
            category_done=False,
            confirmed_facts=[],
        )

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

    # 카테고리당 총 질문 수(고정+AI 합산) 상한 — 도달했으면 남은 고정 질문이 있든,
    # AI가 더 캐묻고 싶어하든 무조건 다음으로 넘긴다 (2026-09-05: "카테고리당 질문
    # 횟수를 늘리자. 3회까지" — 총 개수를 낮춰 AI 판단의 비중을 상대적으로 높이는 방향).
    if category.questions_asked >= orchestrator.MAX_QUESTIONS_PER_CATEGORY:
        advance = True
    else:
        answered_fact_types = {
            f.fact_type
            for f in (await db.execute(select(ConfirmedFact).where(ConfirmedFact.category_id == category_id))).scalars().all()
        }
        remaining_base_question = next_base_question(category.category_type, answered_fact_types)

        if remaining_base_question is not None:
            advance = False
            # Even while fixed questions remain, let the AI interject one
            # narrower drill-down when the answer just confirmed bundled
            # several things together or stayed vague (e.g. "기획과 개발을
            # 담당했어요") instead of marching straight on to the next,
            # unrelated fixed question with no chance to get a concrete
            # example (2026-09-05 request: "답변마다 AI가 바로 파고들지 판단").
            try:
                context, _ = await _build_context(db, session, category, chunk_search)
                decision = await llm.judge_drilldown(context)
            except AllProvidersFailedError:
                decision = None
            if decision is not None and decision.should_ask and decision.question_text:
                session.pending_turn = await _build_pending_turn(
                    llm, context, category, decision.question_text, "followup", "followup"
                )
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
