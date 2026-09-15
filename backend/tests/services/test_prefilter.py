"""job_pipeline/prefilter.py — devlog 52.

서버 직무 필터가 없는 4개 카테고리(public_recruitment 등)의 넓힌 원본
후보 풀을 LLM에 넘기기 전에 키워드/지역으로 미리 추리는 로직. 실제 관련성
판단은 항상 LLM이 하므로(devlog 18), 여기서는 "명백히 무관한 걸 빼는 예비
필터가 통과·폴백 조건을 정확히 지키는지"만 확인한다.
"""
from __future__ import annotations

from app.services.job_pipeline.job_info_client import JobInfoResult
from app.services.job_pipeline.prefilter import prefilter_candidates
from app.services.llm.base import JobInfoQueryParams


def _result(title: str, subtitle: str = "", meta_lines: list[str] | None = None) -> JobInfoResult:
    return JobInfoResult(title=title, subtitle=subtitle, meta_lines=meta_lines or [])


def test_no_query_params_passes_through_up_to_limit():
    raw = [_result(f"항목 {i}") for i in range(10)]

    result = prefilter_candidates(raw, None, limit=3)

    assert result == raw[:3]


def test_query_params_with_no_criteria_passes_through_unfiltered():
    # devlog 49의 "비교 기준 없음 → 전부 관련" 원칙과 같은 이유 — 필터를 걸
    # 근거 자체가 없다.
    raw = [_result(f"항목 {i}") for i in range(10)]
    params = JobInfoQueryParams(regions=[], keywords=[])

    result = prefilter_candidates(raw, params, limit=3)

    assert result == raw[:3]


def test_keyword_match_filters_to_relevant_items():
    raw = [
        _result("자바 백엔드 개발자 채용", "한국소프트웨어"),
        _result("조리기능사 자격증반", "국민내일배움카드"),
        _result("피부미용 국가자격 대비반", "국민내일배움카드"),
        _result("서버 개발 부트캠프", "국민내일배움카드"),
        _result("네일아트 기초반", "국민내일배움카드"),
        _result("클라우드 백엔드 심화", "국민내일배움카드"),
    ]
    params = JobInfoQueryParams(regions=[], keywords=["백엔드 개발자"])

    # 동의어 확장(occupation_synonyms: "백엔드 개발자" -> "백엔드", "서버 개발")
    # 까지 반영돼 "서버 개발 부트캠프"도 통과해야 한다.
    result = prefilter_candidates(raw, params, limit=10)

    titles = {r.title for r in result}
    assert titles == {"자바 백엔드 개발자 채용", "서버 개발 부트캠프", "클라우드 백엔드 심화"}


def test_region_match_filters_using_meta_lines():
    raw = [
        _result("강소기업 A", meta_lines=["지역: 경기 고양시"]),
        _result("강소기업 B", meta_lines=["지역: 부산 해운대구"]),
        _result("강소기업 C", meta_lines=["지역: 경기 성남시"]),
        _result("강소기업 D", meta_lines=["지역: 강원 원주시"]),
        _result("강소기업 E", meta_lines=["지역: 경기 수원시"]),
        _result("강소기업 F", meta_lines=["지역: 대구 수성구"]),
    ]
    params = JobInfoQueryParams(regions=["경기"], keywords=[])

    result = prefilter_candidates(raw, params, limit=10)

    titles = {r.title for r in result}
    assert titles == {"강소기업 A", "강소기업 C", "강소기업 E"}


def test_keyword_or_region_match_is_enough_not_both():
    # 최종 "지역·직무를 동시에 만족해야 한다" 판단은 LLM이 한다(devlog 45) —
    # 1차 필터는 재현율을 지키기 위해 둘 중 하나만 맞아도 통과시킨다.
    raw = [
        _result("전기기사 기초", meta_lines=["부산 사상구"]),  # 키워드만 일치
        _result("조리기능사 과정", meta_lines=["서울 강서구"]),  # 지역만 일치
        _result("네일아트 기초", meta_lines=["대구 수성구"]),  # 둘 다 불일치
        _result("전기(산업)기사 실기", meta_lines=["서울 강남구"]),  # 둘 다 일치
        _result("전기공사 실무", meta_lines=["인천 남동구"]),  # 키워드만 일치
    ]
    params = JobInfoQueryParams(regions=["서울"], keywords=["전기기사"])

    result = prefilter_candidates(raw, params, limit=10)

    titles = {r.title for r in result}
    assert titles == {"전기기사 기초", "조리기능사 과정", "전기(산업)기사 실기", "전기공사 실무"}
    assert "네일아트 기초" not in titles


def test_falls_back_to_unfiltered_pool_when_there_are_zero_matches():
    # public_recruitment/public_recruitment_company처럼 응답에 지역 정보
    # 자체가 없는 카테고리(devlog 52)에서 지역 조건을 걸면 항상 여기로 빠진다
    # — 필터가 이 데이터엔 안 맞을 때 진짜 있는 결과를 지워버리는 것을 막는
    # 안전망이다.
    raw = [_result(f"채용공고 {i}", "어떤회사") for i in range(10)]
    params = JobInfoQueryParams(regions=["서울"], keywords=[])

    result = prefilter_candidates(raw, params, limit=5)

    assert result == raw[:5]


def test_matched_results_are_still_capped_at_limit():
    raw = [_result(f"백엔드 개발자 채용 {i}") for i in range(20)]
    params = JobInfoQueryParams(regions=[], keywords=["백엔드 개발자"])

    result = prefilter_candidates(raw, params, limit=5)

    assert len(result) == 5
