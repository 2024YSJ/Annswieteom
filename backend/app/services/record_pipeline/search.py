from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.record import Record
from app.models.record_chunk import RecordChunk
from app.services.embedding import FallbackEmbedding


@dataclass
class RecordChunkExcerpt:
    chunk_id: uuid.UUID
    text: str
    published_at: date | None


async def search_relevant_chunks(
    session_id: uuid.UUID,
    category_label: str,
    top_k: int = 5,
) -> list[RecordChunkExcerpt]:
    """Embed the category label and return the top-k semantically similar chunks.

    Only chunks belonging to this session are considered.
    The query uses the same embedding model that was used for storage
    (both via LocalOllamaEmbedding / bge-m3) — see fallback.model_name.
    """
    embedding_provider = FallbackEmbedding()
    [query_vector] = await embedding_provider.embed([category_label])

    async with AsyncSessionLocal() as db:
        # Subquery: record IDs belonging to this session
        record_ids_subq = select(Record.id).where(Record.session_id == session_id).scalar_subquery()

        stmt = (
            select(RecordChunk)
            .where(
                RecordChunk.record_id.in_(record_ids_subq),
                RecordChunk.embedding.is_not(None),
                # Only compare chunks embedded with the same model
                RecordChunk.embedding_model == embedding_provider.model_name,
            )
            .order_by(RecordChunk.embedding.cosine_distance(query_vector))
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
