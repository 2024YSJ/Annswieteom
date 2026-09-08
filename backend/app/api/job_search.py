from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import get_owned_session
from app.models.session import Session as SessionModel
from app.schemas.job_search import (
    JobInfoCategoryResultRead,
    JobInfoQueryRead,
    JobInfoQueryRequest,
    JobInfoResultRead,
)
from app.services.job_pipeline.job_info_client import CATEGORY_LABELS, JobInfoClient, WorknetApiError, get_job_info_client
from app.services.llm.base import AllProvidersFailedError, LLMProvider
from app.services.llm.fallback import get_llm_provider

router = APIRouter(prefix="/sessions", tags=["job_search"])

_CLARIFICATION_QUESTION = (
    "어떤 종류의 정보를 찾으시나요? 채용행사, 최근 공채 소식, 채용 기업 정보, "
    "직업훈련과정, 취업 지원 프로그램, 강소기업 중에서 궁금하신 걸 말씀해주세요."
)


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
    대화 이력은 프론트가 로컬 상태로만 누적한다(devlog 16)."""
    _require_job_search(session)

    try:
        category_queries = await llm.classify_job_info_query(payload.query)
    except AllProvidersFailedError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc

    if not category_queries:
        return JobInfoQueryRead(categories=[], clarification_question=_CLARIFICATION_QUESTION)

    async def _search_category(category: str, keywords: list[str]) -> JobInfoCategoryResultRead | None:
        try:
            results = await job_client.search(category, keywords)
        except WorknetApiError:
            # 이 카테고리만 실패 처리하고 나머지는 계속 보여준다 — 카테고리
            # 하나가 승인 대기/오류라고 질문 전체가 실패로 보이면 안 된다.
            return None
        return JobInfoCategoryResultRead(
            category=category,
            category_label=CATEGORY_LABELS[category],
            results=[JobInfoResultRead(**r.__dict__) for r in results],
        )

    searched = await asyncio.gather(
        *[_search_category(cq.category, cq.keywords) for cq in category_queries]
    )
    categories = [c for c in searched if c is not None]

    return JobInfoQueryRead(categories=categories, clarification_question=None)
