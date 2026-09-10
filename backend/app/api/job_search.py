from __future__ import annotations

import asyncio
import time

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
from app.services.job_pipeline.regions import KNOWN_REGION_NAMES
from app.services.llm.base import JobInfoCandidate, LLMProvider, LLMUnavailableError
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

# 분류가 6개를 다 고르는 일이 실제로 흔하다("백엔드 개발자, 경기 북부"가 그렇다)
# — 카테고리마다 관련성 판단 LLM 호출이 하나씩 붙으므로 상한을 두지 않으면
# 질문 한 번이 LLM 호출 7회가 된다. 분류 프롬프트가 관련성 높은 순으로
# 내놓으므로 앞에서부터 자른다.
_MAX_CATEGORIES_PER_QUERY = 3

# 질문 하나가 쓸 수 있는 전체 시간 예산. 예산을 넘기면 남은 카테고리는
# skipped로 넘기고 그때까지 모인 결과만 돌려준다 — 무한정 기다리다 화면이
# 멈추는 것보다 부분 결과가 낫다. 이 값은 로컬 3b + 후보 20건 기준으로
# 관련성 판단 1회가 ~37초 걸리는 현실에 맞춘 잠정치다(devlog 20 실측).
# 조회에 검색 조건이 실려 후보 수가 줄면 훨씬 내려갈 수 있다.
# 2026-09-10 상향: 추론 서버가 DGX Spark로 바뀌면서 관련성 판단 1회가 훨씬
# 오래 걸린다 — 대역폭(273GB/s)이 decode 벽이고 qwen2.5:72b는 3.0 tok/s로
# 실측됐다. 운영 모델을 32b로 내려도 4090+14b 시절보다는 느리다. 90초로는 첫
# 카테고리도 못 넘기고 전부 skipped로 떨어져 화면이 늘 비어 보인다. 위의
# _MAX_CATEGORIES_PER_QUERY=3과 함께 읽어야 하는 값이다 — 예산은 3회분이다.
_QUERY_BUDGET_SECONDS = 600.0


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

    selected_categories = [cq.category for cq in category_queries][:_MAX_CATEGORIES_PER_QUERY]

    # 조회에 실을 검색 조건(지역/직무 키워드)을 뽑는다. 이게 없던 동안에는
    # 카테고리(=엔드포인트)만 맞게 고르고 조회는 전국 첫 20건을 무조건
    # 받아왔다 — "경기 북부 백엔드"라고 물어도 후보에 강원/경남 과정이
    # 들어오니 관련성 판단이 아무리 정확해도 건질 게 없었다(devlog 20).
    try:
        query_params = await llm.extract_job_info_query_params(payload.query, list(KNOWN_REGION_NAMES))
    except LLMUnavailableError:
        # 조건 추출이 실패하면 조건 없이라도 조회한다 — 예전 동작으로
        # 퇴화할 뿐이고, 질문 전체를 실패시키는 것보다 낫다.
        query_params = None

    # 워크넷 조회는 병렬로 던진다 — 순수 HTTP라 실제로 동시에 처리되고
    # 카테고리당 0.2~1.2초로 끝난다.
    async def _fetch(category: str) -> list | None:
        try:
            return await job_client.search(category, query_params)
        except WorknetApiError:
            # 이 카테고리만 실패 처리하고 나머지는 계속 보여준다 — 카테고리
            # 하나가 승인 대기/오류라고 질문 전체가 실패로 보이면 안 된다.
            return None

    fetched = await asyncio.gather(*[_fetch(category) for category in selected_categories])

    # 관련성 판단은 반대로 순차 처리한다. 로컬 Ollama는 요청을 직렬로 처리하니
    # 동시에 던지면 뒤쪽 호출들이 큐에서 기다리는 동안 자기 타임아웃을 다 써버린다
    # — 6개를 asyncio.gather로 던졌을 때 1개만 성공하고 5개가 45초 타임아웃으로
    # 죽는 걸 실측했다(devlog 20). 즉 fan-out은 싼 쪽(HTTP)에서만 하고 비싼
    # 쪽(LLM)에서는 하지 않는다.
    deadline = time.monotonic() + _QUERY_BUDGET_SECONDS
    categories: list[JobInfoCategoryResultRead] = []
    skipped: list[str] = []

    for category, raw_results in zip(selected_categories, fetched):
        label = CATEGORY_LABELS[category]
        if raw_results is None:
            skipped.append(label)
            continue
        if not raw_results:
            categories.append(JobInfoCategoryResultRead(category=category, category_label=label, results=[]))
            continue

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            skipped.append(label)
            continue

        candidates = [
            JobInfoCandidate(index=i, title=r.title, subtitle=r.subtitle, meta_lines=r.meta_lines)
            for i, r in enumerate(raw_results)
        ]
        try:
            async with asyncio.timeout(remaining):
                relevant_indices = await llm.select_relevant_job_info_results(payload.query, label, candidates)
        # TimeoutError를 계속 같이 잡는다. LLMUnavailableError가 프로바이더 쪽
        # httpx 타임아웃을 이미 흡수하지만, 여기 asyncio.timeout(remaining)은
        # 그 바깥에서 도는 전체 예산 타이머라 여전히 맨 TimeoutError를 던진다
        # — 이걸 빼면 큐에 밀린 호출이 예산을 태울 때 라우트가 500으로 죽는다.
        except (LLMUnavailableError, TimeoutError):
            # 원본 목록은 받아왔지만 관련성 판단이 안 되면, 걸러지지 않은
            # 목록을 그대로 보여주느니 이 카테고리를 빼는 쪽이 낫다 — 그게
            # 바로 devlog 18에서 고친 문제(무관한 결과 노출)이기 때문이다.
            # 다만 예전처럼 조용히 버리지 않고 무엇이 빠졌는지 알려준다.
            skipped.append(label)
            continue

        selected = [raw_results[i] for i in relevant_indices][:_MAX_RESULTS_PER_CATEGORY]
        categories.append(
            JobInfoCategoryResultRead(
                category=category,
                category_label=label,
                results=[JobInfoResultRead(**r.__dict__) for r in selected],
            )
        )

    return JobInfoQueryRead(categories=categories, clarification_question=None, skipped_category_labels=skipped)


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
