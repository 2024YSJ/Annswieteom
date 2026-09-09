from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_owned_session
from app.db.session import get_db
from app.models.activity_category import ActivityCategory
from app.models.gap_period import GapPeriod
from app.models.session import Session as SessionModel
from app.schemas.coverage import (
    CategoryPeriodUpdate,
    CoverageFillRead,
    CoverageFillRequest,
    CoverageRead,
    DateRangeRead,
)
from app.services.coverage import DateRange, build_coverage_report, label_for_range, probe_question_for

router = APIRouter(prefix="/sessions", tags=["coverage"])

# 빈 구간 채우기를 허용하는 상태. 기간 입력/카테고리 선택 단계에서는 아직 커버리지를
# 계산할 활동 자체가 없고, 문서를 이미 확정한 뒤(RESULT_REVIEW)라면 카테고리를 새로
# 끼워 넣는 대신 재생성을 거쳐야 하므로 제외한다.
_FILL_ALLOWED_STATUSES = ("INTERVIEWING", "RESULT_GENERATE")


def _range_read(r: DateRange) -> DateRangeRead:
    return DateRangeRead(start=r.start, end=r.end, days=r.days)


async def _load_gap_and_categories(
    session: SessionModel, db: AsyncSession
) -> tuple[GapPeriod, list[ActivityCategory]]:
    gap_period = (
        await db.execute(select(GapPeriod).where(GapPeriod.session_id == session.id))
    ).scalar_one_or_none()
    if gap_period is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="gap_period_not_set")
    categories = list(
        (
            await db.execute(select(ActivityCategory).where(ActivityCategory.session_id == session.id))
        ).scalars().all()
    )
    return gap_period, categories


@router.get("/{session_id}/coverage", response_model=CoverageRead)
async def get_coverage(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
) -> CoverageRead:
    """공백기가 실제로 얼마나 설명됐는지.

    서비스 이름이 "공백기 채우기"인데도 2026-09-09 전까지는 이걸 계산할 수
    없었다 — 활동에 날짜가 없었기 때문이다(app/models/activity_category.py의
    period_start 주석 참고).
    """
    gap_period, categories = await _load_gap_and_categories(session, db)
    report = build_coverage_report(gap_period, categories)
    largest = report.largest_uncovered

    return CoverageRead(
        gap_start=report.gap_start,
        gap_end=report.gap_end,
        total_days=report.total_days,
        covered_days=report.covered_days,
        coverage_ratio=report.coverage_ratio,
        covered_ranges=[_range_read(r) for r in report.covered_ranges],
        uncovered_ranges=[_range_read(r) for r in report.uncovered_ranges],
        categories_without_period=report.categories_without_period,
        suggested_probe_question=probe_question_for(largest) if largest else None,
    )


@router.patch("/{session_id}/categories/{category_id}/period", status_code=status.HTTP_204_NO_CONTENT)
async def set_category_period(
    category_id: uuid.UUID,
    payload: CategoryPeriodUpdate,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
):
    """활동 기간을 사용자가 직접 정정한다.

    period_source가 "user_set"으로 바뀌면 이후 인터뷰 턴에서 LLM 추정이 이
    값을 덮어쓰지 않는다(app/api/interview.py의 _maybe_infer_category_period).

    No `-> None` annotation — 204 응답 본문 assertion 때문(sessions.delete_session 주석 참고).
    """
    if payload.end_date < payload.start_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_date_order")

    category = await db.get(ActivityCategory, category_id)
    if category is None or category.session_id != session.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="category_not_found")

    category.period_start = payload.start_date
    category.period_end = payload.end_date
    category.period_source = "user_set"
    await db.commit()


@router.post("/{session_id}/coverage/fill", response_model=CoverageFillRead, status_code=status.HTTP_201_CREATED)
async def fill_uncovered_range(
    payload: CoverageFillRequest,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
) -> CoverageFillRead:
    """빈 구간 하나를 인터뷰 대상으로 올린다.

    그 구간 전용 카테고리("2025년 3월~6월")를 만들고 세션의 현재 카테고리를
    거기로 옮긴다 — 이후 질문은 평범한 other 카테고리와 똑같이 질문 은행에서
    나온다. 사용자가 명시적으로 호출해야만 생기므로 인터뷰가 스스로 빈 구간을
    무한정 만들어내는 일은 없다.

    기간은 사용자가 지목한 구간 그대로이므로 period_source="user_set"이고,
    activity_split_checked=True로 만들어 소분류 질문을 건너뛴다 — 애초에 하나의
    시간 구간을 가리키는 카테고리라 쪼갤 것이 없다.
    """
    if session.status not in _FILL_ALLOWED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"coverage fill requires one of {_FILL_ALLOWED_STATUSES}, got '{session.status}'",
        )
    if payload.end_date < payload.start_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_date_order")

    gap_period, categories = await _load_gap_and_categories(session, db)
    requested = DateRange(payload.start_date, payload.end_date)
    if requested.start < gap_period.start_date or requested.end > gap_period.end_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="range_outside_gap_period")

    report = build_coverage_report(gap_period, categories)
    overlaps_uncovered = any(
        requested.start <= r.end and r.start <= requested.end for r in report.uncovered_ranges
    )
    if not overlaps_uncovered:
        # 이미 설명된 구간을 다시 카테고리로 만들면 커버리지가 중복 계산되지는
        # 않지만(merge_ranges가 합친다) 사용자에게는 같은 얘기를 두 번 묻는 셈이 된다.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="range_already_covered")

    label = label_for_range(requested)
    new_category = ActivityCategory(
        session_id=session.id,
        category_type="other",
        custom_label=label,
        order_index=max((c.order_index for c in categories), default=-1) + 1,
        activity_split_checked=True,
        period_start=requested.start,
        period_end=requested.end,
        period_source="user_set",
    )
    db.add(new_category)
    await db.flush()

    session.status = "INTERVIEWING"
    session.current_category_id = new_category.id
    # 다른 카테고리의 미완료 턴이 남아 있으면 새 카테고리 질문과 충돌한다
    # (interview_ask의 pending 재사용 분기가 category_id로 판단하므로 조용히
    # 버려지긴 하지만, 명시적으로 비워두는 편이 상태를 읽기 쉽다).
    session.pending_turn = None
    await db.commit()

    return CoverageFillRead(status=session.status, category_id=new_category.id, category_label=label)
