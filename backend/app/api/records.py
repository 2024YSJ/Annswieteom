from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_owned_session
from app.db.session import get_db
from app.models.gap_period import GapPeriod
from app.models.record import Record
from app.models.session import Session as SessionModel
from app.schemas.record import BlogRecordCreate, RecordRead, TextRecordCreate, UncitedChunkRead
from app.services import interview_orchestrator as orchestrator
from app.services.record_pipeline.document_parser import DOCUMENT_EXTENSIONS
from app.services.record_pipeline.parsers import velog
from app.services.record_pipeline.pipeline import process_document_record, process_record
from app.services.record_pipeline.search import find_uncited_chunks
from app.services.storage import SupabaseStorage, get_storage

router = APIRouter(prefix="/sessions", tags=["records"])

# 확장자로 판별한다(브라우저가 넘기는 content_type은 .md/.hwp 등에서 신뢰도가 낮음 —
# 비어있거나 "application/octet-stream"으로 오는 경우가 흔함).
#
# 2026-09-09까지는 이미지(.jpg/.png/.webp)도 받아 Gemini Vision으로 OCR을 돌렸다.
# Gemini를 제거하면서 대체할 비전 모델이 없어(로컬 Ollama에는 텍스트 모델과 bge-m3만
# 있다) 이미지 업로드 자체를 없앴다 — 텍스트를 못 뽑으면 청크도 임베딩도 안 생겨서
# 기록물로서 아무 근거도 되지 못하는데, 받아만 두면 사용자는 근거가 쌓인 줄 안다.
# 이제 이미지 확장자는 다른 미지원 형식과 똑같이 unsupported_file_type으로 거절된다.
# models/record.py의 RECORD_TYPES에는 "image"를 남겨뒀다 — 이미 저장된 과거 행들이
# CHECK 제약에 걸리면 안 되기 때문이고, 새로 만들어지는 경로는 없다.


def get_process_record():
    return process_record


def get_process_document_record():
    return process_document_record


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
                category_id=session.current_category_id,
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

    record = Record(
        session_id=session.id,
        category_id=session.current_category_id,
        record_type="blog_url",
        source_url=payload.source_url,
    )
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

    record = Record(
        session_id=session.id,
        category_id=session.current_category_id,
        record_type="text",
        raw_text=payload.text,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    # process_record skips straight to chunking/embedding for record_type="text"
    # (no fetch step) — see app/services/record_pipeline/pipeline.py::_fetch_text.
    background_tasks.add_task(process_record_fn, record.id)
    return record


@router.post("/{session_id}/records/upload", response_model=RecordRead, status_code=status.HTTP_201_CREATED)
async def upload_file_record(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    storage: SupabaseStorage = Depends(get_storage),
    process_document_record_fn=Depends(get_process_document_record),
) -> Record:
    """문서(txt/md/docx/hwp) 하나를 업로드한다 — 텍스트를 직접 추출한다.
    여러 파일을 한 번에 올리는 건 프론트가 파일마다 이 엔드포인트를 반복 호출하는
    방식으로 처리한다(create_blog_record의 velog 목록 가져오기와 같은 패턴 — 파일
    하나가 실패해도 나머지에 영향이 없다).
    """
    _require_record_creatable(session)

    filename = file.filename or ""
    extension = Path(filename).suffix.lower()
    if extension not in DOCUMENT_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported_file_type")

    content = await file.read()
    record_type = "document"
    content_type = "application/octet-stream"

    record = Record(
        id=uuid.uuid4(),
        session_id=session.id,
        category_id=session.current_category_id,
        record_type=record_type,
        original_filename=filename or None,
    )
    # 사용자·세션·기록물 단위로 경로를 분리해 다른 사용자의 파일과 절대 겹치지 않게 한다
    # (person_B_frontend_backend/03_records_feature.md 1-1절).
    record.storage_path = f"records/{session.user_id}/{session.id}/{record.id}{extension}"
    await storage.upload(record.storage_path, content, content_type)

    db.add(record)
    await db.commit()
    await db.refresh(record)

    background_tasks.add_task(process_document_record_fn, record.id)
    return record


@router.get("/{session_id}/records/uncited", response_model=list[UncitedChunkRead])
async def list_uncited_chunks(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
) -> list[UncitedChunkRead]:
    """올렸지만 한 번도 근거로 쓰이지 않은 기록물 조각.

    채팅창이 구조적으로 던질 수 없는 질문이 여기서 나온다 — "이 글을 올리셨는데
    아직 아무 이야기에도 안 쓰였어요, 여기 넣을 만한 내용이 있을까요?" 대화형
    LLM은 사용자가 붙여넣은 것 중 무엇을 아직 안 썼는지 추적하지 못한다.
    인용은 confirmed_facts.source_record_chunk_id에, 조각은 record_chunks에
    각각 남아 있으므로 뺄셈으로 정확히 구할 수 있다.

    라우트 순서 주의: `/{record_id}`보다 먼저 선언해야 "uncited"가 UUID로
    파싱되려다 422로 떨어지지 않는다.
    """
    excerpts = await find_uncited_chunks(session.id, db)
    return [
        UncitedChunkRead(chunk_id=e.chunk_id, text=e.text, published_at=e.published_at)
        for e in excerpts
    ]


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
