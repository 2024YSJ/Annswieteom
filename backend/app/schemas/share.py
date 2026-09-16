from __future__ import annotations

from pydantic import BaseModel


class ShareLinkRead(BaseModel):
    share_slug: str


class SharePreviewRead(BaseModel):
    """공개 공유 페이지가 받는 전부 — 의도적으로 이게 전부다.

    session_id/user_id/근거 원문(citation.source_url, ConfirmedFact.content)은
    절대 여기 없다. 공유 카드는 "이 서비스가 근거 있는 문서를 만든다"는 걸
    보여주는 용도지, 사용자의 실제 이력서 전문이나 개인 블로그 주소를
    퍼뜨리는 용도가 아니다.
    """

    tone: str
    representative_sentences: list[str]
    evidence_grade_summary: dict[str, int]
