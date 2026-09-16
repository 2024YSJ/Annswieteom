"""LLM 출력에 섞인 중국어 한자를 감지한다.

인터뷰 관련 로컬 모델(qwen 계열)이 이따금 한국어 응답에 중국어 단어/문자를
섞어 낸다 — 2026-09-03(qwen2.5:14b, devlog 08)과 2026-09-15/16(qwen3.5:35b-a3b,
devlog 54)에 서로 다른 모델로 두 번 재현됐다. `confirmed_facts.content`는
정직성 가드레일이 보호하는, 생성 문서에 그대로 들어갈 수 있는 데이터라
오염된 텍스트가 저장 전에 걸러져야 한다(devlog 54 — `consistency_check`는
문서 생성 시점의 의미 유사도만 보므로 이 실패 모드를 못 잡는다).
"""
from __future__ import annotations

import re

_CJK_PATTERN = re.compile(r"[一-鿿]")


def contains_cjk(text: str | None) -> bool:
    """CJK Unified Ideographs(한자) 존재 여부.

    정당한 한자(회사명 등)가 드물게 이 범위에 걸릴 위험은 있지만, 이 앱의
    캐주얼한 인터뷰 답변 맥락에서 한자가 실제로 필요한 경우는 극히 드문
    반면, confirmed_facts에 오염된 텍스트가 그대로 들어가는 정직성 가드레일
    비용이 훨씬 크므로 이 트레이드오프를 받아들인다.
    """
    return bool(_CJK_PATTERN.search(text or ""))
