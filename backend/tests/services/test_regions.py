from __future__ import annotations

from app.services.job_pipeline.regions import (
    KNOWN_REGION_NAMES,
    RegionFilter,
    resolve_region_filters,
)


def test_region_group_collapses_to_one_wide_call_with_an_address_filter():
    # 시·군 코드 10개로 펼치면 훈련과정은 엔드포인트가 4개라 호출이 40회로
    # 폭발한다 — 광역 한 번으로 받고 주소로 걸러낸다.
    filters = resolve_region_filters(["경기 북부"], limit=3)

    assert len(filters) == 1
    assert filters[0].area1 == "41"
    assert filters[0].area2 is None
    assert filters[0].needs_address_filter
    assert filters[0].matches_address("경기 고양시 일산동구")
    assert filters[0].matches_address("경기 파주시")
    assert not filters[0].matches_address("경기 성남시 분당구")  # 남부는 제외


def test_specific_city_uses_the_precise_api_parameter_instead_of_filtering():
    filters = resolve_region_filters(["고양"], limit=3)

    assert filters == [RegionFilter(area1="41", area2="41280")]
    assert not filters[0].needs_address_filter
    # 파라미터로 이미 좁혀졌으니 주소는 전부 통과시킨다.
    assert filters[0].matches_address("경기 고양시 덕양구")


def test_city_name_with_a_suffix_still_resolves():
    assert resolve_region_filters(["고양시"], limit=3) == [RegionFilter(area1="41", area2="41280")]
    assert resolve_region_filters(["연천군"], limit=3) == [RegionFilter(area1="41", area2="41800")]


def test_wide_areas_use_the_codes_that_were_verified_against_the_api():
    # 강원/전북은 특별자치도 전환 후 코드가 바뀌었고, 구 코드(42/45)는 에러가
    # 아니라 조용한 0건을 돌려준다 — 실측으로 확인한 51/52만 쓴다.
    assert resolve_region_filters(["강원"], limit=3) == [RegionFilter(area1="51")]
    assert resolve_region_filters(["전북"], limit=3) == [RegionFilter(area1="52")]
    assert resolve_region_filters(["서울"], limit=3) == [RegionFilter(area1="11")]


def test_multiple_same_dimension_values_become_multiple_calls():
    # 같은 파라미터에 값을 여러 개 넣는 건 API가 지원하지 않는다(콤마는 0건,
    # 반복 파라미터는 첫 값만 적용) — 호출을 쪼개는 것만이 방법이다.
    filters = resolve_region_filters(["서울", "경기"], limit=3)

    assert filters == [RegionFilter(area1="11"), RegionFilter(area1="41")]


def test_metropolitan_area_expands_to_three_wide_areas():
    filters = resolve_region_filters(["수도권"], limit=5)

    assert [f.area1 for f in filters] == ["11", "41", "28"]


def test_unknown_region_names_are_skipped_rather_than_guessed():
    # 코드를 추측해 보내면 0건이 돌아와 "그 지역에 정보가 없다"로 잘못 보인다.
    assert resolve_region_filters(["평양", "아무데나"], limit=3) == []
    # 알아본 것만 남는다.
    assert resolve_region_filters(["평양", "부산"], limit=3) == [RegionFilter(area1="26")]


def test_duplicates_are_removed_and_the_limit_is_applied():
    filters = resolve_region_filters(["서울", "서울", "부산", "대구", "인천"], limit=2)

    assert filters == [RegionFilter(area1="11"), RegionFilter(area1="26")]


def test_known_region_names_cover_what_the_prompt_needs_to_offer():
    # 추출 프롬프트는 이 목록만 보여주고 그 안에서 고르게 한다 — 목록에 없으면
    # LLM이 올바른 지역명을 내놓아도 코드 변환에서 조용히 버려진다.
    for name in ("경기 북부", "수도권", "서울", "경기", "고양", "의정부"):
        assert name in KNOWN_REGION_NAMES
