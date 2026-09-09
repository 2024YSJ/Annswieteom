from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_owned_session
from app.db.session import get_db
from app.models.activity_category import ActivityCategory
from app.models.confirmed_fact import ConfirmedFact
from app.models.session import Session as SessionModel
from app.schemas.job_search import (
    JobInfoCategoryResultRead,
    JobInfoDraftQueryRead,
    JobInfoQueryRead,
    JobInfoQueryRequest,
    JobInfoResultRead,
)
from app.services.job_pipeline.job_info_client import CATEGORY_LABELS, JobInfoClient, WorknetApiError, get_job_info_client
from app.services.llm.base import LLMUnavailableError, JobInfoCandidate, LLMProvider
from app.services.llm.base import ConfirmedFact as LLMConfirmedFact
from app.services.llm import get_llm_provider

router = APIRouter(prefix="/sessions", tags=["job_search"])

_CLARIFICATION_QUESTION = (
    "어떤 종류의 정보를 찾으시나요? 채용행사, 최근 공채 소식, 채용 기업 정보, "
    "직업훈련과정, 취업 지원 프로그램, 강소기업 중에서 궁금하신 걸 말씀해주세요."
)

# 관련 있다고 판단된 항목이 너무 많아도(예: 훈련과정 4개 엔드포인트 합쳐서
# 40건 중 30건이 관련) 카드가 끝없이 늘어지지 않도록 화면에 보여줄 상한.
_MAX_RESULTS_PER_CATEGORY = 8


def _require_job_search(session: SessionModel) -> None:
    if session.kind != "job_search":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_a_job_search_session")


@router.post("/{session_id}/job-search/query", response_model=JobInfoQueryRead)
async def query_job_info(
    payload: JobInfoQueryRequest,
    session: SessionModel = Depends(get_owned_session),
    llm: LLMProvider = Depends(get_llm_provider),
    job_client: JobInfoClient = Depends(get_job_info_client),
) -> JobInfoQueryRead:
    """무상태 대화형 검색 — 매 질문마다 관련 카테고리(들)를 판단하고 그
    자리에서 바로 조회한다. 확정/저장할 게 없어(급여/조건을 모아뒀다가
    나중에 검색하던 이전 버전과 달리) 세션에 아무것도 영속화하지 않는다 —
    대화 이력은 프론트가 로컬 상태로만 누적한다(devlog 16).

    카테고리 안에서 실제로 어떤 항목을 보여줄지는 워크넷 원본 목록을 통째로
    LLM에게 보여주고 고르게 한다(select_relevant_job_info_results) — 사용자
    질문 키워드를 응답 텍스트에 문자열로 부분일치시키던 이전 방식은 "경기
    북부"라고 물었을 때 실제 데이터엔 "의정부"/"파주"처럼 구체적인 지명만
    있는 경우를 전혀 못 잡아서(2026-09-08 실사용 피드백) 폐기했다 —
    devlog 18 참고."""
    _require_job_search(session)

    try:
        category_queries = await llm.classify_job_info_query(payload.query)
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc

    if not category_queries:
        return JobInfoQueryRead(categories=[], clarification_question=_CLARIFICATION_QUESTION)

    async def _search_category(category: str) -> JobInfoCategoryResultRead | None:
        label = CATEGORY_LABELS[category]
        try:
            raw_results = await job_client.search(category)
        except WorknetApiError:
            # 이 카테고리만 실패 처리하고 나머지는 계속 보여준다 — 카테고리
            # 하나가 승인 대기/오류라고 질문 전체가 실패로 보이면 안 된다.
            return None

        if not raw_results:
            return JobInfoCategoryResultRead(category=category, category_label=label, results=[])

        candidates = [
            JobInfoCandidate(index=i, title=r.title, subtitle=r.subtitle, meta_lines=r.meta_lines)
            for i, r in enumerate(raw_results)
        ]
        try:
            relevant_indices = await llm.select_relevant_job_info_results(payload.query, label, candidates)
        except LLMUnavailableError:
            # 원본 목록은 받아왔지만 관련성 판단이 안 되면, 걸러지지 않은
            # 목록을 그대로 보여주느니 이 카테고리를 빼는 쪽이 낫다 — 그게
            # 바로 이번에 고치려는 문제(무관한 결과 노출)이기 때문이다.
            return None

        selected = [raw_results[i] for i in relevant_indices][:_MAX_RESULTS_PER_CATEGORY]
        return JobInfoCategoryResultRead(
            category=category,
            category_label=label,
            results=[JobInfoResultRead(**r.__dict__) for r in selected],
        )

    searched = await asyncio.gather(*[_search_category(cq.category) for cq in category_queries])
    categories = [c for c in searched if c is not None]

    return JobInfoQueryRead(categories=categories, clarification_question=None)


@router.post("/{session_id}/job-search/draft-query-from-gap", response_model=JobInfoDraftQueryRead)
async def draft_query_from_gap(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
) -> JobInfoDraftQueryRead:
    """공백기 채우기 세션에서 "취업 정보 검색으로 이관"한 직후, 그 세션의
    confirmed_facts를 요약해 컴포저에 미리 채워둘 첫 질문 초안을 만든다.
    suggestion만 반환하고 아무것도 저장하지 않는다 — 사용자가 그대로 보내거나
    고쳐 쓰거나 지우고 새로 써야 실제로 대화가 시작된다(다른 모든 AI 초안과
    동일한 "AI가 쓰고 사용자가 확인" 원칙, devlog 17)."""
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
        draft_query = await llm.draft_job_info_query_from_facts(
            [
                LLMConfirmedFact(id=str(f.id), content=f.content, source_type=f.source_type, fact_type=f.fact_type)
                for f in facts
            ]
        )
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc

    return JobInfoDraftQueryRead(draft_query=draft_query)
