from __future__ import annotations

import random
import uuid
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_owned_session
from app.db.session import get_db
from app.models.activity_category import ActivityCategory
from app.models.confirmed_fact import ConfirmedFact
from app.models.gap_period import GapPeriod
from app.models.interview_answer import InterviewAnswer
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
from app.services.coverage import has_period_clue
from app.services.interview_question_bank import next_base_question
from app.services.llm.base import (
    PROBE_FOCUSES,
    LLMUnavailableError,
    BasedOn,
    ConfirmedFact as LLMConfirmedFact,
    FactCandidate,
    InterviewContext,
    LLMProvider,
    RecordExcerpt as LLMRecordExcerpt,
)
from app.services.llm import get_llm_provider
from app.services.profile.attributes import get_profile_extractor, profile_summary_lines
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


# judge_drilldown이 모든 LLM provider 실패로 아예 호출 불가능할 때 쓰는 규칙 기반
# 백업(2026-09-06) — 로컬 dev 환경처럼 폴백 provider(Gemini)도 플레이스홀더 키라 실패하는
# 상황에서, LLM 판단 없이도 최소한의 구체화 질문 하나는 보장하기 위함이다. LLM 판단만큼
# 정교하지 않다 — 정밀한 판단이 필요 없는 최후의 안전망일 뿐이므로 임계값은 넉넉하게 잡는다.
_VAGUE_ANSWER_MIN_LENGTH = 20
_GENERIC_PROBE_QUESTION = "조금 더 구체적으로 말씀해주시겠어요? 그때 있었던 구체적인 상황이나 예시를 알려주세요."


def _is_vague_answer(facts: list[ConfirmedFact]) -> bool:
    combined = " ".join(f.content for f in facts).strip()
    return len(combined) < _VAGUE_ANSWER_MIN_LENGTH


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


async def _load_confirmed_facts(db: AsyncSession, category: ActivityCategory) -> list[ConfirmedFact]:
    return list(
        (await db.execute(select(ConfirmedFact).where(ConfirmedFact.category_id == category.id))).scalars().all()
    )


# 이 fact_type이 확정되면 활동 기간을 유추해볼 만하다고 본다 — 카테고리 유형별
# 고정 질문 목록에서 "얼마나 자주, 어느 정도 기간 동안" / "어떤 상황에서"에 해당하는
# 슬롯들이다(interview_question_bank.py). 카테고리가 끝날 때까지 기다리지 않고 여기서
# 시도하는 이유는, 기간을 알아야 후속 질문 예산(orchestrator.followup_budget)을 그
# 카테고리에 맞게 늘려줄 수 있고 커버리지도 인터뷰 도중에 의미를 갖기 때문이다.
_PERIOD_HINT_FACT_TYPES = frozenset({"frequency", "context"})


async def _maybe_infer_category_period(
    db: AsyncSession,
    session: SessionModel,
    category: ActivityCategory,
    facts: list[ConfirmedFact],
    llm: LLMProvider,
) -> None:
    """확정된 사실에서 이 활동의 기간을 한 번만 유추해 저장한다.

    사용자가 직접 지정한 기간(period_source="user_set")은 절대 덮어쓰지 않는다.
    실패는 조용히 넘긴다 — 기간은 커버리지 계산용 메타데이터일 뿐이라, 이걸
    못 구했다고 인터뷰 턴 자체를 실패시킬 이유가 없다(기간 미상 카테고리는
    coverage report의 categories_without_period로 그대로 드러난다).
    """
    if category.period_start is not None or category.period_source == "user_set":
        return
    if not _PERIOD_HINT_FACT_TYPES & {f.fact_type for f in facts}:
        return
    # 사실에 기간 단서가 하나도 없으면 아예 묻지 않는다 — 로컬 모델은 이 경우
    # "모르겠다" 대신 공백 기간 전체를 되뱉는다(coverage.has_period_clue 주석 참고).
    # LLM 호출 한 번도 아낀다.
    if not has_period_clue(f.content for f in facts):
        return

    gap_period = (
        await db.execute(select(GapPeriod).where(GapPeriod.session_id == session.id))
    ).scalar_one_or_none()
    if gap_period is None:
        return

    llm_facts = [
        LLMConfirmedFact(id=str(f.id), content=f.content, source_type=f.source_type, fact_type=f.fact_type)
        for f in facts
    ]
    try:
        suggestion = await llm.extract_activity_period(
            category.label, llm_facts, gap_period.start_date, gap_period.end_date
        )
    except Exception:
        return
    if suggestion is None:
        return

    category.period_start = suggestion.start_date
    category.period_end = suggestion.end_date
    category.period_source = "ai_inferred"


async def _build_context(
    db: AsyncSession,
    session: SessionModel,
    category: ActivityCategory,
    chunk_search,
    query_text: str | None = None,
) -> tuple[InterviewContext, list]:
    """`query_text` is the question we are about to ask (or just asked). It is
    what makes the record search a *search*: chunk_search embeds it and ranks
    the user's own records by cosine distance against it, instead of handing
    back whichever five chunks happened to be parsed first. Pass None only
    where there is no meaningful query (the structural "여러 활동 있나요?" turn).
    """
    gap_period = (
        await db.execute(select(GapPeriod).where(GapPeriod.session_id == session.id))
    ).scalar_one()
    confirmed_so_far = await _load_confirmed_facts(db, category)

    try:
        excerpts = await chunk_search(session.id, category.id, query_text)
        # 소분류는 자체 기록물 요청 단계가 없다(부모의 기록물을 공유하기로 확정,
        # 2026-09-06) — 소분류 자신에게 붙은 기록물이 없으면 부모 카테고리의 풀로
        # 한 번 더 검색해본다.
        if not excerpts and category.parent_category_id is not None:
            excerpts = await chunk_search(session.id, category.parent_category_id, query_text)
    except Exception:
        excerpts = []

    # 다른 세션·검색에서 이미 알게 된 사람 단위 속성(비민감만). 후속/드릴다운
    # 질문이 아는 걸 다시 묻지 않게 한다 — draft_answer에는 넣지 않는다
    # (InterviewContext.profile_summary 주석 참고).
    profile_summary = await profile_summary_lines(db, session.user_id)

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
        profile_summary=profile_summary,
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
    except LLMUnavailableError as exc:
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
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc

    # 활동을 하나도 못 찾았을 때만 AI에게 되묻는 질문을 만들게 한다. "잘 모르겠어"
    # 같은 답에 같은 질문을 되풀이하면 사용자는 똑같이 막히기 때문이다(2026-09-09
    # 요청). 정상 경로에는 LLM 호출이 늘지 않는다.
    #
    # 실패해도 질문 전체를 실패시키지 않는다 — Gemini 폴백을 제거한 뒤 로컬
    # Ollama가 유일한 경로라 터널이 끊기면 여기도 같이 죽는데, 그때는 None으로
    # 두고 프론트가 정적 예시 안내로 돌아가게 한다.
    followup_question = None
    if not suggestions:
        try:
            followup_question = await llm.probe_activity_question(
                payload.text,
                gap_period.start_date,
                gap_period.end_date,
                # 갈래는 여기서 고른다 — 매번 다른 각도로 물어보게 된다.
                random.choice(PROBE_FOCUSES),
            )
        except LLMUnavailableError:
            followup_question = None

    return CategoryExtractRead(
        suggestions=[
            CategorySuggestionRead(category_type=s.category_type, custom_label=s.custom_label) for s in suggestions
        ],
        followup_question=followup_question,
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
    routing info, not a content question, so it shouldn't eat into either
    question budget, and there's nothing meaningful for the AI to draft an
    answer to."""
    if is_structural:
        draft_answer = ""
    else:
        try:
            draft_answer = await llm.draft_answer(context, question_text)
        except LLMUnavailableError:
            # The composer prefill is a convenience, not a required part of
            # the flow (the user can always type from a blank box), so a
            # failure here shouldn't block the question itself from being shown.
            draft_answer = ""

    # Every fresh question — whether the next fixed one, an interleaved
    # drill-down, or a post-base followup — goes through this one function,
    # so incrementing here (rather than at each of its call sites) is the
    # single place that keeps the two budgets accurate: fixed ("base")
    # questions and AI-added ("followup", covering both drill-downs and
    # post-base followups) are tracked separately since only the latter is
    # capped (MAX_FOLLOWUP_QUESTIONS_PER_CATEGORY).
    if not is_structural:
        if question_source == "followup":
            category.followup_questions_asked += 1
        else:
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

    # 질문을 먼저 정하고, 그 질문 문구로 기록물을 검색한다. 순서가 반대였을 때는
    # (2026-09-09 이전) 검색어가 없어 카테고리에 붙은 청크를 작성순으로 자르는 게
    # 전부였고, record_chunks.embedding은 한 번도 조회되지 않았다.
    is_structural = False
    if not category.activity_split_checked:
        question_text = ACTIVITY_BREAKDOWN_QUESTION
        question_source = "split_check"
        fact_type_hint = "activity_breakdown"
        is_structural = True
    else:
        confirmed_so_far = await _load_confirmed_facts(db, category)
        answered_fact_types = {f.fact_type for f in confirmed_so_far}
        base_question = next_base_question(category.category_type, answered_fact_types)

        if base_question is not None:
            question_text = base_question.text
            question_source = "base"
            fact_type_hint = base_question.fact_type
        else:
            # 후속 질문은 질문 자체를 만들기 위해 컨텍스트가 먼저 필요하다 —
            # 아직 질문 문구가 없으므로 카테고리 이름을 검색어로 쓴다.
            context, _ = await _build_context(db, session, category, chunk_search, query_text=category.label)
            try:
                question_text = await llm.followup_question(context)
            except LLMUnavailableError as exc:
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc
            question_source = "followup"
            fact_type_hint = "followup"

    context, _ = await _build_context(
        db, session, category, chunk_search, query_text=None if is_structural else question_text
    )

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
    background_tasks: BackgroundTasks,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    chunk_search=Depends(get_chunk_search),
    extractor=Depends(get_profile_extractor),
) -> InterviewAnswerRead:
    try:
        orchestrator.require_interviewing(session.status)
    except orchestrator.StateMachineViolation as exc:
        raise _violation_to_409(exc) from exc

    pending = session.pending_turn
    if pending is None or pending.get("candidate_facts") is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_pending_question")

    category = await db.get(ActivityCategory, uuid.UUID(pending["category_id"]))
    context, _ = await _build_context(db, session, category, chunk_search, query_text=pending["question_text"])

    if pending["fact_type_hint"] == "activity_breakdown":
        # 이 답변은 서사적 사실이 아니라 "이 카테고리를 소분류로 쪼갤지" 라우팅
        # 정보다 — extract_facts(정직성 가드레일이 적용되는 일반 경로) 대신 전용
        # 파서를 쓰고, 결과를 candidate_facts와 같은 모양으로 감싸 리뷰 UI를
        # 그대로 재사용한다(interview_confirm의 activity_breakdown 분기가 처리).
        try:
            items = await llm.extract_activity_items(category.label, payload.text)
        except LLMUnavailableError as exc:
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
    except LLMUnavailableError as exc:
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

    # 계정 단위 문답 기록. 여기가 사용자가 실제로 타이핑한 문장을 붙잡을 수 있는
    # 유일한 지점이다 — 이 아래로는 extract_facts가 요약한 짧은 사실 문장만 남는다.
    # 확정 여부와 무관하게 먼저 남기고(답변만 하고 이탈한 턴도 기록으로는 남는다),
    # 확정된 사실 스냅샷은 interview_confirm이 이 행에 채운다.
    answer_log = InterviewAnswer(
        user_id=session.user_id,
        session_id=session.id,
        category_label=category.label,
        category_type=category.category_type,
        question_text=pending["question_text"],
        question_source=pending["question_source"],
        answer_text=payload.text,
    )
    db.add(answer_log)
    await db.flush()

    session.pending_turn = {
        **pending,
        "candidate_facts": candidate_payload,
        "answer_log_id": str(answer_log.id),
    }
    user_id, answer_id = session.user_id, answer_log.id
    await db.commit()

    # 답변 원문에서 사람 단위 속성(나이·거주지·학력·희망직무 …)을 뽑아 프로필로
    # 남긴다. 응답을 보낸 뒤 백그라운드에서 돈다 — 사용자가 후보 사실을 검토하는
    # 동안이 로컬 Ollama가 비어 있는 시간이다. 구조 질문(activity_breakdown)은 위에서
    # 이미 반환했으므로 여기 오지 않는다.
    background_tasks.add_task(extractor, user_id, "interview_answer", payload.text, answer_id)

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
        #
        # final_text(사용자가 확정한 값)를 쓴다 — candidate_facts[index]["content"](AI가
        # 처음 제안한 값)를 썼던 이전 버전은 "고쳐 쓰기"로 항목 이름을 수정해도 반영이
        # 안 되는 버그였다. index가 candidate_facts 범위를 넘어가는 항목(프론트에서 새로
        # 추가한 항목)도 그냥 final_text 그대로 받아들인다 — 애초에 이 목록엔 서버가 검증할
        # "근거"가 없으므로(전부 generic_pattern) candidate_facts 조회 자체가 필요 없다.
        items = [c.final_text.strip() for c in payload.confirmations if c.include and c.final_text.strip()]
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
        if confirmation.index < 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="invalid_candidate_index")
        if not confirmation.include or not confirmation.final_text.strip():
            # 빈 문자열은 그냥 조용히 건너뛴다 — 새로 추가한 항목을 다 채우지 않고
            # 제출한 경우(2026-09-06, "+ 새 항목 추가") 빈 확정 사실이 만들어지는 걸 막는다.
            continue

        # index >= len(candidate_facts)는 프론트에서 새로 추가한 항목(원래 AI 후보
        # 목록에 없던 것)이다 — candidate=None으로 두고, 근거 없는 사용자 작성 항목으로
        # 취급한다(아래에서 was_edited와 동일하게 처리).
        candidate = candidate_facts[confirmation.index] if confirmation.index < len(candidate_facts) else None
        based_on = (candidate or {}).get("based_on") or {"type": "generic_pattern", "excerpts": []}

        # 정직성 가드레일: source_type은 클라이언트가 아니라 서버가 캐시해둔 후보의
        # was_edited/based_on으로부터만 결정한다 (임의로 record_cited를 주장하지 못하게).
        source_chunk_id: uuid.UUID | None = None
        if confirmation.was_edited or candidate is None:
            source_type = "user_edited"
        elif based_on.get("type") == "record" and based_on.get("excerpts"):
            source_type = "record_cited"
            source_chunk_id = uuid.UUID(based_on["excerpts"][0]["chunk_id"])
        else:
            source_type = "user_confirmed"

        fact = ConfirmedFact(
            category_id=category_id,
            # candidate_payload always sets fact_type to pending["fact_type_hint"]
            # uniformly (interview_answer, above) — reading it from here directly
            # also correctly covers a manually-added candidate (candidate=None).
            fact_type=pending["fact_type_hint"],
            content=confirmation.final_text,
            source_type=source_type,
            source_record_chunk_id=source_chunk_id,
            ai_draft_text=(candidate or {}).get("content"),
            source_question_text=pending["question_text"],
        )
        db.add(fact)
        inserted.append(fact)

    # 계정 단위 문답 기록에 "이 답변에서 실제로 확정된 것"을 스냅샷으로 남긴다 —
    # 세션이 지워져도(confirmed_facts는 CASCADE로 사라진다) 이 요약은 남는다.
    answer_log_id = pending.get("answer_log_id")
    if answer_log_id:
        answer_log = await db.get(InterviewAnswer, uuid.UUID(answer_log_id))
        if answer_log is not None:
            answer_log.confirmed_facts = [
                {"content": f.content, "fact_type": f.fact_type, "source_type": f.source_type}
                for f in inserted
            ]

    session.pending_turn = None
    await db.flush()

    all_facts = list(
        (await db.execute(select(ConfirmedFact).where(ConfirmedFact.category_id == category_id))).scalars().all()
    )
    answered_fact_types = {f.fact_type for f in all_facts}
    await _maybe_infer_category_period(db, session, category, all_facts, llm)

    remaining_base_question = next_base_question(category.category_type, answered_fact_types)
    # AI 추가 질문(드릴다운/후속) 전용 예산 — 고정 질문 자체는 이 예산과 무관하게
    # 항상 전부 물어본다(2026-09-06, orchestrator.MAX_FOLLOWUP_QUESTIONS_PER_CATEGORY
    # 참고). 예전엔 고정+AI를 하나의 상한으로 묶어서, 예산이 바닥나면 "성과/결과"
    # 같은 마지막 고정 질문이 아직 안 나왔어도 강제로 다음 카테고리로 넘어가 버렸다.
    # 상한 자체는 활동 기간에 따라 달라진다(orchestrator.followup_budget).
    followup_budget_left = category.followup_questions_asked < orchestrator.followup_budget(category)

    if remaining_base_question is not None:
        advance = False
        # Even while fixed questions remain, let the AI interject one
        # narrower drill-down when the answer just confirmed bundled
        # several things together or stayed vague (e.g. "기획과 개발을
        # 담당했어요") instead of marching straight on to the next,
        # unrelated fixed question with no chance to get a concrete
        # example (2026-09-05 request: "답변마다 AI가 바로 파고들지 판단"). Skipped
        # entirely once the followup budget is spent — no point spending an
        # LLM call on a decision we won't act on.
        if followup_budget_left:
            should_ask, drilldown_question_text = False, None
            try:
                context, _ = await _build_context(db, session, category, chunk_search, query_text=pending["question_text"])
                decision = await llm.judge_drilldown(context)
                should_ask, drilldown_question_text = decision.should_ask, decision.question_text
            except LLMUnavailableError:
                # 모든 LLM provider가 막혀 있으면(로컬 dev 환경의 알려진 한계 — 플레이스홀더
                # GEMINI_API_KEY라 로컬 모델이 JSON 파싱에 실패해도 폴백이 안 됨) 정교한
                # 판단 대신 규칙 기반 백업으로 최소한의 구체화는 보장한다: 방금 확정된
                # 답변이 아주 짧으면(명사구 수준, 구체적 설명 없음) 정형화된 구체화
                # 질문을 하나 끼워넣는다.
                if _is_vague_answer(inserted):
                    should_ask, drilldown_question_text = True, _GENERIC_PROBE_QUESTION
            if should_ask and drilldown_question_text:
                session.pending_turn = await _build_pending_turn(
                    llm, context, category, drilldown_question_text, "followup", "followup"
                )
    elif followup_budget_left:
        try:
            context, _ = await _build_context(db, session, category, chunk_search, query_text=pending["question_text"])
            result = await llm.judge_sufficiency(context)
            advance = result.sufficient
        except LLMUnavailableError:
            # LLM 판단이 안 되면 안전하게 계속 진행하기보다 멈추지 않도록 다음으로 넘긴다 —
            # 무한정 붙잡아두는 것보다 사용자가 다음 카테고리로 진행할 수 있는 편이 낫다.
            advance = True
    else:
        # 후속 질문 예산 소진 — LLM이 계속 부족하다고 판단하더라도(judge_sufficiency를
        # 호출할 필요조차 없이) 더 묻지 않고 다음 카테고리로 넘긴다.
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
