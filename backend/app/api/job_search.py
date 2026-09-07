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
    JobSearchSeedRead,
    JobSearchStateRead,
)
from app.services.job_pipeline.worknet_client import WorknetJobPostingClient, get_job_search_client
from app.services.llm.base import AllProvidersFailedError
from app.services.llm.base import ConfirmedFact as LLMConfirmedFact
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
        salary_min=prefs.desired_salary_min,
        salary_max=prefs.desired_salary_max,
        location=prefs.desired_location,
        education_level=prefs.education_level,
        career_years=prefs.career_years,
        work_style_tags=list(prefs.work_style_tags),
    )


def _preferences_read(prefs: JobSearchPreferences) -> JobPreferencesRead:
    return JobPreferencesRead(
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
        last_searched_at=prefs.last_searched_at if prefs else None,
        results=[JobPostingRead(**r) for r in (prefs.last_results if prefs else [])],
    )


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
    _require_status("job_preferences_extract", session, "JOB_PREFERENCES_INPUT")

    # 카테고리/기간 추출과 동일한 원칙: DB에 아무것도 안 씀 — 사용자가 확인한
    # 뒤 POST /preferences를 직접 호출해야 실제로 저장된다.
    try:
        suggestion = await llm.extract_job_preferences(payload.text)
    except AllProvidersFailedError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc

    return JobPreferencesSuggestionRead(
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


@router.post("/{session_id}/job-search/seed-from-gap", response_model=JobSearchSeedRead)
async def seed_from_gap(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
) -> JobSearchSeedRead:
    _require_job_search(session)
    if session.linked_gap_session_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_linked_gap_session")

    gap_session = await db.get(SessionModel, session.linked_gap_session_id)
    if gap_session is None or gap_session.user_id != session.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="linked_session_not_found")

    facts = (
        await db.execute(
            select(ConfirmedFact)
            .join(ActivityCategory, ConfirmedFact.category_id == ActivityCategory.id)
            .where(ActivityCategory.session_id == gap_session.id)
        )
    ).scalars().all()

    try:
        result = await llm.infer_job_preferences_from_facts(
            [
                LLMConfirmedFact(id=str(f.id), content=f.content, source_type=f.source_type, fact_type=f.fact_type)
                for f in facts
            ]
        )
    except AllProvidersFailedError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc

    return JobSearchSeedRead(
        work_style_tags=list(result.work_style_tags),
        keyword_hints=list(result.keyword_hints),
        notes=result.notes,
    )
