from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.record import Record
from app.models.record_chunk import RecordChunk


@dataclass
class RecordChunkExcerpt:
    chunk_id: uuid.UUID
    text: str
    published_at: date | None


async def search_relevant_chunks(
    session_id: uuid.UUID,
    category_id: uuid.UUID,
    top_k: int = 5,
) -> list[RecordChunkExcerpt]:
    """Return chunks from records the user attached to this specific category.

    Records now carry a direct category_id (set from session.current_category_id
    at creation time — see app/api/records.py), so this is a plain filter rather
    than the label-embedding similarity search it used to be; that similarity
    match was never reliable in practice (always fell back to generic_pattern,
    per docs/checklists/person_B_frontend_backend/03_records_feature.md).
    """
    async with AsyncSessionLocal() as db:
        # Subquery: record IDs belonging to this session AND this category
        record_ids_subq = (
            select(Record.id)
            .where(Record.session_id == session_id, Record.category_id == category_id)
            .scalar_subquery()
        )

        stmt = (
            select(RecordChunk)
            .where(RecordChunk.record_id.in_(record_ids_subq))
            .order_by(RecordChunk.created_at)
            .limit(top_k)
        )
        result = await db.execute(stmt)
        chunks = result.scalars().all()

    return [
        RecordChunkExcerpt(
            chunk_id=c.id,
            text=c.chunk_text,
            published_at=c.published_at,
        )
        for c in chunks
    ]


def get_chunk_search():
    """FastAPI DI hook wrapping search_relevant_chunks.

    search_relevant_chunks opens its own DB session directly (not through
    get_db), so overriding the get_db dependency alone can't swap it out in
    tests — routes should depend on this instead of importing the function
    directly, so `app.dependency_overrides[get_chunk_search] = ...` works.
    """
    return search_relevant_chunks
