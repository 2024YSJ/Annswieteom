from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.models.feed_item import (
    JOB_SECTION_CATEGORIES,
    POLICY_SECTION_CATEGORIES,
    TRAINING_SECTION_CATEGORIES,
    FeedItem,
)
from app.models.feed_refresh_state import FeedRefreshState
from app.models.user import User
from app.schemas.feed import FeedItemRead, FeedRead, FeedSourceStatusRead
from app.services.feed.ingest import (
    feed_is_empty,
    get_feed_refresher,
    last_refreshed_at,
    stale_source_keys,
)
from app.services.feed.profile_adapter import (
    get_profile_embedder,
    has_profile_input,
    load_profile_vector,
    profile_needs_refresh,
)
from app.services.feed.matching import ItemMatch, get_region_ranker, get_tiered_ranker
from app.services.feed.ranking import get_feed_ranker
from app.services.feed.sources import FEED_CATEGORY_LABELS, FEED_SOURCE_LABELS, all_sources
from app.services.profile.attributes import load_match_profile

# /me는 api/profile.py(문답 아카이브)가 점유했고, 무엇보다 피드는 로그아웃
# 방문자에게도 떠야 한다 — /me/* 는 정의상 인증이 필요하므로 최상위 /feed에 둔다.
router = APIRouter(prefix="/feed", tags=["feed"])


def _to_read(item: FeedItem, match: ItemMatch | None = None) -> FeedItemRead:
    extra = (
        {"match_tier": match.tier, "matched_labels": match.matched_labels, "unmet_labels": match.unmet_labels}
        if match is not None
        else {}
    )
    return FeedItemRead(
        **extra,
        id=item.id,
        source=item.source,
        source_label=FEED_SOURCE_LABELS.get(item.source, item.source),
        category=item.category,
        category_label=FEED_CATEGORY_LABELS.get(item.category, item.category),
        feed_kind=item.feed_kind,
        title=item.title,
        subtitle=item.subtitle or "",
        meta_lines=list(item.meta_lines or []),
        detail_url=item.detail_url,
        source_published_at=item.source_published_at,
        first_seen_at=item.first_seen_at,
    )


def _validate_category(category: str | None, allowed: tuple[str, ...]) -> None:
    """섹션 밖의 카테고리를 고르면 422 — 예: 정책 섹션에서 훈련과정을 요청."""
    if category is not None and category not in allowed:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_feed_category")


async def _schedule_refresh_if_needed(db: AsyncSession, background_tasks: BackgroundTasks, refresher) -> bool:
    """캐시가 비었거나 만료됐으면 백그라운드 갱신을 예약한다. 응답은 언제나
    캐시에서 즉시 나간다(stale-while-revalidate).

    돌려주는 값은 "지금 캐시가 비어 있는가"다 — 최초 1회는 BackgroundTasks가
    응답 이후에 돌기 때문에 구조적으로 빈 응답이 나갈 수밖에 없고, 프론트가
    그걸 로딩 상태로 그릴 수 있어야 한다.
    """
    empty = await feed_is_empty(db)
    if empty or await stale_source_keys(db):
        background_tasks.add_task(refresher)
    return empty


async def _build(
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    refresher,
    ranker,
    *,
    feed_kind: str,
    category: str | None,
    limit: int,
    offset: int,
    categories: tuple[str, ...] | None = None,
    profile_vector: list[float] | None = None,
    fallback_reason: str | None = None,
    prefer_published_date: bool = False,
    interleave_categories: bool = False,
) -> FeedRead:
    is_warming = await _schedule_refresh_if_needed(db, background_tasks, refresher)
    ranked = await ranker(
        db,
        feed_kind=feed_kind,
        category=category,
        categories=categories,
        profile_vector=profile_vector,
        prefer_published_date=prefer_published_date,
        interleave_categories=interleave_categories,
        limit=limit,
        offset=offset,
    )
    # 정렬 질의가 실제로 터졌을 때만 고장 안내를 띄운다. "벡터를 넘겼는데
    # 최신순으로 내려왔다"는 조건만 보면, 아직 항목 임베딩이 안 채워진 정상
    # 상태(= 갓 수집된 피드)까지 고장으로 잘못 보고한다 — 그건 `preparing`이다.
    if ranked.vector_ranking_failed:
        fallback_reason = "ai_unavailable"
    return FeedRead(
        items=[_to_read(i) for i in ranked.items],
        total=ranked.total,
        limit=limit,
        offset=offset,
        personalized=ranked.personalized,
        fallback_reason=None if ranked.personalized else fallback_reason,
        is_warming=is_warming,
        refreshed_at=await last_refreshed_at(db),
    )


@router.get("/policies", response_model=FeedRead)
async def list_policy_feed(
    background_tasks: BackgroundTasks,
    category: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
    refresher=Depends(get_feed_refresher),
    ranker=Depends(get_feed_ranker),
) -> FeedRead:
    """청년 지원 정책(온통청년) — 최신 등록순.

    소스가 등록일을 주면 그 순서, 안 주면 우리가 처음 본 순서다. 로그인
    여부와 무관하게 같은 목록이 나간다(개인화 없음). 고용24 훈련과정·구직자
    프로그램은 같은 "policy"로 저장돼 있지만 /feed/trainings로 따로 나간다.
    """
    _validate_category(category, POLICY_SECTION_CATEGORIES)
    return await _build(
        db, background_tasks, refresher, ranker,
        feed_kind="policy", category=category, categories=POLICY_SECTION_CATEGORIES,
        limit=limit, offset=offset, prefer_published_date=True,
    )


@router.get("/trainings", response_model=FeedRead)
async def list_training_feed(
    background_tasks: BackgroundTasks,
    category: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
    refresher=Depends(get_feed_refresher),
    ranker=Depends(get_feed_ranker),
) -> FeedRead:
    """직업훈련·취업 프로그램(고용24 훈련과정 + 구직자취업역량 강화프로그램).

    두 카테고리를 라운드로빈으로 섞는다 — 최신순만 쓰면 한 번의 수집에서 마지막에
    들어간 카테고리가 통째로 앞을 차지한다(ranking._interleaved_order 주석).
    """
    _validate_category(category, TRAINING_SECTION_CATEGORIES)
    return await _build(
        db, background_tasks, refresher, ranker,
        feed_kind="policy", category=category, categories=TRAINING_SECTION_CATEGORIES,
        limit=limit, offset=offset, interleave_categories=True,
    )


@router.get("/jobs", response_model=FeedRead)
async def list_job_feed(
    background_tasks: BackgroundTasks,
    category: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
    refresher=Depends(get_feed_refresher),
    ranker=Depends(get_feed_ranker),
) -> FeedRead:
    """공고 피드 — 최신순, 로그인 여부 무관.

    익명 방문자도 그대로 받는다. 지금 랜딩을 실제로 보는 건 로그아웃
    방문자와 세션이 없는 사용자뿐이라, 여기서 401을 내면 기능이 사실상
    안 보인다.
    """
    _validate_category(category, JOB_SECTION_CATEGORIES)
    return await _build(
        db, background_tasks, refresher, ranker,
        feed_kind="job", category=category, limit=limit, offset=offset,
        # 순수 최신순이면 목록이 카테고리 덩어리가 되고, 링크를 못 다는
        # 강소기업이 통째로 앞을 막는다(ranking._interleaved_order 주석 참고).
        interleave_categories=True,
    )


@router.get("/jobs/recommended", response_model=FeedRead)
async def list_recommended_job_feed(
    background_tasks: BackgroundTasks,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    refresher=Depends(get_feed_refresher),
    ranker=Depends(get_feed_ranker),
    profile_embedder=Depends(get_profile_embedder),
) -> FeedRead:
    """맞춤 공고 — 문답 기록으로 만든 프로필 벡터와의 코사인 거리순.

    게스트도 막지 않는다. api/profile.py는 게스트에게 403을 주지만 그건
    "세션을 넘어 쌓인 아카이브"가 게스트에겐 성립하지 않아서이고, 랭킹은
    신호가 조금이라도 있으면 이득인 데다 돌려주는 건 공개 공고뿐이라
    사용자 본인 텍스트가 밖으로 나가지 않는다.

    읽기 경로는 절대 임베딩 호출을 기다리지 않는다 — 저장된 벡터가 없거나
    문답이 늘었으면 최신순으로 응답하면서 갱신만 백그라운드로 예약한다.
    """
    # user_id를 먼저 붙잡아 둔다. 아래 프로필 조회들은 실패 시 db.rollback()을
    # 부르는데, rollback은 세션에 붙은 ORM 객체를 전부 expire시킨다 — 그 뒤에
    # current_user.id를 읽으면 lazy refresh(IO)가 일어나고, 요청 핸들러에는
    # greenlet 컨텍스트가 없어 MissingGreenlet으로 터진다. 테스트에서 먼저
    # 잡혔지만 프로덕션에서도 벡터 차원 불일치 등으로 같은 경로를 탈 수 있다.
    user_id = current_user.id

    # 문답이든 직접 쓴 희망사항이든, 개인화에 쓸 재료가 하나라도 있으면 켠다.
    # 예전엔 문답 개수만 셌는데, 그러면 "맞춤 정보"만 적어둔 사용자가 영영
    # 개인화되지 않는다 — 인터뷰를 아직 안 한 사람에게 조종간을 주려고 만든
    # 기능이므로 그게 바로 이 기능이 필요한 사람이다.
    has_input = await has_profile_input(db, user_id)
    vector = await load_profile_vector(db, user_id) if has_input else None

    if has_input and await profile_needs_refresh(db, user_id):
        background_tasks.add_task(profile_embedder, user_id)

    fallback_reason = None
    if not has_input:
        fallback_reason = "no_profile"
    elif vector is None:
        # 문답은 있는데 벡터가 아직 없다 = 방금 계산을 예약한 상태. 문답을
        # 처음 남긴 사용자는 전부 여기를 한 번 지나가므로 고장 안내가 아니라
        # "준비 중"이어야 한다.
        fallback_reason = "preparing"

    return await _build(
        db, background_tasks, refresher, ranker,
        feed_kind="job", category=None, limit=limit, offset=offset,
        profile_vector=vector, fallback_reason=fallback_reason,
    )


@router.get("/policies/recommended", response_model=FeedRead)
async def list_recommended_policy_feed(
    background_tasks: BackgroundTasks,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    include_excluded: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    refresher=Depends(get_feed_refresher),
    ranker=Depends(get_feed_ranker),
    tiered_ranker=Depends(get_tiered_ranker),
) -> FeedRead:
    """맞춤 정책 — 걸린 조건이 모두 맞는 정책(교집합) 먼저, 일부 맞는 정책
    (합집합) 다음, 나머지는 프로필 벡터 유사도순.

    조건 판정은 대화로 알게 된 속성(user_attributes)과 온통청년 자격조건 코드를
    필드별로 대조한다(services/feed/matching.py). 나이·거주지가 맞지 않는 정책은
    신청 자격이 없으므로 기본적으로 뺀다 — `include_excluded=true`면 맨 뒤에 붙인다.

    게스트도 받는다(맞춤 공고와 같은 이유). 속성이 하나도 없으면 최신순 +
    `fallback_reason="no_attributes"`.
    """
    # rollback이 ORM 객체를 expire시키므로 id를 먼저 잡는다(list_recommended_job_feed 주석).
    user_id = current_user.id
    profile = await load_match_profile(db, user_id)
    if profile.is_empty:
        return await _build(
            db, background_tasks, refresher, ranker,
            feed_kind="policy", category=None, categories=POLICY_SECTION_CATEGORIES,
            limit=limit, offset=offset, prefer_published_date=True, fallback_reason="no_attributes",
        )

    is_warming = await _schedule_refresh_if_needed(db, background_tasks, refresher)
    # 벡터는 티어 안에서의 2차 정렬에만 쓴다. 없어도(아직 계산 전, SQLite) 티어는 그대로다.
    vector = await load_profile_vector(db, user_id)
    # 온통청년만 — 고용24 훈련·프로그램은 자격조건 정보가 없어 매칭이 안 되고
    # "조건 없음"으로 뒤에 섞일 뿐이다(2026-09-11 결정).
    ranked = await tiered_ranker(
        db,
        feed_kind="policy",
        category="youth_policy",
        profile=profile,
        profile_vector=vector,
        include_excluded=include_excluded,
        limit=limit,
        offset=offset,
    )
    return FeedRead(
        items=[_to_read(i, ranked.matches.get(i.id)) for i in ranked.items],
        total=ranked.total,
        limit=limit,
        offset=offset,
        personalized=True,
        fallback_reason=None,
        is_warming=is_warming,
        refreshed_at=await last_refreshed_at(db),
    )


@router.get("/trainings/recommended", response_model=FeedRead)
async def list_recommended_training_feed(
    background_tasks: BackgroundTasks,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    refresher=Depends(get_feed_refresher),
    ranker=Depends(get_feed_ranker),
    region_ranker=Depends(get_region_ranker),
) -> FeedRead:
    """맞춤 직업훈련 — 거주지·희망지역에서 열리는 과정 먼저, 그 안에서 프로필 벡터
    유사도순(2026-09-11 결정: 훈련은 통학해야 하니 지역이 먼저).

    개인화 재료가 하나도 없으면(지역 속성도 벡터도 없음) 일반 목록 + `no_attributes`.
    """
    # rollback이 ORM 객체를 expire시키므로 id를 먼저 잡는다(list_recommended_job_feed 주석).
    user_id = current_user.id
    profile = await load_match_profile(db, user_id)
    vector = await load_profile_vector(db, user_id)
    if not profile.region_codes and vector is None:
        return await _build(
            db, background_tasks, refresher, ranker,
            feed_kind="policy", category=None, categories=TRAINING_SECTION_CATEGORIES,
            limit=limit, offset=offset, interleave_categories=True, fallback_reason="no_attributes",
        )

    is_warming = await _schedule_refresh_if_needed(db, background_tasks, refresher)
    ranked = await region_ranker(
        db,
        feed_kind="policy",
        categories=TRAINING_SECTION_CATEGORIES,
        profile=profile,
        profile_vector=vector,
        limit=limit,
        offset=offset,
    )
    return FeedRead(
        items=[_to_read(i, ranked.matches.get(i.id)) for i in ranked.items],
        total=ranked.total,
        limit=limit,
        offset=offset,
        personalized=True,
        fallback_reason=None,
        is_warming=is_warming,
        refreshed_at=await last_refreshed_at(db),
    )


@router.get("/sources", response_model=list[FeedSourceStatusRead])
async def list_feed_sources(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FeedSourceStatusRead]:
    """소스별 설정/수집 상태. 인증 필요 — 외부 API 설정 상태를 익명에 노출하지 않는다.

    피드가 비어 보일 때 "키가 안 들어갔다"와 "호출이 실패한다"를 구분하기 위한
    진단용이다. `configured_sources()`가 아니라 `all_sources()`를 도는 게
    핵심이다 — 조용히 빠진 소스가 목록에서도 사라지면 진단이 안 된다.
    """
    states = {
        row.source_key: row
        for row in (await db.execute(select(FeedRefreshState))).scalars().all()
    }
    counts = {
        (source, category): total
        for source, category, total in (
            await db.execute(
                select(FeedItem.source, FeedItem.category, func.count(FeedItem.id))
                .where(FeedItem.is_active.is_(True))
                .group_by(FeedItem.source, FeedItem.category)
            )
        ).all()
    }

    rows: list[FeedSourceStatusRead] = []
    for source in all_sources():
        for category in source.categories:
            key = f"{source.name}:{category}"
            state = states.get(key)
            rows.append(
                FeedSourceStatusRead(
                    source=source.name,
                    source_label=FEED_SOURCE_LABELS.get(source.name, source.name),
                    category=category,
                    category_label=FEED_CATEGORY_LABELS.get(category, category),
                    source_key=key,
                    configured=source.is_category_configured(category),
                    last_succeeded_at=state.last_succeeded_at if state else None,
                    last_failed_at=state.last_failed_at if state else None,
                    last_error=state.last_error if state else None,
                    item_count=state.item_count if state else 0,
                    active_item_count=counts.get((source.name, category), 0),
                )
            )
    return rows
