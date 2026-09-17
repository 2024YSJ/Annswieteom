from __future__ import annotations

from dataclasses import dataclass

from app.services.evidence import EVIDENCE_GRADES

_GRADE_PRIORITY = {"record_backed": 0, "self_reported": 1, "unsupported": 2}


@dataclass
class SentenceForPreview:
    text: str
    evidence_grade: str
    order_index: int


def select_representative_sentences(sentences: list[SentenceForPreview], limit: int = 2) -> list[str]:
    """공유 카드에 실을 대표 문장 1~2개 — record_backed 등급을 우선하고,
    동률이면 order_index가 빠른 것부터. unsupported(근거 없음) 문장은 애초에
    대표작 자격이 없다 — 공유 카드는 이 서비스의 강점(근거 기반 생성)을
    보여주는 용도이므로, 정직성 가드레일이 잡아낸 예외 케이스를 굳이
    앞세우지 않는다(문서 본문 화면에서는 여전히 그대로 드러난다).
    """
    candidates = [s for s in sentences if s.evidence_grade != "unsupported"]
    ranked = sorted(candidates, key=lambda s: (_GRADE_PRIORITY.get(s.evidence_grade, 9), s.order_index))
    return [s.text for s in ranked[:limit]]


def evidence_grade_summary(sentences: list[SentenceForPreview]) -> dict[str, int]:
    summary = {grade: 0 for grade in EVIDENCE_GRADES}
    for s in sentences:
        summary[s.evidence_grade] = summary.get(s.evidence_grade, 0) + 1
    return summary
