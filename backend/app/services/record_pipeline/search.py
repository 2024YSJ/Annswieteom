from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Select, select

from app.db.session import AsyncSessionLocal
from app.models.record import Record
from app.models.record_chunk import RecordChunk
from app.services.embedding.base import EmbeddingProvider


@dataclass
class RecordChunkExcerpt:
    chunk_id: uuid.UUID
    text: str
    published_at: date | None


def _record_ids_for(session_id: uuid.UUID, category_id: uuid.UUID | None):
    stmt = select(Record.id).where(Record.session_id == session_id)
    if category_id is not None:
        stmt = stmt.where(Record.category_id == category_id)
    return stmt.scalar_subquery()


def _recency_ordered(record_ids_subq, top_k: int) -> Select:
    return (
        select(RecordChunk)
        .where(RecordChunk.record_id.in_(record_ids_subq))
        .order_by(RecordChunk.created_at)
        .limit(top_k)
    )


async def _embed_query(query_text: str, embedding_provider: EmbeddingProvider | None) -> list[float] | None:
    """None means "no usable query vector" — every caller then falls back to
    recency ordering rather than failing the interview turn. Embedding runs on
    the same local Ollama/Gemini pair as generation, so it is exactly as likely
    to be down, and a missing excerpt is a degraded answer draft, not a broken
    state machine.
    """
    if not query_text or not query_text.strip():
        return None
    provider = embedding_provider
    if provider is None:
        from app.services.embedding import LocalOllamaEmbedding

        provider = LocalOllamaEmbedding()
    try:
        vectors = await provider.embed([query_text])
    except Exception:
        return None
    return vectors[0] if vectors else None


async def search_relevant_chunks(
    session_id: uuid.UUID,
    category_id: uuid.UUID,
    query_text: str | None = None,
    top_k: int = 5,
    embedding_provider: EmbeddingProvider | None = None,
) -> list[RecordChunkExcerpt]:
    """Return the record chunks most relevant to `query_text` for this category.

    Three layers, in order:

    1. **Vector search** (`query_text` given, embeddings present) — the chunk's
       stored `bge-m3` vector against the vector of the question we are about
       to ask, ordered by cosine distance. This is the whole point of the
       `record_chunks.embedding` column and its ivfflat index; until 2026-09-09
       nothing read either of them (the search below was the only code path),
       so a long blog post only ever contributed its first few chunks no matter
       what the question was.
    2. **Category recency** — the pre-existing behaviour, kept as the fallback
       for records whose embedding never got written (pipeline failure, or a
       chunk predating the embedding step) and for when the embedding provider
       is unreachable.
    3. **Session-wide** — if this category has no chunks at all, search every
       record in the session. Records carry a `category_id` chosen at upload
       time, and users routinely attach a document under the "wrong" category;
       one relevant excerpt from elsewhere in the session beats none.
    """
    async with AsyncSessionLocal() as db:
        record_ids_subq = _record_ids_for(session_id, category_id)

        has_category_chunks = await db.scalar(
            select(RecordChunk.id).where(RecordChunk.record_id.in_(record_ids_subq)).limit(1)
        )
        if has_category_chunks is None:
            record_ids_subq = _record_ids_for(session_id, None)

        chunks = None
        query_vector = await _embed_query(query_text, embedding_provider) if query_text else None
        if query_vector is not None:
            stmt = (
                select(RecordChunk)
                .where(
                    RecordChunk.record_id.in_(record_ids_subq),
                    RecordChunk.embedding.is_not(None),
                )
                .order_by(RecordChunk.embedding.cosine_distance(query_vector))
                .limit(top_k)
            )
            try:
                chunks = (await db.execute(stmt)).scalars().all()
            except Exception:
                # No pgvector (e.g. SQLite in tests), a dimension mismatch, or a
                # missing index — none of which should cost the user their
                # excerpts entirely.
                await db.rollback()
                chunks = None

        if not chunks:
            chunks = (await db.execute(_recency_ordered(record_ids_subq, top_k))).scalars().all()

    return [
        RecordChunkExcerpt(
            chunk_id=c.id,
            text=c.chunk_text,
            published_at=c.published_at,
        )
        for c in chunks
    ]


async def find_uncited_chunks(
    session_id: uuid.UUID,
    db,
    limit: int = 20,
) -> list[RecordChunkExcerpt]:
    """Chunks the user attached that no confirmed fact ever cited.

    The one question a chat window structurally cannot ask: "you uploaded this
    and we never used it — is there something in here worth saying?" Only
    possible because the excerpts and the citations both live in the database.
    """
    from app.models.confirmed_fact import ConfirmedFact

    cited_subq = (
        select(ConfirmedFact.source_record_chunk_id)
        .where(ConfirmedFact.source_record_chunk_id.is_not(None))
        .scalar_subquery()
    )
    stmt = (
        select(RecordChunk)
        .where(
            RecordChunk.record_id.in_(_record_ids_for(session_id, None)),
            RecordChunk.id.not_in(cited_subq),
        )
        .order_by(RecordChunk.created_at)
        .limit(limit)
    )
    chunks = (await db.execute(stmt)).scalars().all()
    return [
        RecordChunkExcerpt(chunk_id=c.id, text=c.chunk_text, published_at=c.published_at)
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
