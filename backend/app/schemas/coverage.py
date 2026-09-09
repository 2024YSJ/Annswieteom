from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel


class DateRangeRead(BaseModel):
    start: date
    end: date
    days: int


class CoverageRead(BaseModel):
    """`GET /sessions/{id}/coverage` — 공백기 중 설명된 구간과 남은 구간.

    `coverage_ratio`는 기간을 아는 카테고리만으로 계산한 **하한선**이다 —
    `categories_without_period`가 비어 있지 않으면 실제 커버리지는 이보다 높다.
    """

    gap_start: date
    gap_end: date
    total_days: int
    covered_days: int
    coverage_ratio: float
    covered_ranges: list[DateRangeRead]
    uncovered_ranges: list[DateRangeRead]
    categories_without_period: list[uuid.UUID]
    # 가장 큰 빈 구간에 대해 시스템이 먼저 던질 수 있는 질문. 빈 구간이 없으면 None.
    suggested_probe_question: str | None


class CategoryPeriodUpdate(BaseModel):
    start_date: date
    end_date: date


class CoverageFillRequest(BaseModel):
    start_date: date
    end_date: date


class CoverageFillRead(BaseModel):
    status: str
    category_id: uuid.UUID
    category_label: str
