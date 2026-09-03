from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.record import Record
from app.models.record_chunk import RecordChunk
from app.models.gap_period import GapPeriod
from app.services.embedding import FallbackEmbedding
from app.services.record_pipeline.chunker import chunk_text
from app.services.record_pipeline.ocr import MIME_TYPES_BY_EXTENSION, extract_text_from_image
from app.services.record_pipeline.parsers import generic, naver_blog, tistory
from app.services.record_pipeline.platform_detector import detect_platform
from app.services.storage import get_storage


async def process_record(record_id: uuid.UUID) -> None:
    """Parse a blog_url or pasted_text record, chunk it, and embed each chunk.

    Sets parse_status to DONE or FAILED on completion.
    """
    async with AsyncSessionLocal() as db:
        record = await db.get(Record, record_id)
        if record is None:
            return

        record.parse_status = "PROCESSING"
        await db.commit()

        try:
            text, pub_date = await _fetch_text(record)
            gap_start, gap_end = await _get_gap_period(db, record.session_id)

            if pub_date and not (gap_start <= pub_date <= gap_end):
                # Post is outside the gap period — skip without error
                record.parse_status = "DONE"
                record.raw_text = text
                await db.commit()
                return

            chunks = chunk_text(text, pub_date)
            await _embed_and_store(db, record, chunks)

            record.raw_text = text
            record.parse_status = "DONE"
            await db.commit()

        except Exception as exc:
            record.parse_status = "FAILED"
            record.parse_error = _user_message(exc)
            await db.commit()


async def process_image_record(record_id: uuid.UUID) -> None:
    """OCR an image record, chunk the extracted text, and embed each chunk.

    Sets parse_status to DONE or FAILED on completion.
    """
    async with AsyncSessionLocal() as db:
        record = await db.get(Record, record_id)
        if record is None:
            return

        record.parse_status = "PROCESSING"
        await db.commit()

        try:
            if not record.storage_path:
                raise ValueError("No storage_path for image record")

            storage = get_storage()
            image_bytes = await storage.download(record.storage_path)
            mime_type = _guess_mime_type(record.storage_path)

            text, pub_date = await extract_text_from_image(image_bytes, mime_type)
            chunks = chunk_text(text, pub_date)
            await _embed_and_store(db, record, chunks)

            record.raw_text = text
            record.parse_status = "DONE"
            await db.commit()

        except Exception as exc:
            record.parse_status = "FAILED"
            record.parse_error = _user_message(exc)
            await db.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fetch_text(record: Record) -> tuple[str, date | None]:
    if record.record_type == "text":
        return record.raw_text or "", None

    url = record.source_url or ""
    platform = detect_platform(url)
    record.platform = platform

    if platform == "naver":
        return await naver_blog.parse(url)
    if platform == "tistory":
        return await tistory.parse(url)
    # velog, brunch, other → generic
    return await generic.parse(url)


async def _get_gap_period(db, session_id: uuid.UUID) -> tuple[date, date]:
    stmt = select(GapPeriod).where(GapPeriod.session_id == session_id)
    gap = (await db.execute(stmt)).scalars().first()
    if gap is None:
        # No gap period configured — treat all dates as in-range
        from datetime import date as d
        return d.min, d.max
    return gap.start_date, gap.end_date


async def _embed_and_store(db, record: Record, chunks) -> None:
    if not chunks:
        return

    provider = FallbackEmbedding()
    texts = [c.text for c in chunks]
    vectors = await provider.embed(texts)

    for chunk, vector in zip(chunks, vectors):
        db.add(RecordChunk(
            record_id=record.id,
            chunk_text=chunk.text,
            chunk_index=chunk.chunk_index,
            published_at=chunk.published_at,
            embedding=vector,
            embedding_model=provider.model_name,
        ))


def _guess_mime_type(storage_path: str) -> str:
    for ext, mime in MIME_TYPES_BY_EXTENSION.items():
        if storage_path.lower().endswith(ext):
            return mime
    return "image/jpeg"


def _user_message(exc: Exception) -> str:
    msg = str(exc)
    if "private" in msg.lower() or "비공개" in msg:
        return "비공개 게시물은 가져올 수 없어요."
    if "timeout" in msg.lower():
        return "블로그 응답이 너무 느려요. 잠시 후 다시 시도해주세요."
    if "403" in msg or "404" in msg:
        return "게시물에 접근할 수 없어요. 주소를 확인해주세요."
    return "기록물을 가져오는 중 오류가 발생했어요."
