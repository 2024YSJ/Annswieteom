from __future__ import annotations

from app.services.llm.language_guard import contains_cjk


def test_contains_cjk_detects_hanzi():
    assert contains_cjk("봉사活动中에 활용했어요") is True
    assert contains_cjk("您对") is True


def test_contains_cjk_allows_pure_korean():
    # 한글(Hangul Syllables, U+AC00~D7A3)은 CJK Unified Ideographs 범위 밖이다.
    assert contains_cjk("카페에서 아르바이트를 했어요") is False


def test_contains_cjk_allows_ascii_english():
    assert contains_cjk("JPA와 Spring Boot를 배웠어요") is False


def test_contains_cjk_handles_none_and_empty():
    assert contains_cjk(None) is False
    assert contains_cjk("") is False
