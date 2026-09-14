from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_owned_session
from app.db.session import get_db
from app.models.activity_category import ActivityCategory
from app.models.confirmed_fact import ConfirmedFact
from app.models.session import Session as SessionModel
from app.models.user import User
from app.schemas.job_search import (
    JobInfoCategoryResultRead,
    JobInfoDraftQueryRead,
    JobInfoQueryRead,
    JobInfoQueryRequest,
    JobInfoResultRead,
)
from app.services.job_pipeline.job_info_client import CATEGORY_LABELS, JobInfoClient, WorknetApiError, get_job_info_client
from app.services.job_pipeline.regions import KNOWN_REGION_NAMES, region_label_for
from app.services.llm.base import JobInfoCandidate, JobInfoQueryParams, LLMProvider, LLMUnavailableError
from app.services.llm.base import ConfirmedFact as LLMConfirmedFact
from app.services.llm import get_llm_provider
from app.services.profile.attributes import get_profile_extractor, load_match_profile, profile_summary_lines

logger = logging.getLogger(__name__)

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

# 관련성 판정 후 남은 결과가 이보다 적으면 조건을 한 번 풀어 다시 조회한다
# (devlog 44). job_info_client.py의 _MIN_RESULTS_BEFORE_WIDENING(원본 건수 기준,
# training_course 내부 전용)과는 다른 값이다 — 여기는 "관련성 판정까지 끝난 뒤"
# 기준이라 더 낮게 잡는다. 실측: "경기 프로그래머 강소기업"이 지역 필터 때문에
# 0건이었는데 지역을 빼자 바로 1건이 나왔다 — 좁은 필터가 서버 쪽에서 이미
# 후보를 20건으로 제한한 뒤라, 그 20건 안에 관련 항목이 우연히 없으면 그걸로
# 끝이었다.
_MIN_RELEVANT_BEFORE_WIDENING = 3

# 서버 필터가 없는 3개 카테고리(_UNFILTERED_FETCH_LIMIT 기본값)는 조건을 뗄 게
# 없으니 대신 후보 풀 자체를 넓혀서 재시도한다 — 진짜 페이지네이션(startPage=2)은
# 이번 범위 밖(JobInfoClient.search 인터페이스를 더 크게 건드려야 함).
_WIDENED_UNFILTERED_LIMIT = 60

# 프론트가 실어 보내는 history(이전 사용자 발화)를 이 개수만큼만 쓴다 — 무상태
# 대화라 프론트가 전체 turns를 다 보낼 수도 있는데, 프롬프트가 한없이 길어지면
# 안 된다(devlog 44).
_MAX_HISTORY_TURNS = 5


def _widen_attempt(
    category: str, query_params: JobInfoQueryParams | None
) -> tuple[JobInfoQueryParams | None, int | None] | None:
    """관련성 판정 결과가 모자랄 때 무엇을 풀어 다시 조회할지 정한다(devlog 44).
    더 넓힐 방법이 없으면(예: training_course — 이미 job_info_client.py 내부에서
    자체적으로 단계적으로 넓힌 뒤라 여기서 더 할 게 없다) None을 돌려준다."""
    if category == "promising_sme" and query_params and query_params.regions:
        # 유일한 서버 필터가 region이다 — 그걸 떼고 전국으로 넓힌다.
        return JobInfoQueryParams(regions=[], keywords=query_params.keywords), None
    if category == "job_fair" and query_params and query_params.keywords:
        # 유일한 서버 필터가 keyword다 — 그걸 떼고 지역만(또는 무조건) 넓힌다.
        return JobInfoQueryParams(regions=query_params.regions, keywords=[]), None
    if category in ("public_recruitment", "public_recruitment_company", "job_seeker_program"):
        # 서버 필터 자체가 없다 — 조건을 풀 게 없으니 후보 풀을 넓힌다.
        return query_params, _WIDENED_UNFILTERED_LIMIT
    return None


def _require_job_search(session: SessionModel) -> None:
    if session.kind != "job_search":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_a_job_search_session")


async def _profile_hint_lines(db: AsyncSession, user_id) -> list[str]:
    """classify_job_info_query에 넘길 짧은 프로필 힌트 — "내 맞춤 정보에 따라
    찾아줘"처럼 질문 자체엔 주제어가 없는 자기참조적 질문을 카테고리로 매핑하기
    위한 것(2026-09-14 리포트). 정보가 없으면 빈 리스트(게스트 포함)."""
    profile = await load_match_profile(db, user_id)
    lines = []
    if profile.desired_job:
        lines.append(f"희망직무: {profile.desired_job}")
    regions = [label for code in profile.desired_region_codes if (label := region_label_for(code))]
    if regions:
        lines.append(f"희망지역: {', '.join(regions)}")
    return lines


async def _profile_derived_query_params(db: AsyncSession, user_id) -> JobInfoQueryParams | None:
    """구조화된 희망직무/희망지역이 있으면 그것을 조회 조건으로 쓴다.

    "괜찮은 데 있나요"처럼 이번 메시지에 조건이 없어도, 프로필에 남은 희망사항
    으로 조회를 좁힌다 — 안 그러면 조건 0개로 전국 첫 N건이 그대로 나가
    지역·직무 둘 다 무관한 결과가 섞인다(2026-09-13 리포트).
    """
    profile = await load_match_profile(db, user_id)
    regions = [label for code in profile.desired_region_codes if (label := region_label_for(code))]
    keywords = [profile.desired_job] if profile.desired_job else []
    if not regions and not keywords:
        return None
    return JobInfoQueryParams(regions=regions, keywords=keywords)


@router.post("/{session_id}/job-search/query", response_model=JobInfoQueryRead)
async def query_job_info(
    payload: JobInfoQueryRequest,
    background_tasks: BackgroundTasks,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    job_client: JobInfoClient = Depends(get_job_info_client),
    extractor=Depends(get_profile_extractor),
) -> JobInfoQueryRead:
    """무상태 대화형 검색 — 매 질문마다 관련 카테고리(들)를 판단하고 그
    자리에서 바로 조회한다. 확정/저장할 게 없어(급여/조건을 모아뒀다가
    나중에 검색하던 이전 버전과 달리) 세션에 아무것도 영속화하지 않는다 —
    대화 이력은 프론트가 로컬 상태로만 누적한다(devlog 16).

    카테고리 안에서 실제로 어떤 항목을 보여줄지는 고용24 원본 목록을 통째로
    LLM에게 보여주고 고르게 한다(select_relevant_job_info_results) — 사용자
    질문 키워드를 응답 텍스트에 문자열로 부분일치시키던 이전 방식은 "경기
    북부"라고 물었을 때 실제 데이터엔 "의정부"/"파주"처럼 구체적인 지명만
    있는 경우를 전혀 못 잡아서(2026-09-08 실사용 피드백) 폐기했다 —
    devlog 18 참고."""
    _require_job_search(session)
    # 검색 질문도 사용자가 자기에 대해 한 말이다("경기 북부 백엔드 신입") — 희망
    # 지역·직무를 프로필로 남긴다. 응답을 보낸 뒤 백그라운드에서만 돈다(이 라우트는
    # 이미 LLM 호출이 많아 요청 경로에 하나를 더 얹을 수 없다).
    background_tasks.add_task(extractor, session.user_id, "job_search", payload.query)

    profile_hint = await _profile_hint_lines(db, session.user_id)
    # 프론트가 이미 들고 있는 turns를 그대로 실어 보낸 것 — 세션에는 아무것도
    # 저장하지 않으므로(무상태) 프롬프트가 길어지지 않게 최근 N턴만 쓴다(devlog 44).
    history = payload.history[-_MAX_HISTORY_TURNS:]

    try:
        category_queries, unsupported_note = await llm.classify_job_info_query(payload.query, profile_hint, history)
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc

    if not category_queries:
        # unsupported_note가 있으면(예: "카페 알바 알려줘") 일반적인 재질문 문구보다
        # "이건 우리가 다루는 정보가 아니다"를 그대로 보여주는 게 사용자에게 더 정확하다.
        if unsupported_note:
            return JobInfoQueryRead(categories=[], unsupported_note=unsupported_note)
        return JobInfoQueryRead(categories=[], clarification_question=_CLARIFICATION_QUESTION)

    selected_categories = [cq.category for cq in category_queries][:_MAX_CATEGORIES_PER_QUERY]

    # 조회에 실을 검색 조건(지역/직무 키워드)을 뽑는다. 이게 없던 동안에는
    # 카테고리(=엔드포인트)만 맞게 고르고 조회는 전국 첫 20건을 무조건
    # 받아왔다 — "경기 북부 백엔드"라고 물어도 후보에 강원/경남 과정이
    # 들어오니 관련성 판단이 아무리 정확해도 건질 게 없었다(devlog 20).
    try:
        query_params = await llm.extract_job_info_query_params(payload.query, list(KNOWN_REGION_NAMES), history)
    except LLMUnavailableError:
        # 조건 추출이 실패하면 조건 없이라도 조회한다 — 예전 동작으로
        # 퇴화할 뿐이고, 질문 전체를 실패시키는 것보다 낫다.
        query_params = None

    # 카테고리는 선택됐는데(=이 앱이 다루는 개념) unsupported_note가 방금 추출한
    # 지역 이름을 그대로 언급하면 모순이다 — 지역은 검색 조건일 뿐 "다루지 않는
    # 개념"이 될 수 없다. 실측 사례(2026-09-14): "내 프로필 말고 인천에서 디자이너
    # 뽑는 데 있어?"가 categories=["public_recruitment"]를 정확히 고르고도
    # "인천 지역 채용정보... 아직 지원하지 않아요"를 만들어냈다 — 프롬프트
    # 지시(Phase 3)만으로 100% 막을 수 없으니 값싼 사후 방어선을 둔다.
    if unsupported_note and query_params and query_params.regions:
        if any(region in unsupported_note for region in query_params.regions):
            logger.warning(
                "job_search: dropped contradictory unsupported_note %r for regions %s",
                unsupported_note,
                query_params.regions,
            )
            unsupported_note = None

    # 이번 메시지에 조건이 없으면(추출 실패 포함) 로그인 사용자(게스트 제외)의
    # 저장된 희망직무/희망지역으로 대체한다 — 조건 0개로 전국 첫 N건이 그대로
    # 나가 지역·직무 둘 다 무관한 결과가 섞이던 것이 이 버그의 근본 원인이었다
    # (2026-09-13 리포트). 게스트는 저장된 속성이 없으므로 원래도 영향이 없다.
    if not query_params or (not query_params.regions and not query_params.keywords):
        user = await db.get(User, session.user_id)
        if user is not None and not user.is_guest:
            profile_params = await _profile_derived_query_params(db, session.user_id)
            if profile_params is not None:
                query_params = profile_params

    # 고용24 조회는 병렬로 던진다 — 순수 HTTP라 실제로 동시에 처리되고
    # 카테고리당 0.2~1.2초로 끝난다.
    async def _fetch(category: str) -> list | None:
        try:
            return await job_client.search(category, query_params)
        except WorknetApiError as exc:
            # 이 카테고리만 실패 처리하고 나머지는 계속 보여준다 — 카테고리
            # 하나가 승인 대기/오류라고 질문 전체가 실패로 보이면 안 된다.
            # 로깅이 아예 없어 2026-09-12 고용24 전면 장애를 API 응답만으로는
            # 진단할 수 없었다 — 원인(카테고리명 + 오류 메시지, authKey 없음)을 남긴다.
            logger.warning("job_search: %s skipped: %s", category, exc)
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

    async def _judge_relevant(category: str, label: str, raw: list, remaining: float) -> list | None:
        """반환값이 None이면 판정 자체가 실패한 것(타임아웃/LLM 다운) — 빈
        리스트(판정은 됐지만 관련 항목이 없음)와는 구분해야 한다."""
        if not raw:
            return []
        candidates = [
            JobInfoCandidate(index=i, title=r.title, subtitle=r.subtitle, meta_lines=r.meta_lines)
            for i, r in enumerate(raw)
        ]
        try:
            async with asyncio.timeout(remaining):
                relevant_indices = await llm.select_relevant_job_info_results(payload.query, label, candidates)
        # TimeoutError를 계속 같이 잡는다. LLMUnavailableError가 프로바이더 쪽
        # httpx 타임아웃을 이미 흡수하지만, 여기 asyncio.timeout(remaining)은
        # 그 바깥에서 도는 전체 예산 타이머라 여전히 맨 TimeoutError를 던진다
        # — 이걸 빼면 큐에 밀린 호출이 예산을 태울 때 라우트가 500으로 죽는다.
        except (LLMUnavailableError, TimeoutError) as exc:
            logger.warning("job_search: %s relevance judging skipped: %s", category, exc)
            return None
        return [raw[i] for i in relevant_indices]

    for category, raw_results in zip(selected_categories, fetched):
        label = CATEGORY_LABELS[category]
        if raw_results is None:
            skipped.append(label)
            continue

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            skipped.append(label)
            continue

        selected = await _judge_relevant(category, label, raw_results, remaining)
        if selected is None:
            # 원본 목록은 받아왔지만 관련성 판단이 안 되면, 걸러지지 않은
            # 목록을 그대로 보여주느니 이 카테고리를 빼는 쪽이 낫다 — 그게
            # 바로 devlog 18에서 고친 문제(무관한 결과 노출)이기 때문이다.
            # 다만 예전처럼 조용히 버리지 않고 무엇이 빠졌는지 알려준다.
            skipped.append(label)
            continue

        broadened = False
        if len(selected) < _MIN_RELEVANT_BEFORE_WIDENING:
            widen = _widen_attempt(category, query_params)
            remaining = deadline - time.monotonic()
            if widen is not None and remaining > 0:
                widened_params, widened_limit = widen
                try:
                    widened_raw = await job_client.search(category, widened_params, widened_limit)
                except WorknetApiError as exc:
                    logger.warning("job_search: %s widen-retry fetch failed: %s", category, exc)
                    widened_raw = []
                if widened_raw:
                    remaining = deadline - time.monotonic()
                    widened_selected = (
                        await _judge_relevant(category, label, widened_raw, remaining) if remaining > 0 else None
                    )
                    if widened_selected:
                        # 제목+부제로 중복 제거 — job_info_client.py의 훈련과정
                        # widen 병합과 같은 키(같은 항목이 1차/2차 조회에 둘 다
                        # 걸릴 수 있다).
                        merged = {(r.title, r.subtitle): r for r in [*selected, *widened_selected]}
                        if len(merged) > len(selected):
                            broadened = True
                        selected = list(merged.values())

        selected = selected[:_MAX_RESULTS_PER_CATEGORY]
        categories.append(
            JobInfoCategoryResultRead(
                category=category,
                category_label=label,
                results=[JobInfoResultRead(**r.__dict__) for r in selected],
                broadened=broadened,
            )
        )

    return JobInfoQueryRead(
        categories=categories,
        clarification_question=None,
        skipped_category_labels=skipped,
        unsupported_note=unsupported_note,
    )


@router.post("/{session_id}/job-search/draft-query-from-gap", response_model=JobInfoDraftQueryRead)
async def draft_query_from_gap(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    extractor=Depends(get_profile_extractor),
) -> JobInfoDraftQueryRead:
    """커리어 채우기 세션에서 "취업 정보 검색으로 이관"한 직후, 그 세션의
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

    # 이관 순간 바로 희망직무/희망지역을 반영한다 — 평소엔 인터뷰 답변마다
    # 백그라운드로 도는 추출이 이관 자체에서는 안 도니, 그 자리에서 동기로
    # 한 번 불러준다(이 함수는 자기 세션을 열고 예외를 삼킨다, attributes.py
    # 참고 — 실패해도 아래 초안 생성 자체는 계속된다). 이래야 바로 다음 줄의
    # profile_summary_lines가 방금 반영된 값을 읽는다(2026-09-14 리포트).
    await extractor(session.user_id, "job_search", "\n".join(f.content for f in facts))
    profile_summary = await profile_summary_lines(db, session.user_id)

    try:
        draft_query = await llm.draft_job_info_query_from_facts(
            [
                LLMConfirmedFact(id=str(f.id), content=f.content, source_type=f.source_type, fact_type=f.fact_type)
                for f in facts
            ],
            profile_summary,
        )
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc

    return JobInfoDraftQueryRead(draft_query=draft_query)
