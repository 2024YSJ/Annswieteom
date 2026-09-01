from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.confirmed_fact import ConfirmedFact
from app.models.record import Record
from app.models.record_chunk import RecordChunk


@dataclass
class Citation:
    source_url: str | None
    published_at: str | None  # ISO date string


async def resolve_fact_citation(fact_id: uuid.UUID) -> Citation | None:
    """Return the source URL and date for a confirmed fact backed by a record chunk.

    Returns None for user_confirmed / user_edited facts that have no record origin.
    Used by GET /sessions/{id}/document to populate citation metadata per sentence.
    """
    async with AsyncSessionLocal() as db:
        fact = await db.get(ConfirmedFact, fact_id)
        if fact is None or fact.source_record_chunk_id is None:
            return None

        stmt = (
            select(Record.source_url, RecordChunk.published_at)
            .join(RecordChunk, RecordChunk.record_id == Record.id)
            .where(RecordChunk.id == fact.source_record_chunk_id)
        )
        row = (await db.execute(stmt)).first()
        if row is None:
            return None

        source_url, published_at = row
        return Citation(
            source_url=source_url,
            published_at=published_at.isoformat() if published_at else None,
        )
