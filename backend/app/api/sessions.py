from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, get_owned_session
from app.db.session import get_db
from app.models.activity_category import ActivityCategory
from app.models.session import Session as SessionModel
from app.models.user import User
from app.schemas.session import RecordChunkExcerptRead, SessionContextRead, SessionRead
from app.services.record_pipeline.search import get_chunk_search

router = APIRouter(prefix="/sessions", tags=["sessions"])


def category_label(category: ActivityCategory) -> str:
    return category.custom_label or category.category_type


@router.post("", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionModel:
    session = SessionModel(user_id=current_user.id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/{session_id}", response_model=SessionContextRead)
async def get_session(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    chunk_search=Depends(get_chunk_search),
) -> SessionContextRead:
    stmt = (
        select(SessionModel)
        .where(SessionModel.id == session.id)
        .options(
            selectinload(SessionModel.gap_period),
            selectinload(SessionModel.categories).selectinload(ActivityCategory.confirmed_facts),
        )
    )
    full_session = (await db.execute(stmt)).scalar_one()

    current_category = next(
        (c for c in full_session.categories if c.id == full_session.current_category_id),
        None,
    )

    available_record_chunks: list[RecordChunkExcerptRead] = []
    if current_category is not None:
        try:
            excerpts = await chunk_search(full_session.id, category_label(current_category))
        except Exception:
            # 임베딩/LLM 인프라가 잠깐 죽어도 세션 컨텍스트 조회 자체는 막지 않는다 —
            # available_record_chunks는 참고 정보일 뿐 상태머신 전이에 필요하지 않다.
            excerpts = []
        available_record_chunks = [
            RecordChunkExcerptRead(chunk_id=e.chunk_id, text=e.text, published_at=e.published_at)
            for e in excerpts
        ]

    return SessionContextRead(
        session_id=full_session.id,
        status=full_session.status,
        gap_period=full_session.gap_period,
        categories=full_session.categories,
        current_category=current_category,
        confirmed_facts=[fact for c in full_session.categories for fact in c.confirmed_facts],
        available_record_chunks=available_record_chunks,
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
) -> None:
    await db.delete(session)
    await db.commit()
