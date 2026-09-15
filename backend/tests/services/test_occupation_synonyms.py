from __future__ import annotations

from app.services.job_pipeline.occupation_synonyms import expand_occupation_keyword


def test_canonical_keyword_expands_to_its_synonym_group():
    result = expand_occupation_keyword("용접공", limit=3)

    assert result[0] == "용접공"
    assert set(result) == {"용접공", "용접", "용접기능사"}


def test_unmapped_keyword_passes_through_unchanged():
    assert expand_occupation_keyword("듣도보도못한직업명", limit=3) == ["듣도보도못한직업명"]


def test_looking_up_a_synonym_value_resolves_to_the_same_group():
    # "용접"은 표제어가 아니라 동의어 값이지만, 조회하면 같은 그룹이 나와야
    # 한다(역인덱스) — 자기 자신이 맨 앞에 온다.
    result = expand_occupation_keyword("용접", limit=3)

    assert result[0] == "용접"
    assert set(result) == {"용접공", "용접", "용접기능사"}


def test_limit_truncates_the_group():
    result = expand_occupation_keyword("영양사", limit=1)

    assert result == ["영양사"]
