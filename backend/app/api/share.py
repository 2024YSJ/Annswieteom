from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.confirmed_fact import ConfirmedFact
from app.models.generated_document import GeneratedDocument
from app.models.generated_sentence import GeneratedSentence
from app.schemas.share import SharePreviewRead
from app.services.evidence import grade_for
from app.services.share_preview import SentenceForPreview, evidence_grade_summary, select_representative_sentences

router = APIRouter(prefix="/share", tags=["share"])


async def _evidence_grade(sentence: GeneratedSentence, db: AsyncSession) -> str:
    """문장 근거의 등급만 계산한다 — 근거 fact의 content나 citation은 조회하지
    않는다(build_sentence_read와 갈라지는 지점). 공개 라우트가 노출할 값이
    등급 하나뿐이라, 애초에 노출하지 않을 데이터를 메모리에 올릴 이유가 없다.
    """
    if not sentence.evidence_fact_ids:
        return "unsupported"
    fact_ids = [uuid.UUID(fid) for fid in sentence.evidence_fact_ids]
    stmt = select(ConfirmedFact.source_type).where(ConfirmedFact.id.in_(fact_ids))
    source_types = (await db.execute(stmt)).scalars().all()
    return grade_for(source_types)


@router.get("/{slug}", response_model=SharePreviewRead)
async def get_share_preview(slug: str, db: AsyncSession = Depends(get_db)) -> SharePreviewRead:
    """완전 무인증 공개 라우트 — health.py/demo.py와 같은 패턴.

    session_id/user_id/근거 원문을 응답에 절대 담지 않는다(SharePreviewRead
    자체가 그 세 필드를 가질 수 없는 스키마다).
    """
    stmt = select(GeneratedDocument).where(GeneratedDocument.share_slug == slug)
    document = (await db.execute(stmt)).scalar_one_or_none()
    if document is None or document.status != "FINAL":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="share_not_found")

    sent_stmt = select(GeneratedSentence).where(GeneratedSentence.document_id == document.id)
    sentences = list((await db.execute(sent_stmt)).scalars().all())

    previews = [
        SentenceForPreview(text=s.text, evidence_grade=await _evidence_grade(s, db), order_index=s.order_index)
        for s in sentences
    ]

    return SharePreviewRead(
        tone=document.tone,
        representative_sentences=select_representative_sentences(previews),
        evidence_grade_summary=evidence_grade_summary(previews),
    )
