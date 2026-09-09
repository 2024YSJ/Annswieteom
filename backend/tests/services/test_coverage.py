from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from app.services.llm.base import clamp_activity_period
from app.services.coverage import (
    DateRange,
    has_period_clue,
    build_coverage_report,
    invert_ranges,
    merge_ranges,
    probe_question_for,
)


@dataclass
class FakeGapPeriod:
    start_date: date
    end_date: date


@dataclass
class FakeCategory:
    """ActivityCategory 중 build_coverage_report가 실제로 읽는 필드만."""

    period_start: date | None = None
    period_end: date | None = None
    parent_category_id: uuid.UUID | None = None
    id: uuid.UUID = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.id is None:
            self.id = uuid.uuid4()


def _gap(start="2025-01-01", end="2025-12-31") -> FakeGapPeriod:
    return FakeGapPeriod(date.fromisoformat(start), date.fromisoformat(end))


def _cat(start=None, end=None, **kwargs) -> FakeCategory:
    return FakeCategory(
        period_start=date.fromisoformat(start) if start else None,
        period_end=date.fromisoformat(end) if end else None,
        **kwargs,
    )


def test_merge_ranges_combines_overlapping_and_adjacent():
    merged = merge_ranges([
        DateRange(date(2025, 1, 1), date(2025, 3, 31)),
        DateRange(date(2025, 3, 1), date(2025, 4, 30)),   # overlaps
        DateRange(date(2025, 5, 1), date(2025, 5, 31)),   # adjacent (4/30 + 1일)
        DateRange(date(2025, 8, 1), date(2025, 8, 31)),   # separate
    ])
    assert merged == [
        DateRange(date(2025, 1, 1), date(2025, 5, 31)),
        DateRange(date(2025, 8, 1), date(2025, 8, 31)),
    ]


def test_merge_ranges_does_not_double_count_concurrent_activities():
    """같은 기간에 두 활동을 병행했다고 커버리지가 두 배가 되면 안 된다."""
    same = DateRange(date(2025, 1, 1), date(2025, 6, 30))
    merged = merge_ranges([same, same])
    assert sum(r.days for r in merged) == same.days


def test_invert_ranges_finds_the_holes():
    bounds = DateRange(date(2025, 1, 1), date(2025, 12, 31))
    covered = [
        DateRange(date(2025, 1, 1), date(2025, 2, 28)),
        DateRange(date(2025, 7, 1), date(2025, 8, 31)),
    ]
    assert invert_ranges(covered, bounds) == [
        DateRange(date(2025, 3, 1), date(2025, 6, 30)),
        DateRange(date(2025, 9, 1), date(2025, 12, 31)),
    ]


def test_invert_ranges_returns_whole_span_when_nothing_covered():
    bounds = DateRange(date(2025, 1, 1), date(2025, 3, 31))
    assert invert_ranges([], bounds) == [bounds]


def test_report_identifies_uncovered_span():
    report = build_coverage_report(
        _gap(),
        [_cat("2025-01-01", "2025-02-28"), _cat("2025-07-01", "2025-12-31")],
    )
    assert report.total_days == 365
    assert report.covered_days == 59 + 184
    assert [(r.start, r.end) for r in report.uncovered_ranges] == [
        (date(2025, 3, 1), date(2025, 6, 30))
    ]
    assert report.largest_uncovered.days == 122
    assert 0 < report.coverage_ratio < 1


def test_report_ignores_holes_shorter_than_the_reporting_floor():
    """며칠짜리 틈은 데이터 해상도 문제이지 설명이 필요한 공백이 아니다."""
    report = build_coverage_report(
        _gap("2025-01-01", "2025-03-31"),
        [_cat("2025-01-01", "2025-01-31"), _cat("2025-02-10", "2025-03-31")],
    )
    assert report.uncovered_ranges == []  # 2/1~2/9, 9일


def test_report_clamps_activity_periods_to_the_gap():
    report = build_coverage_report(
        _gap("2025-01-01", "2025-06-30"),
        [_cat("2024-06-01", "2025-12-31")],
    )
    assert report.covered_days == report.total_days
    assert report.coverage_ratio == 1.0


def test_report_treats_non_overlapping_period_as_unknown():
    """공백기와 전혀 겹치지 않는 기간이 저장돼 있으면 조용히 사라지는 대신
    '기간 미상'으로 드러나야 한다."""
    category = _cat("2020-01-01", "2020-12-31")
    report = build_coverage_report(_gap(), [category])
    assert report.covered_days == 0
    assert report.categories_without_period == [category.id]


def test_report_lists_categories_without_period():
    known = _cat("2025-01-01", "2025-06-30")
    unknown = _cat()
    report = build_coverage_report(_gap(), [known, unknown])
    assert report.categories_without_period == [unknown.id]


def test_report_skips_split_parent_containers():
    """자식으로 쪼개진 부모는 직접 인터뷰되지 않으므로 기간이 채워질 일이 없다 —
    '기간 미상'으로 세면 영원히 사라지지 않는 경고가 된다."""
    parent = _cat()
    child = _cat("2025-01-01", "2025-06-30", parent_category_id=parent.id)
    report = build_coverage_report(_gap(), [parent, child])
    assert report.categories_without_period == []
    assert report.covered_days == 181


def test_report_with_no_categories_is_entirely_uncovered():
    report = build_coverage_report(_gap(), [])
    assert report.covered_days == 0
    assert report.coverage_ratio == 0.0
    assert len(report.uncovered_ranges) == 1


def test_probe_question_names_the_missing_months():
    question = probe_question_for(DateRange(date(2025, 3, 1), date(2025, 6, 30)))
    assert "2025년 3월~6월" in question
    assert question.endswith("?")


# ---------------------------------------------------------------------------
# 기간 단서 게이트 — 실 로컬 모델 검증에서 나온 방어(2026-09-09).
# qwen2.5:3b는 단서 없는 사실을 받으면 "모르겠다" 대신 공백 기간 전체를 그대로
# 베껴 돌려줬다. 그 답을 저장하면 커버리지가 100%가 되어 빈 구간이 사라진다.
# ---------------------------------------------------------------------------


def test_explicit_dates_count_as_a_clue():
    assert has_period_clue(["2025년 3월부터 8월까지 주 3회 근무했다"])


def test_duration_counts_as_a_clue():
    assert has_period_clue(["6개월 동안 매일 공부했다"])
    assert has_period_clue(["3주 정도 준비했다"])
    assert has_period_clue(["한 달 반 걸렸다", "2일 만에 끝냈다"])


def test_relative_expressions_count_as_a_clue():
    assert has_period_clue(["작년 하반기에 시작했다"])
    assert has_period_clue(["지난달부터 다시 했다"])


def test_frequency_alone_is_not_a_clue():
    """"주 3회"는 얼마나 자주인지만 말할 뿐 언제/얼마 동안인지를 말하지 않는다."""
    assert not has_period_clue(["주 3회 정도 팀원들과 모여서 진행했다"])


def test_time_of_day_and_daily_hours_are_not_clues():
    assert not has_period_clue(["저녁 6시부터 10시까지 일했다"])
    assert not has_period_clue(["매일 4시간씩 공부했다"])


def test_empty_and_none_safe():
    assert not has_period_clue([])
    assert not has_period_clue(["", None])


# ---------------------------------------------------------------------------
# clamp_activity_period — 커버리지를 지키기 위한 규칙이라 여기서 함께 검증한다.
# ---------------------------------------------------------------------------


def test_clamp_trims_a_period_that_overhangs_the_gap():
    result = clamp_activity_period(
        date(2024, 6, 1), date(2025, 3, 31), date(2025, 1, 1), date(2025, 12, 31)
    )
    assert (result.start_date, result.end_date) == (date(2025, 1, 1), date(2025, 3, 31))


def test_clamp_discards_a_period_that_does_not_overlap_the_gap():
    assert clamp_activity_period(
        date(2020, 1, 1), date(2020, 12, 31), date(2025, 1, 1), date(2025, 12, 31)
    ) is None


def test_clamp_discards_a_reversed_period():
    assert clamp_activity_period(
        date(2025, 8, 1), date(2025, 3, 1), date(2025, 1, 1), date(2025, 12, 31)
    ) is None


def test_clamp_discards_a_period_identical_to_the_whole_gap():
    """실 로컬 모델이 단서 없는 입력에 대해 되뱉는 값이 정확히 이것이다 —
    관찰이 아니라 입력 반사이므로 버린다. 과소 보고(질문 한 번 더)가
    과대 보고(빈 구간 은폐)보다 싸다."""
    assert clamp_activity_period(
        date(2025, 1, 1), date(2025, 12, 31), date(2025, 1, 1), date(2025, 12, 31)
    ) is None


def test_clamp_keeps_a_period_one_day_short_of_the_whole_gap():
    """전체와 '정확히' 같을 때만 버린다 — 실제로 거의 전 기간을 채운 활동까지
    싸잡아 버리지는 않는다."""
    result = clamp_activity_period(
        date(2025, 1, 1), date(2025, 12, 30), date(2025, 1, 1), date(2025, 12, 31)
    )
    assert result is not None
    assert result.end_date == date(2025, 12, 30)
