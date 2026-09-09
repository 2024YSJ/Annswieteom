from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.models.activity_category import ActivityCategory
from app.models.gap_period import GapPeriod

# 확정된 사실에 기간을 알 만한 단서가 있는지 판별하는 값싼 게이트.
#
# 왜 코드로 거르는가(2026-09-09, 실 로컬 모델 검증 결과): qwen2.5:3b는 날짜가
# 적혀 있으면 잘 뽑아내지만 **"모르겠다"고 답하지 못한다.** 단서가 전혀 없는
# 사실을 주면 3/3으로 공백 기간 전체를 그대로 베껴 돌려줬다 — 프롬프트에 "베껴
# 쓰지 말라"고 명시해도 그랬다. 그 답을 그대로 저장하면 커버리지가 100%가 되어
# 빈 구간이 하나도 안 보이고, 커버리지 기능 전체가 조용히 무의미해진다.
# 판단은 모델에게 맡기고 추출만 시키는 대신, 판단을 여기로 가져왔다.
#
# 숫자+기간 단위만 단서로 친다. "주 3회"(빈도), "저녁 6시부터"(시각),
# "매일 4시간씩"(하루 분량)은 활동이 언제/얼마나 이어졌는지를 말해주지 않으므로
# 일부러 제외한다 — 회/시/시간은 목록에 없다.
_PERIOD_CLUE_PATTERN = re.compile(
    r"\d\s*(년|개월|달|월|주일|주|일)"
    r"|작년|재작년|올해|지난해|지난달|이번\s*달|상반기|하반기"
)


def has_period_clue(texts: Iterable[str]) -> bool:
    return any(_PERIOD_CLUE_PATTERN.search(text or "") for text in texts)

# 이보다 짧은 빈 구간은 보고하지 않는다. 활동 기간은 대부분 월 단위 단서에서
# 유추되므로(activity_period.jinja가 "월 단위면 1일~말일"로 맞춘다) 며칠짜리
# 틈은 데이터의 해상도 문제이지 실제 공백이 아니다. 이력서에서 설명을 요구받는
# 최소 단위가 대략 한 달이라는 점도 같은 값을 가리킨다.
MIN_REPORTABLE_GAP_DAYS = 30


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


@dataclass
class CoverageReport:
    gap_start: date
    gap_end: date
    total_days: int
    covered_days: int
    covered_ranges: list[DateRange] = field(default_factory=list)
    uncovered_ranges: list[DateRange] = field(default_factory=list)
    # 기간을 아직 모르는 카테고리 — 커버리지 계산에서 통째로 빠져 있으므로,
    # 이게 비어 있지 않으면 coverage_ratio는 하한선으로만 읽어야 한다.
    categories_without_period: list[uuid.UUID] = field(default_factory=list)

    @property
    def coverage_ratio(self) -> float:
        return self.covered_days / self.total_days if self.total_days else 0.0

    @property
    def largest_uncovered(self) -> DateRange | None:
        return max(self.uncovered_ranges, key=lambda r: r.days, default=None)


def merge_ranges(ranges: list[DateRange]) -> list[DateRange]:
    """겹치거나 맞닿은 구간을 합친다. 두 활동을 병행한 기간을 두 번 세지 않기
    위한 것 — 이게 없으면 covered_days가 공백기 전체 길이를 넘을 수 있다.
    """
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda r: (r.start, r.end))
    merged = [ordered[0]]
    for current in ordered[1:]:
        last = merged[-1]
        # 하루 차이로 붙어 있는 구간(3월 31일 종료 + 4월 1일 시작)도 하나로 본다.
        if current.start <= last.end + timedelta(days=1):
            if current.end > last.end:
                merged[-1] = DateRange(last.start, current.end)
        else:
            merged.append(current)
    return merged


def invert_ranges(covered: list[DateRange], bounds: DateRange) -> list[DateRange]:
    """`bounds` 안에서 `covered`(정렬·병합된 상태여야 함)가 덮지 않은 구간."""
    gaps: list[DateRange] = []
    cursor = bounds.start
    for r in covered:
        if r.start > cursor:
            gaps.append(DateRange(cursor, r.start - timedelta(days=1)))
        cursor = max(cursor, r.end + timedelta(days=1))
        if cursor > bounds.end:
            break
    if cursor <= bounds.end:
        gaps.append(DateRange(cursor, bounds.end))
    return gaps


def build_coverage_report(
    gap_period: GapPeriod,
    categories: list[ActivityCategory],
    min_reportable_gap_days: int = MIN_REPORTABLE_GAP_DAYS,
) -> CoverageReport:
    """공백기 중 실제로 설명된 구간과 아직 비어 있는 구간을 계산한다.

    이 함수가 "안 쉬었음"이 채팅창과 갈리는 지점이다. 대화형 LLM은 자기가 무엇을
    아직 안 물었는지 추적하지 못한다 — 사용자가 3월~6월 이야기를 꺼내지 않으면
    그 구간은 그냥 대화에 등장하지 않고 끝난다. 여기서는 공백기가 날짜 구간이고
    활동도 날짜 구간이므로, 덮이지 않은 부분을 뺄셈으로 정확히 지목할 수 있다.

    소분류(parent_category_id가 있는 카테고리)는 부모 자리에서 실제로 인터뷰되는
    단위이므로 그대로 센다. 자식이 있는 부모(컨테이너)는 직접 인터뷰되지 않아
    기간이 채워질 일이 없으니 categories_without_period에서 제외한다.
    """
    bounds = DateRange(gap_period.start_date, gap_period.end_date)

    parent_ids = {c.parent_category_id for c in categories if c.parent_category_id is not None}
    interviewed = [c for c in categories if c.id not in parent_ids]

    raw_ranges: list[DateRange] = []
    without_period: list[uuid.UUID] = []
    for category in interviewed:
        if category.period_start is None or category.period_end is None:
            without_period.append(category.id)
            continue
        start = max(category.period_start, bounds.start)
        end = min(category.period_end, bounds.end)
        if start <= end:
            raw_ranges.append(DateRange(start, end))
        else:
            # 공백기와 전혀 겹치지 않는 기간이 저장돼 있으면 "기간 미상"과 같게
            # 취급한다 — 커버리지에 기여하지 않으면서 조용히 사라지면 안 된다.
            without_period.append(category.id)

    covered = merge_ranges(raw_ranges)
    uncovered = [r for r in invert_ranges(covered, bounds) if r.days >= min_reportable_gap_days]

    return CoverageReport(
        gap_start=bounds.start,
        gap_end=bounds.end,
        total_days=bounds.days,
        covered_days=sum(r.days for r in covered),
        covered_ranges=covered,
        uncovered_ranges=uncovered,
        categories_without_period=without_period,
    )


def _format_range(r: DateRange) -> str:
    if r.start.year == r.end.year:
        return f"{r.start.year}년 {r.start.month}월~{r.end.month}월"
    return f"{r.start.year}년 {r.start.month}월~{r.end.year}년 {r.end.month}월"


def probe_question_for(r: DateRange) -> str:
    """빈 구간 하나를 두고 시스템이 먼저 던지는 질문.

    질문 은행(interview_question_bank.py)의 고정 질문들과 달리 이건 사용자가
    말하지 않은 것에서 출발한다 — 무엇이 빠졌는지 계산할 수 있어야만 만들 수
    있는 질문이다.
    """
    return f"{_format_range(r)}은 아직 이야기가 없는데, 이 시기에는 어떻게 지내셨나요?"


def label_for_range(r: DateRange) -> str:
    """빈 구간을 메우려고 만드는 카테고리에 붙일 이름."""
    return _format_range(r)
