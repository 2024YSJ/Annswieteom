from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_owned_session
from app.db.session import get_db
from app.models.session import Session as SessionModel
from app.schemas.trust import TrustScoreRead
from app.services.document_assembly import get_latest_document
from app.services.trust_score import TrustStats, compute_document_trust, compute_global_trust

# 세션 단위(소유자 인증 필요)와 전역(무인증) 두 라우터로 나눈다 — 전역 지표는
# health.py의 /health/llm과 같은 이유로 인증을 걸지 않는다: 심사위원/투표자가
# 로그인 없이 확인할 수 있어야 하고, 노출되는 값은 비율·개수뿐이라 개인정보가 아니다.
session_router = APIRouter(prefix="/sessions", tags=["trust"])
global_router = APIRouter(prefix="/trust-score", tags=["trust"])


def _to_read(stats: TrustStats) -> TrustScoreRead:
    return TrustScoreRead(
        total_sentences=stats.total_sentences,
        evidence_coverage_ratio=stats.evidence_coverage_ratio,
        consistency_pass_rate=stats.consistency_pass_rate,
        ai_acceptance_rate=stats.ai_acceptance_rate,
        interview_ai_acceptance_rate=stats.interview_ai_acceptance_rate,
        machine_checked_sentences=stats.machine_checked_sentences,
        user_edited_sentences=stats.user_edited_sentences,
    )


@session_router.get("/{session_id}/trust-score", response_model=TrustScoreRead)
async def get_session_trust_score(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
) -> TrustScoreRead:
    """이 세션의 최신 문서가 정직성 가드레일을 얼마나 지켰는지 숫자로 보여준다."""
    document = await get_latest_document(session.id, db)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")
    return _to_read(await compute_document_trust(document.id, db))


@global_router.get("/global", response_model=TrustScoreRead)
async def get_global_trust_score(db: AsyncSession = Depends(get_db)) -> TrustScoreRead:
    """확정(FINAL)된 문서 전체를 대상으로 한 발표용 지표. 완전 무인증."""
    return _to_read(await compute_global_trust(db))
