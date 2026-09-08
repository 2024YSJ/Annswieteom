from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_owned_session
from app.db.session import get_db
from app.models.activity_category import ActivityCategory
from app.models.confirmed_fact import ConfirmedFact
from app.models.job_search_preferences import JobSearchPreferences
from app.models.session import Session as SessionModel
from app.schemas.job_search import (
    JobPostingRead,
    JobPreferencesConfirmRead,
    JobPreferencesConfirmRequest,
    JobPreferencesExtractRequest,
    JobPreferencesRead,
    JobPreferencesSuggestionRead,
    JobSearchQuestionRead,
    JobSearchSeedRead,
    JobSearchStateRead,
    JobSearchTurnConfirmRequest,
)
from app.services.job_pipeline.worknet_client import WorknetJobPostingClient, get_job_search_client
from app.services.job_search_question_bank import next_question
from app.services.llm.base import AllProvidersFailedError
from app.services.llm.base import ConfirmedFact as LLMConfirmedFact
from app.services.llm.base import JobPreferenceInferenceResult
from app.services.llm.base import JobPreferences as LLMJobPreferences
from app.services.llm.base import LLMProvider
from app.services.llm.fallback import get_llm_provider

router = APIRouter(prefix="/sessions", tags=["job_search"])

# 워크넷 조회 건수 상한 — 15건 x judge_job_fit 병렬 4개면 로컬 Ollama에서도
# 합리적인 시간 안에 끝난다(순차 15콜은 너무 느림, 2절 계획 참고).
_MAX_SEARCH_RESULTS = 15
_JUDGE_CONCURRENCY = 4


def _require_job_search(session: SessionModel) -> None:
    if session.kind != "job_search":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_a_job_search_session")


def _require_status(action: str, session: SessionModel, *allowed: str) -> None:
    # 일자리 찾기는 카테고리 기반 gap-fill 상태머신(interview_orchestrator)과
    # 도메인이 완전히 다르므로 별도 헬퍼로 둔다 — sessions.status 컬럼만
    # 공유할 뿐, 전이 규칙까지 같은 모듈에 억지로 묶을 이유가 없다.
    if session.status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{action}' requires session status in {allowed}, got '{session.status}'",
        )


async def _get_preferences(session_id, db: AsyncSession) -> JobSearchPreferences | None:
    return (
        await db.execute(select(JobSearchPreferences).where(JobSearchPreferences.session_id == session_id))
    ).scalar_one_or_none()


def _to_llm_preferences(prefs: JobSearchPreferences | None) -> LLMJobPreferences:
    if prefs is None:
        return LLMJobPreferences()
    return LLMJobPreferences(
        desired_keyword=prefs.desired_keyword,
        salary_min=prefs.desired_salary_min,
        salary_max=prefs.desired_salary_max,
        location=prefs.desired_location,
        education_level=prefs.education_level,
        career_years=prefs.career_years,
        work_style_tags=list(prefs.work_style_tags),
    )


def _preferences_read(prefs: JobSearchPreferences) -> JobPreferencesRead:
    return JobPreferencesRead(
        desired_keyword=prefs.desired_keyword,
        salary_min=prefs.desired_salary_min,
        salary_max=prefs.desired_salary_max,
        location=prefs.desired_location,
        education_level=prefs.education_level,
        career_years=prefs.career_years,
        work_style_tags=list(prefs.work_style_tags),
    )


def _state_read(session: SessionModel, prefs: JobSearchPreferences | None) -> JobSearchStateRead:
    return JobSearchStateRead(
        status=session.status,
        linked_gap_session_id=str(session.linked_gap_session_id) if session.linked_gap_session_id else None,
        preferences=_preferences_read(prefs) if prefs else None,
        completed_fields=list(prefs.completed_fields) if prefs else [],
        last_searched_at=prefs.last_searched_at if prefs else None,
        results=[JobPostingRead(**r) for r in (prefs.last_results if prefs else [])],
    )


def _apply_turn_field(prefs: JobSearchPreferences, field: str, payload: JobSearchTurnConfirmRequest) -> None:
    """턴에서 방금 확정된 값만 해당 컬럼(들)에 반영한다 — 클라이언트가 payload에
    다른 필드를 같이 실어 보내도 현재 턴의 field와 무관한 값은 무시된다."""
    if field == "keyword":
        prefs.desired_keyword = payload.desired_keyword
    elif field == "location":
        prefs.desired_location = payload.location
    elif field == "salary":
        prefs.desired_salary_min = payload.salary_min
        prefs.desired_salary_max = payload.salary_max
    elif field == "education":
        prefs.education_level = payload.education_level
    elif field == "career":
        prefs.career_years = payload.career_years
    elif field == "work_style":
        prefs.work_style_tags = list(payload.work_style_tags or [])


async def _seed_from_gap(session: SessionModel, db: AsyncSession, llm: LLMProvider) -> JobPreferenceInferenceResult | None:
    """연동된 공백기 세션이 있으면 그 confirmed_facts에서 힌트를 추론한다 —
    없거나 뭔가 실패하면 None(호출부가 조용히 시드 없이 진행하게).
    seed_from_gap 라우트와 ask 엔드포인트(keyword/work_style 질문 턴)가 공유."""
    if session.linked_gap_session_id is None:
        return None
    gap_session = await db.get(SessionModel, session.linked_gap_session_id)
    if gap_session is None or gap_session.user_id != session.user_id:
        return None

    facts = (
        await db.execute(
            select(ConfirmedFact)
            .join(ActivityCategory, ConfirmedFact.category_id == ActivityCategory.id)
            .where(ActivityCategory.session_id == gap_session.id)
        )
    ).scalars().all()

    try:
        return await llm.infer_job_preferences_from_facts(
            [
                LLMConfirmedFact(id=str(f.id), content=f.content, source_type=f.source_type, fact_type=f.fact_type)
                for f in facts
            ]
        )
    except AllProvidersFailedError:
        return None


@router.get("/{session_id}/job-search", response_model=JobSearchStateRead)
async def get_job_search_state(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
) -> JobSearchStateRead:
    _require_job_search(session)
    prefs = await _get_preferences(session.id, db)
    return _state_read(session, prefs)


@router.post("/{session_id}/job-search/preferences/extract", response_model=JobPreferencesSuggestionRead)
async def extract_job_preferences(
    payload: JobPreferencesExtractRequest,
    session: SessionModel = Depends(get_owned_session),
    llm: LLMProvider = Depends(get_llm_provider),
) -> JobPreferencesSuggestionRead:
    _require_job_search(session)
    # confirm_job_preferences와 동일한 허용 목록 — 확정 후에도(검색/결과 확인
    # 중에도) 자유 텍스트로 조건을 다시 말하면 이 엔드포인트가 해석해준다.
    _require_status(
        "job_preferences_extract", session, "JOB_PREFERENCES_INPUT", "JOB_SEARCHING", "JOB_RESULTS_REVIEW"
    )

    # 카테고리/기간 추출과 동일한 원칙: DB에 아무것도 안 씀 — 사용자가 확인한
    # 뒤 POST /preferences를 직접 호출해야 실제로 저장된다.
    try:
        suggestion = await llm.extract_job_preferences(payload.text)
    except AllProvidersFailedError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc

    return JobPreferencesSuggestionRead(
        desired_keyword=suggestion.desired_keyword,
        salary_min=suggestion.salary_min,
        salary_max=suggestion.salary_max,
        location=suggestion.location,
        education_level=suggestion.education_level,
        career_years=suggestion.career_years,
        work_style_tags=list(suggestion.work_style_tags),
    )


@router.post("/{session_id}/job-search/preferences", response_model=JobPreferencesConfirmRead)
async def confirm_job_preferences(
    payload: JobPreferencesConfirmRequest,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
) -> JobPreferencesConfirmRead:
    _require_job_search(session)
    # 최초 확정(JOB_PREFERENCES_INPUT)뿐 아니라, 검색 이후에도 조건을 고쳐서
    # 다시 확정할 수 있게 허용한다 — 검색 자체를 다시 트리거하려면 별도로
    # POST /job-search/search("다시 찾기")를 호출해야 한다.
    _require_status(
        "job_preferences_confirm", session, "JOB_PREFERENCES_INPUT", "JOB_SEARCHING", "JOB_RESULTS_REVIEW"
    )

    prefs = await _get_preferences(session.id, db)
    if prefs is None:
        prefs = JobSearchPreferences(session_id=session.id)
        db.add(prefs)

    prefs.desired_keyword = payload.desired_keyword
    prefs.desired_salary_min = payload.salary_min
    prefs.desired_salary_max = payload.salary_max
    prefs.desired_location = payload.location
    prefs.education_level = payload.education_level
    prefs.career_years = payload.career_years
    prefs.work_style_tags = list(payload.work_style_tags)

    if session.status == "JOB_PREFERENCES_INPUT":
        session.status = "JOB_SEARCHING"

    await db.commit()
    await db.refresh(prefs)

    return JobPreferencesConfirmRead(status=session.status, preferences=_preferences_read(prefs))


@router.post("/{session_id}/job-search/search", response_model=JobSearchStateRead)
async def search_jobs(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    job_client: WorknetJobPostingClient = Depends(get_job_search_client),
) -> JobSearchStateRead:
    _require_job_search(session)
    _require_status("job_search", session, "JOB_SEARCHING", "JOB_RESULTS_REVIEW")

    prefs = await _get_preferences(session.id, db)
    if prefs is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="preferences_not_confirmed")

    llm_prefs = _to_llm_preferences(prefs)
    postings = await job_client.search(llm_prefs, limit=_MAX_SEARCH_RESULTS)

    semaphore = asyncio.Semaphore(_JUDGE_CONCURRENCY)

    async def _judge(posting):
        async with semaphore:
            try:
                return await llm.judge_job_fit(llm_prefs, posting)
            except AllProvidersFailedError:
                # 판단이 아예 불가능해도 검색 자체가 실패한 건 아니므로 목록에서
                # 빼지 않고 "판단 불가"로 표시한다.
                return None

    judgments = await asyncio.gather(*[_judge(p) for p in postings])

    results = [
        {
            "source": posting.source,
            "external_id": posting.external_id,
            "title": posting.title,
            "company": posting.company,
            "salary_text": posting.salary_text,
            "location": posting.location,
            "education_requirement": posting.education_requirement,
            "career_requirement": posting.career_requirement,
            "work_type": posting.work_type,
            "url": posting.url,
            "fit": judgment.fit if judgment else False,
            "reason": judgment.reason if judgment else "적합도를 판단하지 못했어요.",
        }
        for posting, judgment in zip(postings, judgments)
    ]
    results.sort(key=lambda r: not r["fit"])  # fit=true 먼저

    prefs.last_results = results
    prefs.last_searched_at = datetime.now(timezone.utc)
    session.status = "JOB_RESULTS_REVIEW"
    await db.commit()
    await db.refresh(prefs)

    return _state_read(session, prefs)


@router.post("/{session_id}/job-search/preferences/ask", response_model=JobSearchQuestionRead)
async def ask_job_search_question(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
) -> JobSearchQuestionRead:
    """최초 1회차 입력 전용 — 공백기 채우기의 interview/ask와 같은 원리로,
    이미 캐싱된 턴이 있으면(새로고침/중복 호출) LLM을 다시 안 부르고 그대로
    재사용한다."""
    _require_job_search(session)
    _require_status("job_search_preferences_ask", session, "JOB_PREFERENCES_INPUT")

    pending = session.pending_turn
    if pending is not None and pending.get("kind") == "job_search_preferences":
        return JobSearchQuestionRead(
            done=False,
            status=session.status,
            field=pending["field"],
            question_text=pending["question_text"],
            draft_answer=pending.get("draft_answer", ""),
        )

    prefs = await _get_preferences(session.id, db)
    completed = list(prefs.completed_fields) if prefs else []
    question = next_question(completed)

    if question is None:
        # 이론상 여기 안 옴 — turn-confirm이 마지막 질문에서 이미 JOB_SEARCHING으로
        # 전이시키므로 이 상태에서 다시 ask가 불릴 일이 없다. 그래도 방어적으로.
        session.status = "JOB_SEARCHING"
        session.pending_turn = None
        await db.commit()
        return JobSearchQuestionRead(done=True, status=session.status)

    # keyword/work_style 질문 턴에서만 연동 시드를 미리 채워준다 —
    # infer_job_preferences_from_facts 호출은 그 자체로 비용이 있으므로
    # 관련 없는 질문(급여/학력 등)에서는 부르지 않는다.
    draft_answer = ""
    if question.field in ("keyword", "work_style") and session.linked_gap_session_id:
        seed = await _seed_from_gap(session, db, llm)
        if seed is not None:
            hints = seed.keyword_hints if question.field == "keyword" else seed.work_style_tags
            draft_answer = ", ".join(hints)

    session.pending_turn = {
        "kind": "job_search_preferences",
        "field": question.field,
        "question_text": question.text,
        "draft_answer": draft_answer,
    }
    await db.commit()

    return JobSearchQuestionRead(
        done=False, status=session.status, field=question.field, question_text=question.text, draft_answer=draft_answer
    )


@router.post("/{session_id}/job-search/preferences/turn-confirm", response_model=JobSearchQuestionRead)
async def confirm_job_search_turn(
    payload: JobSearchTurnConfirmRequest,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
) -> JobSearchQuestionRead:
    """현재 턴(pending_turn에 캐싱된 field)만 반영하고 다음 질문 유무를
    알려준다 — 다음 질문의 실제 문구/시드는 프론트가 이어서 ask를 다시
    불러 받는다(interview_confirm 이후 프론트가 interviewAsk를 다시 부르는
    것과 동일한 분담)."""
    _require_job_search(session)
    _require_status("job_search_preferences_turn_confirm", session, "JOB_PREFERENCES_INPUT")

    pending = session.pending_turn
    if pending is None or pending.get("kind") != "job_search_preferences":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_pending_question")

    field = pending["field"]
    prefs = await _get_preferences(session.id, db)
    if prefs is None:
        prefs = JobSearchPreferences(session_id=session.id)
        db.add(prefs)
        await db.flush()

    _apply_turn_field(prefs, field, payload)
    if field not in prefs.completed_fields:
        prefs.completed_fields = [*prefs.completed_fields, field]
    session.pending_turn = None

    done = next_question(prefs.completed_fields) is None
    if done:
        session.status = "JOB_SEARCHING"

    await db.commit()
    return JobSearchQuestionRead(done=done, status=session.status)


@router.post("/{session_id}/job-search/seed-from-gap", response_model=JobSearchSeedRead)
async def seed_from_gap(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
) -> JobSearchSeedRead:
    _require_job_search(session)
    if session.linked_gap_session_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_linked_gap_session")

    result = await _seed_from_gap(session, db, llm)
    if result is None:
        # linked_gap_session_id가 있는데도 None이 나오는 경우는 소유자 불일치
        # (다른 세션) 또는 모든 provider 실패뿐 — 전자는 404, 후자는 503으로
        # 구분해 알려준다.
        gap_session = await db.get(SessionModel, session.linked_gap_session_id)
        if gap_session is None or gap_session.user_id != session.user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="linked_session_not_found")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable")

    return JobSearchSeedRead(
        work_style_tags=list(result.work_style_tags),
        keyword_hints=list(result.keyword_hints),
        notes=result.notes,
    )
