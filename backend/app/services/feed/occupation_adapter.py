from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.user_occupation_embedding import UserOccupationEmbedding
from app.services.embedding import LocalOllamaEmbedding
from app.services.profile.attributes import load_match_profile

logger = logging.getLogger(__name__)

# ── 희망직무 임베딩 어댑터 ───────────────────────────────────────────────────
#
# profile_adapter.py와 별도 파일인 이유: 그쪽은 interview_answers(커지는 문답
# 아카이브) + wish_text를 다루는, 지문/개수/시각 삼종 검사가 필요한 관심사다.
# 여기는 load_match_profile()이 주는 desired_job 한 줄(고정 문자열)만 다룬다 —
# 원본이 짧고 안 자라므로 저장된 source_text와 등가 비교만으로 충분하다.
# ──────────────────────────────────────────────────────────────────────────


async def load_occupation_vector(db: AsyncSession, user_id: uuid.UUID) -> list[float] | None:
    """저장된 희망직무 벡터. 없거나 못 읽으면 None(텍스트 매칭 폴백으로).

    load_profile_vector(profile_adapter.py)와 같은 계약 — pgvector 없는
    SQLite에서도 조용히 None.
    """
    try:
        row = await db.get(UserOccupationEmbedding, user_id)
    except Exception:
        await db.rollback()
        return None
    return row.embedding if row is not None and row.embedding is not None else None


async def occupation_needs_refresh(db: AsyncSession, user_id: uuid.UUID, desired_job: str | None) -> bool:
    """desired_job이 없으면 임베딩할 게 없다. 있으면 저장된 source_text와
    등가 비교 — UserProfileEmbedding처럼 지문/개수/시각을 쌓을 이유가 없다,
    원본이 한 줄짜리 고정 문자열이라서다."""
    desired_job = (desired_job or "").strip()
    if not desired_job:
        return False
    try:
        row = await db.get(UserOccupationEmbedding, user_id)
    except Exception:
        # profile_needs_refresh와 같은 이유로 "갱신 필요"로 본다 — 워커가
        # 실패에 관대해서 헛도는 예약은 싸고, 원인이 고쳐지면 저절로 복구된다.
        await db.rollback()
        return True
    if row is None or row.embedding is None:
        return True
    return row.source_text != desired_job


async def refresh_occupation_embedding(user_id: uuid.UUID) -> None:
    """백그라운드 워커. refresh_profile_embedding과 같은 모양 — 자기 세션을
    열고, 실패는 전부 삼켜서 다음 요청이 재시도하게 둔다.

    desired_job은 호출 시점 클로저 값이 아니라 여기서 다시 읽는다 — 백그라운드
    태스크가 실행될 때는 요청이 이미 끝났을 수 있어, 그 사이 사용자가 다시
    맞춤 정보를 고쳤다면 최신값을 임베딩해야 한다.
    """
    async with AsyncSessionLocal() as db:
        try:
            profile = await load_match_profile(db, user_id)
        except Exception:
            await db.rollback()
            logger.warning("feed: occupation profile unreadable for %s", user_id, exc_info=True)
            return

        desired_job = (profile.desired_job or "").strip()
        if not desired_job:
            return

        row = await db.get(UserOccupationEmbedding, user_id)
        if row is not None and row.source_text == desired_job and row.embedding is not None:
            return

        provider = LocalOllamaEmbedding()
        try:
            vectors = await provider.embed([desired_job])
        except Exception:
            logger.warning("feed: occupation embedding unavailable for %s", user_id, exc_info=True)
            return

        vector = vectors[0] if vectors else None
        if vector is None:
            return

        now = datetime.now(timezone.utc)
        if row is None:
            db.add(
                UserOccupationEmbedding(
                    user_id=user_id,
                    embedding=vector,
                    embedding_model=provider.model_name,
                    source_text=desired_job,
                    computed_at=now,
                )
            )
        else:
            row.embedding = vector
            row.embedding_model = provider.model_name
            row.source_text = desired_job
            row.computed_at = now
        try:
            await db.commit()
        except Exception:
            # user_occupation_embeddings가 없는 환경(SQLite 테스트)에서도
            # 조용히 넘어간다 — 이 함수는 부가 작업이지 요청 경로가 아니다.
            await db.rollback()


def get_occupation_embedder():
    """FastAPI DI 훅. refresh_occupation_embedding이 자기 세션을 열기 때문에
    get_db 오버라이드만으로는 테스트에서 못 바꾼다(get_profile_embedder와 같은 이유)."""
    return refresh_occupation_embedding


__all__ = [
    "get_occupation_embedder",
    "load_occupation_vector",
    "occupation_needs_refresh",
    "refresh_occupation_embedding",
]
