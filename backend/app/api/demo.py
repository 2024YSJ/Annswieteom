from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.schemas.document import DocumentRead
from app.services.document_assembly import build_document_read, get_latest_document
from app.services.record_pipeline.citation import get_fact_citations

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("/document", response_model=DocumentRead)
async def get_demo_document(
    db: AsyncSession = Depends(get_db),
    fact_citations=Depends(get_fact_citations),
) -> DocumentRead:
    """로그인 없이 볼 수 있는, 실제로 확정된 결과물 하나 — health.py처럼 완전 무인증이다.

    `settings.demo_session_id`로 지정된 세션 딱 하나만 노출한다. **경로 파라미터로
    session_id를 받지 않는 것이 핵심 설계 포인트다** — 그래야 클라이언트가 임의의
    UUID를 넣어 다른 사용자의 세션을 훔쳐볼 길 자체가 없다.
    """
    if not settings.demo_session_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="demo_not_configured")

    try:
        session_id = uuid.UUID(settings.demo_session_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="demo_not_configured")

    document = await get_latest_document(session_id, db)
    if document is None or document.status != "FINAL":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="demo_document_not_found")

    return await build_document_read(document, db, fact_citations)
