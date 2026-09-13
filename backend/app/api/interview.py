from __future__ import annotations

import functools
import logging
import random
import uuid
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.deps import get_owned_session
from app.db.session import get_background_session_factory, get_db
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
    CategoryReviewRead,
    InterviewConfirmRead,
    InterviewConfirmRequest,
    InterviewReviewRequest,
    ReviewGroupRead,
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

logger = logging.getLogger(__name__)

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


def _is_vague_answer(texts: list[str]) -> bool:
    """방금 답에서 뽑은 사실 문장들이 너무 짧은가. 뽑힌 게 없으면(빈 목록) 모호한 답으로 본다."""
    combined = " ".join(texts).strip()
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


# ── 카테고리 단위 확인(2026-09-11) ─────────────────────────────────────────
#
# 답변마다 사실 카드를 확인받던 흐름을 "카테고리 질문이 끝날 때 한 번"으로 바꿨다
# (답변마다 확인을 누르는 게 번거롭다는 요청). 카테고리 도중에 뽑은 사실은
# activity_categories.draft_turns에 초안으로 쌓이고, 다음 질문·드릴다운·충분성·기간
# 추론 같은 **진행 판단은 확정 사실 + 초안**으로 한다. confirmed_facts에는 카테고리
# 끝 확인(POST /interview/review)에서만 들어간다 — 정직성 가드레일은 확인 시점만
# 옮겨졌을 뿐 그대로다. 초안은 LLM이 무엇을 이미 들었는지 아는 데만 쓰이고 인용되지 않는다.


def _draft_turns(category: ActivityCategory) -> list[dict]:
    return list(category.draft_turns or [])


def _draft_facts(category: ActivityCategory) -> list[LLMConfirmedFact]:
    """아직 확인 전인 초안 사실을 LLM 컨텍스트 모양으로."""
    return [
        LLMConfirmedFact(
            id=f"draft:{turn['turn_id']}:{i}",
            content=draft["content"],
            source_type="draft",
            fact_type=turn["fact_type_hint"],
        )
        for turn in _draft_turns(category)
        for i, draft in enumerate(turn["drafts"])
    ]


async def _known_facts(db: AsyncSession, category: ActivityCategory) -> list[LLMConfirmedFact]:
    """확정 사실 + 초안. 진행 판단과 기간 추론의 입력이다."""
    confirmed = await _load_confirmed_facts(db, category)
    return [
        LLMConfirmedFact(id=str(f.id), content=f.content, source_type=f.source_type, fact_type=f.fact_type)
        for f in confirmed
    ] + _draft_facts(category)


def _answered_fact_types(confirmed: list[ConfirmedFact], category: ActivityCategory) -> set[str]:
    """이미 답한 고정 질문의 fact_type.

    초안은 **사실이 아니라 턴 단위로** 센다 — "잘 모르겠어요"처럼 사실이 하나도 안 나온
    답도 그 질문에 답한 것이다. 사실 단위로 세면 같은 고정 질문이 무한 반복된다(예전엔
    답변마다 "+ 항목 추가"로 빠져나갈 수 있었지만 이제 확인은 카테고리 끝에서만 한다).
    """
    return {f.fact_type for f in confirmed} | {turn["fact_type_hint"] for turn in _draft_turns(category)}


# 이 fact_type이 확정되면 활동 기간을 유추해볼 만하다고 본다 — 카테고리 유형별
# 고정 질문 목록에서 "얼마나 자주, 어느 정도 기간 동안" / "어떤 상황에서"에 해당하는
# 슬롯들이다(interview_question_bank.py). 카테고리가 끝날 때까지 기다리지 않고 여기서
# 시도하는 이유는, 기간을 알아야 후속 질문 예산(orchestrator.followup_budget)을 그
# 카테고리에 맞게 늘려줄 수 있고 커버리지도 인터뷰 도중에 의미를 갖기 때문이다.
_PERIOD_HINT_FACT_TYPES = frozenset({"frequency", "context"})


def _period_inference_needed(category: ActivityCategory, facts: list[ConfirmedFact]) -> bool:
    """LLM을 부르기 전의 싼 게이트. 요청 경로에서 먼저 걸러, 필요 없는 턴에는
    백그라운드 작업 자체를 예약하지 않는다."""
    if category.period_start is not None or category.period_source == "user_set":
        return False
    if not _PERIOD_HINT_FACT_TYPES & {f.fact_type for f in facts}:
        return False
    # 사실에 기간 단서가 하나도 없으면 아예 묻지 않는다 — 로컬 모델은 이 경우
    # "모르겠다" 대신 공백 기간 전체를 되뱉는다(coverage.has_period_clue 주석 참고).
    # LLM 호출 한 번도 아낀다.
    return has_period_clue(f.content for f in facts)


async def _maybe_infer_category_period(
    db: AsyncSession,
    session_id: uuid.UUID,
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
    if not _period_inference_needed(category, facts):
        return

    gap_period = (
        await db.execute(select(GapPeriod).where(GapPeriod.session_id == session_id))
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


async def infer_category_period_in_background(
    session_factory: async_sessionmaker,
    llm: LLMProvider,
    session_id: uuid.UUID,
    category_id: uuid.UUID,
) -> None:
    """interview_answer가 응답을 보낸 뒤에 도는 기간 추론 — 예외를 던지지 않는다.

    카테고리 단위 확인(2026-09-11) 이후로는 확정 사실 + 아직 확인 전인 초안을 함께
    본다 — 기간은 인용되지 않는 메타데이터이고, 카테고리 도중에 알아야 후속 질문
    예산(orchestrator.followup_budget)에 반영된다.

    예전에는 confirm 요청 안에서 judge_drilldown보다 먼저 순차로
    불렀다. Spark에서 LLM 호출 하나가 수 초씩이라, 사용자는 결과를 화면에 쓰지도
    않는 메타데이터 때문에 그만큼 더 기다렸다. 사용자가 다음 답을 읽고 쓰는
    동안은 Ollama가 비어 있으니 그때 돌린다(프로필 속성 추출과 같은 이유).

    대가: 방금 끝난 턴의 followup_budget 계산에는 새 기간이 반영되지 않고, 다음
    confirm부터 반영된다. 사실을 새로 읽어 게이트를 다시 확인하므로, 그 사이
    사용자가 직접 기간을 지정했다면(user_set) 덮어쓰지 않는다.
    """
    try:
        async with session_factory() as db:
            category = await db.get(ActivityCategory, category_id)
            if category is None:
                return
            facts = await _known_facts(db, category)
            await _maybe_infer_category_period(db, session_id, category, facts, llm)
            await db.commit()
    except Exception:
        logger.warning("interview: background period inference failed for %s", category_id, exc_info=True)


def get_period_inferrer(
    session_factory: async_sessionmaker = Depends(get_background_session_factory),
    llm: LLMProvider = Depends(get_llm_provider),
):
    """FastAPI DI 훅 — 테스트는 get_background_session_factory를 오버라이드해
    같은 테스트 DB와 FakeLLMProvider로 이 작업을 그대로 돌린다."""
    return functools.partial(infer_category_period_in_background, session_factory, llm)


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
    # 질문이 아는 걸 다시 묻지 않게 한다 — 사실 추출·문서 생성에는 넣지 않는다
    # (InterviewContext.profile_summary 주석 참고).
    profile_summary = await profile_summary_lines(db, session.user_id)

    context = InterviewContext(
        session_id=str(session.id),
        category_label=category.label,
        gap_start=gap_period.start_date,
        gap_end=gap_period.end_date,
        # 확정 사실 + 이 카테고리의 확인 전 초안(카테고리 단위 확인). 초안은 LLM이 무엇을
        # 이미 들었는지 아는 데만 쓰인다 — 문서 생성은 여전히 confirmed_facts만 받는다.
        confirmed_facts_so_far=[
            LLMConfirmedFact(id=str(f.id), content=f.content, source_type=f.source_type, fact_type=f.fact_type)
            for f in confirmed_so_far
        ]
        + _draft_facts(category),
        record_excerpts=[
            LLMRecordExcerpt(chunk_id=str(e.chunk_id), text=e.text, published_at=e.published_at)
            for e in excerpts
        ],
        asked_questions=[f.source_question_text for f in confirmed_so_far if f.source_question_text]
        + [turn["question_text"] for turn in _draft_turns(category)],
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


def _build_pending_turn(
    context: InterviewContext,
    category: ActivityCategory,
    question_text: str,
    question_source: str,
    fact_type_hint: str,
    is_structural: bool = False,
) -> dict:
    """`is_structural=True` is for the "여러 활동 있나요?" check only — it's
    routing info, not a content question, so it shouldn't eat into either
    question budget.

    LLM을 부르지 않는다(2026-09-12 입력창 자동 채우기 제거 이후) — 질문 문구는 이미
    정해져 들어오고, 여기서 하는 일은 질문 예산 집계와 대기 턴 저장뿐이다."""
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
        "kind": "question",
        "category_id": str(category.id),
        "question_text": question_text,
        "question_source": question_source,
        "fact_type_hint": fact_type_hint,
        "context_excerpt_ids": [e.chunk_id for e in context.record_excerpts],
        "candidate_facts": None,
    }


def _ask_read(category: ActivityCategory, pending: dict) -> InterviewAskRead:
    return InterviewAskRead(
        mode="question",
        category_id=category.id,
        question_text=pending["question_text"],
        question_source=pending["question_source"],
    )


def _candidate_reads(candidate_payload: list[dict]) -> list[FactCandidateRead]:
    return [
        FactCandidateRead(index=i, content=c["content"], fact_type=c["fact_type"], based_on=BasedOnRead(**c["based_on"]))
        for i, c in enumerate(candidate_payload)
    ]


def _review_pending(category: ActivityCategory) -> dict:
    return {"kind": "category_review", "category_id": str(category.id)}


def _review_read(category: ActivityCategory) -> CategoryReviewRead:
    return CategoryReviewRead(
        category_id=category.id,
        category_label=category.label,
        groups=[
            ReviewGroupRead(
                turn_id=turn["turn_id"],
                question_text=turn["question_text"],
                answer_text=turn.get("answer_text") or "",
                fact_type=turn["fact_type_hint"],
                drafts=[
                    FactCandidateRead(
                        index=i,
                        content=draft["content"],
                        fact_type=turn["fact_type_hint"],
                        based_on=BasedOnRead(**draft["based_on"]),
                    )
                    for i, draft in enumerate(turn["drafts"])
                ],
            )
            for turn in _draft_turns(category)
        ],
    )


def _append_turn(
    category: ActivityCategory, pending: dict, answer_text: str, drafts: list[dict], answer_log_id: str | None
) -> dict:
    turn = {
        "turn_id": uuid.uuid4().hex,
        "answer_log_id": answer_log_id,
        "question_text": pending["question_text"],
        "question_source": pending["question_source"],
        # fact_type은 LLM의 선택이 아니라 질문의 hint로 고정한다(interview_answer 주석 참고).
        "fact_type_hint": pending["fact_type_hint"],
        "answer_text": answer_text,
        "drafts": drafts,
    }
    # JSON 컬럼은 제자리 변경(append)을 추적하지 않는다 — 새 리스트로 재할당해야 저장된다.
    category.draft_turns = [*_draft_turns(category), turn]
    return turn


async def _absorb_legacy_pending(db: AsyncSession, session: SessionModel) -> None:
    """배포 시점에 옛 방식(답변마다 확인)으로 후보 사실이 대기 중이던 세션을 이어 준다.

    그 후보는 이미 그 턴의 컨텍스트로 검증된 값이라 그대로 초안 턴으로 옮기면 된다.
    소분류 질문("여러 활동 있나요?")의 후보는 지금도 바로 확인하는 경로라 건드리지 않는다.
    """
    pending = session.pending_turn
    if (
        not pending
        or pending.get("kind")
        or pending.get("candidate_facts") is None
        or pending.get("fact_type_hint") == "activity_breakdown"
    ):
        return
    category = await db.get(ActivityCategory, uuid.UUID(pending["category_id"]))
    answer_log_id = pending.get("answer_log_id")
    answer_text = ""
    if answer_log_id:
        answer_log = await db.get(InterviewAnswer, uuid.UUID(answer_log_id))
        answer_text = answer_log.answer_text if answer_log is not None else ""
    if category is not None:
        drafts = [{"content": c["content"], "based_on": c["based_on"]} for c in pending["candidate_facts"]]
        _append_turn(category, pending, answer_text, drafts, answer_log_id)
    session.pending_turn = None
    await db.flush()


def _derive_source_type(draft: dict | None, was_edited: bool) -> tuple[str, uuid.UUID | None]:
    """정직성 가드레일: source_type은 클라이언트가 아니라 서버가 저장해 둔 초안의
    based_on과 was_edited로만 정한다(임의로 record_cited를 주장하지 못하게).
    초안이 없는 항목(사용자가 직접 추가)은 근거 없는 사용자 작성이라 user_edited다."""
    if was_edited or draft is None:
        return "user_edited", None
    based_on = draft.get("based_on") or {}
    if based_on.get("type") == "record" and based_on.get("excerpts"):
        return "record_cited", uuid.UUID(based_on["excerpts"][0]["chunk_id"])
    return "user_confirmed", None


async def _decide_next(
    db: AsyncSession,
    session: SessionModel,
    category: ActivityCategory,
    llm: LLMProvider,
    chunk_search,
    last_turn: dict | None,
) -> tuple[str, dict | None]:
    """다음 질문(`("question", pending_turn)`) 또는 카테고리 끝 확인(`("review", None)`).

    예전 interview_confirm의 라우팅을 초안 기준으로 옮긴 것이다. `last_turn`은 방금
    답한 턴(/answer)이고, None이면 막 들어온 카테고리이거나 대기 질문이 없는 상태에서
    부른 /ask라 판단(드릴다운·충분성) 없이 다음 질문만 정한다.

    - 고정 질문이 남음: 예산이 남았으면 방금 답에 드릴다운이 필요한지 판단 → 아니면
      다음 고정 질문. 고정 질문은 예산과 무관하게 전부 묻는다(2026-09-06).
    - 고정 질문 끝 + 예산 남음: 충분성 판단 → 부족하면 AI 후속 질문, 충분하면 확인.
    - 예산 소진: 확인.

    followup_question 실패(LLMUnavailableError)는 호출자가 처리한다 — /answer는 확인
    단계로 넘기고, /ask는 503을 낸다.
    """
    confirmed = await _load_confirmed_facts(db, category)
    remaining = next_base_question(category.category_type, _answered_fact_types(confirmed, category))
    # AI 추가 질문(드릴다운/후속) 전용 예산 — 상한은 활동 기간에 따라 달라진다
    # (orchestrator.followup_budget).
    budget_left = category.followup_questions_asked < orchestrator.followup_budget(category)

    if remaining is not None:
        if budget_left and last_turn is not None:
            should_ask, drilldown_text = False, None
            context = None
            try:
                context, _ = await _build_context(db, session, category, chunk_search, query_text=last_turn["question_text"])
                decision = await llm.judge_drilldown(context)
                should_ask, drilldown_text = decision.should_ask, decision.question_text
            except LLMUnavailableError:
                # 판단 LLM이 막히면 규칙 기반 백업: 방금 답에서 뽑은 내용이 아주 짧으면
                # 정형화된 구체화 질문을 하나 끼워 넣는다(2026-09-06).
                if _is_vague_answer([d["content"] for d in last_turn["drafts"]]):
                    should_ask, drilldown_text = True, _GENERIC_PROBE_QUESTION
            if should_ask and drilldown_text:
                if context is None:
                    context, _ = await _build_context(db, session, category, chunk_search, query_text=drilldown_text)
                return "question", _build_pending_turn(
                    context, category, drilldown_text, "followup", "followup"
                )
        context, _ = await _build_context(db, session, category, chunk_search, query_text=remaining.text)
        return "question", _build_pending_turn(context, category, remaining.text, "base", remaining.fact_type)

    if not budget_left:
        # 예산 소진 — LLM이 계속 부족하다고 판단하더라도 더 묻지 않는다.
        return "review", None

    if last_turn is not None:
        try:
            context, _ = await _build_context(db, session, category, chunk_search, query_text=last_turn["question_text"])
            sufficient = (await llm.judge_sufficiency(context)).sufficient
        except LLMUnavailableError:
            # 판단이 안 되면 붙잡아 두기보다 확인으로 넘긴다 — 무한정 묻는 것보다 낫다.
            sufficient = True
        if sufficient:
            return "review", None

    # 후속 질문은 질문 문구가 아직 없으므로 카테고리 이름을 검색어로 쓴다.
    context, _ = await _build_context(db, session, category, chunk_search, query_text=category.label)
    question_text = await llm.followup_question(context)
    return "question", _build_pending_turn(context, category, question_text, "followup", "followup")


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

    # 배포 전 방식으로 후보가 대기 중이던 세션은 초안으로 옮기고 이어 간다.
    await _absorb_legacy_pending(db, session)

    pending = session.pending_turn
    if pending is not None and pending.get("category_id") == str(category.id):
        # 카테고리 끝 확인을 기다리는 중 — LLM 호출 없이 확인 내용을 다시 준다
        # (새로고침 복원 경로).
        if pending.get("kind") == "category_review":
            return InterviewAskRead(mode="review", category_id=category.id, review=_review_read(category))
        # Idempotent: if a question is already pending and unanswered, return it
        # as-is instead of calling the LLM again (covers refresh/duplicate calls).
        if pending.get("candidate_facts") is None:
            return _ask_read(category, pending)
        # 후보는 이미 뽑혔지만(예: "여러 활동 있나요?" 답변) 아직 /interview/confirm으로
        # 확정되지 않은 상태 — 여기서 처리 안 하면 아래 activity_split_checked 분기로
        # 떨어져 pending_turn을 새 분리질문으로 덮어쓰고 후보를 버린다(2026-09-12 버그:
        # 같은 문구가 새로고침마다 반복되고 상태가 진행되지 않음). question_text/source도
        # 함께 돌려줘야 프론트가 질문 말풍선을 그려 그 아래 후보 카드가 보인다 — 프론트의
        # 렌더 조건이 questionText 존재를 전제로 하기 때문(InterviewChatThread.tsx).
        return InterviewAskRead(
            mode="candidates",
            category_id=category.id,
            question_text=pending["question_text"],
            question_source=pending["question_source"],
            candidates=_candidate_reads(pending["candidate_facts"]),
        )

    # 질문을 먼저 정하고, 그 질문 문구로 기록물을 검색한다. 순서가 반대였을 때는
    # (2026-09-09 이전) 검색어가 없어 카테고리에 붙은 청크를 작성순으로 자르는 게
    # 전부였고, record_chunks.embedding은 한 번도 조회되지 않았다.
    if not category.activity_split_checked:
        context, _ = await _build_context(db, session, category, chunk_search, query_text=None)
        session.pending_turn = _build_pending_turn(
            context, category, ACTIVITY_BREAKDOWN_QUESTION, "split_check", "activity_breakdown", is_structural=True
        )
        await db.commit()
        return _ask_read(category, session.pending_turn)

    try:
        decision, next_pending = await _decide_next(db, session, category, llm, chunk_search, last_turn=None)
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc

    if decision == "review":
        session.pending_turn = _review_pending(category)
        await db.commit()
        return InterviewAskRead(mode="review", category_id=category.id, review=_review_read(category))

    session.pending_turn = next_pending
    await db.commit()
    return _ask_read(category, next_pending)


@router.post("/{session_id}/interview/answer", response_model=InterviewAnswerRead)
async def interview_answer(
    payload: InterviewAnswerRequest,
    background_tasks: BackgroundTasks,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    chunk_search=Depends(get_chunk_search),
    extractor=Depends(get_profile_extractor),
    period_inferrer=Depends(get_period_inferrer),
) -> InterviewAnswerRead:
    try:
        orchestrator.require_interviewing(session.status)
    except orchestrator.StateMachineViolation as exc:
        raise _violation_to_409(exc) from exc

    pending = session.pending_turn
    if pending is not None and pending.get("kind") == "category_review":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="category_review_pending")
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
            mode="candidates",
            candidates=_candidate_reads(candidate_payload)
        )

    # 공백뿐인 답은 받지 않는다. 예전엔 빈 후보를 확인하고 같은 질문을 다시 받는 식이었지만,
    # 이제는 답 하나가 곧 "그 질문에 답했다"로 세지므로(_answered_fact_types) 빈 답을
    # 받으면 질문이 조용히 넘어가 버린다. LLM을 부르기 전에 막는다.
    if not payload.text.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empty_answer")

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

    # 카테고리 단위 확인(2026-09-11): 뽑은 사실은 바로 확인받지 않고 이 카테고리의
    # 초안으로 쌓는다. confirmed_facts에는 카테고리 끝 확인(/interview/review)에서만 들어간다.
    turn = _append_turn(
        category,
        pending,
        payload.text,
        [{"content": c["content"], "based_on": c["based_on"]} for c in candidate_payload],
        str(answer_log.id),
    )
    session.pending_turn = None
    user_id, answer_id, session_id, category_id = session.user_id, answer_log.id, session.id, category.id
    # 다음 질문을 정하다 LLM이 실패해도 방금 답이 사라지지 않게 먼저 저장한다 — 그때는
    # pending_turn이 비어 있으니 다음 /ask가 초안 기준으로 이어 간다.
    await db.commit()

    # 기간 추론은 응답 뒤로 미룬다(infer_category_period_in_background 참고). 게이트만
    # 여기서 먼저 확인해, 필요 없는 턴엔 작업을 예약하지 않는다.
    if _period_inference_needed(category, await _known_facts(db, category)):
        background_tasks.add_task(period_inferrer, session_id, category_id)
    # 답변 원문에서 사람 단위 속성(나이·거주지·학력·희망직무 …)을 뽑아 프로필로
    # 남긴다. 응답을 보낸 뒤 백그라운드에서 돈다. 구조 질문(activity_breakdown)은 위에서
    # 이미 반환했으므로 여기 오지 않는다.
    background_tasks.add_task(extractor, user_id, "interview_answer", payload.text, answer_id)

    try:
        decision, next_pending = await _decide_next(db, session, category, llm, chunk_search, last_turn=turn)
    except LLMUnavailableError:
        # 후속 질문을 못 만들면 붙잡아 두지 않고 확인으로 넘긴다.
        decision, next_pending = "review", None

    if decision == "review":
        session.pending_turn = _review_pending(category)
        await db.commit()
        return InterviewAnswerRead(mode="review", review=_review_read(category))

    session.pending_turn = next_pending
    await db.commit()
    return InterviewAnswerRead(mode="question", question=_ask_read(category, next_pending))


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

    # 카테고리 단위 확인(2026-09-11) 이후 일반 답변의 사실은 여기서 확정하지 않는다 —
    # 초안으로 쌓였다가 카테고리 끝 확인(POST /interview/review)에서 한 번에 확정된다.
    # 이 경로에 남은 건 위의 "여러 활동 있나요?" 분기뿐이다.
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="use_category_review")


@router.post("/{session_id}/interview/review", response_model=InterviewConfirmRead)
async def interview_review(
    payload: InterviewReviewRequest,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
) -> InterviewConfirmRead:
    """카테고리 끝 확인 — 이 카테고리에서 답한 턴들의 초안을 사용자가 고치고·빼고·더한
    그대로 confirmed_facts로 옮긴다. 일반 답변의 사실이 confirmed_facts에 들어가는 유일한
    지점이다(소분류 질문은 사실이 아니라 라우팅이라 /interview/confirm이 따로 처리한다).
    """
    try:
        orchestrator.require_interviewing(session.status)
    except orchestrator.StateMachineViolation as exc:
        raise _violation_to_409(exc) from exc

    pending = session.pending_turn
    if pending is None or pending.get("kind") != "category_review":
        # 이중 제출도 여기서 막힌다 — 첫 제출이 pending_turn을 비운다.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_pending_review")

    category = await db.get(ActivityCategory, uuid.UUID(pending["category_id"]))
    turns = _draft_turns(category)
    turn_positions = {turn["turn_id"]: pos for pos, turn in enumerate(turns)}
    for confirmation in payload.confirmations:
        if confirmation.turn_id not in turn_positions or confirmation.index < 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="invalid_review_item")

    # 질문 순서 → 항목 순서로 넣는다. 대화 화면은 확정 사실을 원 질문별로 묶어 그리므로
    # 순서가 섞이면 같은 질문 말풍선이 여러 번 나온다.
    ordered = sorted(payload.confirmations, key=lambda c: (turn_positions[c.turn_id], c.index))
    inserted_by_turn: dict[str, list[ConfirmedFact]] = {turn["turn_id"]: [] for turn in turns}
    for confirmation in ordered:
        if not confirmation.include or not confirmation.final_text.strip():
            # 빈 문자열은 조용히 건너뛴다 — 새로 추가한 항목을 다 채우지 않고 제출한 경우
            # 빈 확정 사실이 만들어지는 걸 막는다.
            continue
        turn = turns[turn_positions[confirmation.turn_id]]
        drafts = turn["drafts"]
        draft = drafts[confirmation.index] if confirmation.index < len(drafts) else None
        source_type, source_chunk_id = _derive_source_type(draft, confirmation.was_edited)
        fact = ConfirmedFact(
            category_id=category.id,
            # 턴에 저장된 질문의 hint — 클라이언트 값이 아니다.
            fact_type=turn["fact_type_hint"],
            content=confirmation.final_text,
            source_type=source_type,
            source_record_chunk_id=source_chunk_id,
            ai_draft_text=(draft or {}).get("content"),
            source_question_text=turn["question_text"],
        )
        db.add(fact)
        inserted_by_turn[turn["turn_id"]].append(fact)

    # 계정 단위 문답 기록에 "이 답변에서 실제로 확정된 것"을 스냅샷으로 남긴다 — 전부 뺀
    # 답은 빈 목록이다. 세션이 지워져도(confirmed_facts는 CASCADE로 사라진다) 이 요약은 남는다.
    # 한 번에 읽는다 — 턴마다 db.get을 하면 원격 DB 왕복이 턴 수만큼 늘어난다.
    log_ids = [uuid.UUID(turn["answer_log_id"]) for turn in turns if turn.get("answer_log_id")]
    answer_logs = {
        str(log.id): log
        for log in (
            await db.execute(select(InterviewAnswer).where(InterviewAnswer.id.in_(log_ids)))
        ).scalars().all()
    } if log_ids else {}
    for turn in turns:
        answer_log = answer_logs.get(turn.get("answer_log_id") or "")
        if answer_log is not None:
            answer_log.confirmed_facts = [
                {"content": f.content, "fact_type": f.fact_type, "source_type": f.source_type}
                for f in inserted_by_turn[turn["turn_id"]]
            ]

    category.draft_turns = None
    category.status = "DONE"
    session.pending_turn = None
    categories = (
        await db.execute(select(ActivityCategory).where(ActivityCategory.session_id == session.id))
    ).scalars().all()
    next_status, next_cat = orchestrator.resolve_after_confirm(list(categories), category, advance=True)
    session.status = next_status
    session.current_category_id = next_cat.id if next_cat else None
    await db.commit()

    inserted = [fact for turn in turns for fact in inserted_by_turn[turn["turn_id"]]]
    for fact in inserted:
        await db.refresh(fact)
    return InterviewConfirmRead(
        status=session.status,
        current_category_id=session.current_category_id,
        category_done=True,
        confirmed_facts=[ConfirmedFactRead.model_validate(f) for f in inserted],
    )
