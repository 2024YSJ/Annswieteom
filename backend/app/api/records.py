from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_owned_session
from app.db.session import get_db
from app.models.gap_period import GapPeriod
from app.models.record import Record
from app.models.session import Session as SessionModel
from app.schemas.record import BlogRecordCreate, RecordRead, TextRecordCreate
from app.services import interview_orchestrator as orchestrator
from app.services.record_pipeline.parsers import velog
from app.services.record_pipeline.pipeline import process_image_record, process_record
from app.services.storage import SupabaseStorage, get_storage

router = APIRouter(prefix="/sessions", tags=["records"])

_ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def get_process_record():
    return process_record


def get_process_image_record():
    return process_image_record


def _require_record_creatable(session: SessionModel) -> None:
    try:
        orchestrator.require_record_creatable(session.status)
    except orchestrator.StateMachineViolation as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


async def _get_owned_record(session: SessionModel, record_id: uuid.UUID, db: AsyncSession) -> Record:
    record = await db.get(Record, record_id)
    if record is None or record.session_id != session.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="record_not_found")
    return record


@router.post("/{session_id}/records", response_model=list[RecordRead], status_code=status.HTTP_201_CREATED)
async def create_blog_record(
    payload: BlogRecordCreate,
    background_tasks: BackgroundTasks,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    process_record_fn=Depends(get_process_record),
) -> list[Record]:
    _require_record_creatable(session)

    # A listing/profile page (e.g. /@user/posts) isn't one post — instead of
    # rejecting it, pull every public post in the session's gap period from
    # that page and create one Record per post (all pointing at the real
    # individual post URLs, so each still parses via the normal single-post
    # path in the background).
    listing_username = velog.get_listing_username(payload.source_url)
    if listing_username is not None:
        gap = (
            await db.execute(select(GapPeriod).where(GapPeriod.session_id == session.id))
        ).scalars().first()
        if gap is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="gap_period_missing")

        posts = await velog.list_posts_in_range(listing_username, gap.start_date, gap.end_date)
        if not posts:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="no_posts_in_period")

        records = [
            Record(
                session_id=session.id,
                record_type="blog_url",
                source_url=velog.build_post_url(listing_username, post.url_slug),
            )
            for post in posts
        ]
        db.add_all(records)
        await db.commit()
        for record in records:
            await db.refresh(record)
            background_tasks.add_task(process_record_fn, record.id)
        return records

    record = Record(session_id=session.id, record_type="blog_url", source_url=payload.source_url)
    db.add(record)
    await db.commit()
    await db.refresh(record)

    background_tasks.add_task(process_record_fn, record.id)
    return [record]


@router.post("/{session_id}/records/text", response_model=RecordRead, status_code=status.HTTP_201_CREATED)
async def create_text_record(
    payload: TextRecordCreate,
    background_tasks: BackgroundTasks,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    process_record_fn=Depends(get_process_record),
) -> Record:
    _require_record_creatable(session)

    record = Record(session_id=session.id, record_type="text", raw_text=payload.text)
    db.add(record)
    await db.commit()
    await db.refresh(record)

    # process_record skips straight to chunking/embedding for record_type="text"
    # (no fetch step) — see app/services/record_pipeline/pipeline.py::_fetch_text.
    background_tasks.add_task(process_record_fn, record.id)
    return record


@router.post("/{session_id}/records/upload", response_model=RecordRead, status_code=status.HTTP_201_CREATED)
async def upload_image_record(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    storage: SupabaseStorage = Depends(get_storage),
    process_image_record_fn=Depends(get_process_image_record),
) -> Record:
    _require_record_creatable(session)

    extension = _ALLOWED_IMAGE_CONTENT_TYPES.get(file.content_type or "")
    if extension is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported_image_type")

    content = await file.read()

    record = Record(id=uuid.uuid4(), session_id=session.id, record_type="image")
    # 사용자·세션·기록물 단위로 경로를 분리해 다른 사용자의 파일과 절대 겹치지 않게 한다
    # (person_B_frontend_backend/03_records_feature.md 1-1절).
    record.storage_path = f"records/{session.user_id}/{session.id}/{record.id}{extension}"
    await storage.upload(record.storage_path, content, file.content_type)

    db.add(record)
    await db.commit()
    await db.refresh(record)

    background_tasks.add_task(process_image_record_fn, record.id)
    return record


@router.get("/{session_id}/records/{record_id}", response_model=RecordRead)
async def get_record(
    record_id: uuid.UUID,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
) -> Record:
    return await _get_owned_record(session, record_id, db)


@router.delete("/{session_id}/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record(
    record_id: uuid.UUID,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    storage: SupabaseStorage = Depends(get_storage),
):
    # No `-> None` annotation — see the comment on sessions.delete_session for why
    # that trips FastAPI's 204-response-body assertion under `from __future__ import annotations`.
    record = await _get_owned_record(session, record_id, db)

    if record.storage_path:
        try:
            await storage.delete(record.storage_path)
        except Exception:
            # Storage cleanup is best-effort — an orphaned object in the bucket
            # shouldn't block the user from deleting the record from their session.
            pass

    await db.delete(record)
    await db.commit()
