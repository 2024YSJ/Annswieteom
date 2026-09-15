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


def test_pet_groomer_group_covers_the_real_certificate_name():
    # 2026-09-15 재검증: "반려동물미용사"로 검색하면 0건이었는데 실제 과정은
    # "애견미용사"로만 등록돼 있었다 — 직역과 실제 명칭이 다른 경우.
    result = expand_occupation_keyword("반려동물미용사", limit=4)

    assert "애견미용사" in result


def test_kindergarten_teacher_group_covers_the_real_certificate_name():
    # 같은 라운드에서 발견: "유치원교사"는 0건, 실제 과정은 "보육교사"로 등록.
    result = expand_occupation_keyword("유치원교사", limit=4)

    assert "보육교사" in result


def test_kindergarten_teacher_group_is_reachable_from_just_the_word_유치원():
    # 재배포 후에도 여전히 0건이었다 — 추출 프롬프트가 "교사"를 빼고 "유치원"만
    # 뽑은 것으로 보인다(exact-match라 한 글자만 달라도 못 찾는다). "유치원"도
    # 같은 그룹에 넣어 표제어 표기가 흔들려도 걸리게 했다.
    result = expand_occupation_keyword("유치원", limit=4)

    assert "보육교사" in result
