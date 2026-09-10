from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.models.feed_item import FEED_CATEGORIES, FEED_KIND_BY_CATEGORY, FeedItem
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
from app.services.feed.ranking import get_feed_ranker
from app.services.feed.sources import FEED_CATEGORY_LABELS, FEED_SOURCE_LABELS, all_sources

# /me는 api/profile.py(문답 아카이브)가 점유했고, 무엇보다 피드는 로그아웃
# 방문자에게도 떠야 한다 — /me/* 는 정의상 인증이 필요하므로 최상위 /feed에 둔다.
router = APIRouter(prefix="/feed", tags=["feed"])


def _to_read(item: FeedItem) -> FeedItemRead:
    return FeedItemRead(
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


def _validate_category(category: str | None, feed_kind: str) -> None:
    if category is None:
        return
    if category not in FEED_CATEGORIES or FEED_KIND_BY_CATEGORY[category] != feed_kind:
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
    """청년 지원 정책 — 최신 등록순.

    소스가 등록일을 주면 그 순서, 안 주면 우리가 처음 본 순서다. 로그인
    여부와 무관하게 같은 목록이 나간다(개인화 없음).
    """
    _validate_category(category, "policy")
    return await _build(
        db, background_tasks, refresher, ranker,
        feed_kind="policy", category=category, limit=limit, offset=offset,
        prefer_published_date=True,
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
    _validate_category(category, "job")
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
