from __future__ import annotations

from pydantic import BaseModel


class TrustScoreRead(BaseModel):
    """정직성 가드레일 지표. 각 ratio는 분모가 0이면 null(측정 불가 — "0%"와
    구분해야 한다: 문서가 아직 없는 것과 문서가 있는데 근거가 0%인 것은 다르다).
    """

    total_sentences: int
    evidence_coverage_ratio: float | None
    consistency_pass_rate: float | None
    ai_acceptance_rate: float | None
    interview_ai_acceptance_rate: float | None
    machine_checked_sentences: int
    user_edited_sentences: int
