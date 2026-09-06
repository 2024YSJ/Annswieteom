from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.confirmed_fact import ConfirmedFact
from app.models.record import Record
from app.models.record_chunk import RecordChunk


@dataclass
class Citation:
    source_url: str | None
    published_at: str | None  # ISO date string


async def resolve_fact_citations(fact_ids: Iterable[uuid.UUID], db: AsyncSession) -> dict[uuid.UUID, Citation]:
    """Return source URL/date for whichever of the given facts are backed by a
    record chunk (facts with no citation — user_confirmed/user_edited, or an
    unresolvable chunk — are simply absent from the returned dict).

    Batches every fact into one JOIN query on the caller's own session, rather
    than looking each one up with its own query on a brand-new DB connection
    (the previous per-fact `resolve_fact_citation` did exactly that). Against a
    remote Postgres (Supabase), that per-fact connection setup — not any LLM or
    consistency-check work — was the actual cause of "moving a sentence between
    paragraphs takes forever": every full-document refetch re-resolves the
    citation of every cited fact in the document (2026-09-06).
    """
    fact_ids = list(fact_ids)
    if not fact_ids:
        return {}

    stmt = (
        select(ConfirmedFact.id, Record.source_url, RecordChunk.published_at)
        .join(RecordChunk, RecordChunk.id == ConfirmedFact.source_record_chunk_id)
        .join(Record, Record.id == RecordChunk.record_id)
        .where(ConfirmedFact.id.in_(fact_ids))
    )
    rows = (await db.execute(stmt)).all()
    return {
        fact_id: Citation(source_url=source_url, published_at=published_at.isoformat() if published_at else None)
        for fact_id, source_url, published_at in rows
    }


def get_fact_citations():
    """FastAPI DI hook wrapping resolve_fact_citations — see
    app/services/record_pipeline/search.py::get_chunk_search for why routes
    depend on this instead of importing the function directly (test overrides).
    """
    return resolve_fact_citations
