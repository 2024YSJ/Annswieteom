from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_owned_session
from app.db.session import get_db
from app.models.confirmed_fact import ConfirmedFact
from app.models.generated_document import GeneratedDocument
from app.models.generated_paragraph import GeneratedParagraph
from app.models.generated_sentence import GeneratedSentence
from app.models.session import Session as SessionModel
from app.schemas.document import (
    CitationRead,
    DocumentRead,
    EvidenceRead,
    GenerateRequest,
    MoveSentenceRequest,
    ParagraphRead,
    ParagraphUpdate,
    SentenceRead,
    SentenceUpdate,
)
from app.services import document_generator
from app.services import interview_orchestrator as orchestrator
from app.services.embedding import get_embedding_provider
from app.services.embedding.base import EmbeddingProvider
from app.services.llm.base import LLMProvider
from app.services.llm.fallback import get_llm_provider
from app.services.record_pipeline.citation import get_fact_citations

router = APIRouter(prefix="/sessions", tags=["document"])


def _violation_to_409(exc: orchestrator.StateMachineViolation) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


async def _get_latest_document(session_id: uuid.UUID, db: AsyncSession) -> GeneratedDocument | None:
    stmt = (
        select(GeneratedDocument)
        .where(GeneratedDocument.session_id == session_id)
        .order_by(GeneratedDocument.version.desc())
    )
    return (await db.execute(stmt)).scalars().first()


async def _get_owned_sentence(session: SessionModel, sentence_id: uuid.UUID, db: AsyncSession) -> GeneratedSentence:
    stmt = (
        select(GeneratedSentence)
        .join(GeneratedDocument, GeneratedSentence.document_id == GeneratedDocument.id)
        .where(GeneratedSentence.id == sentence_id, GeneratedDocument.session_id == session.id)
    )
    sentence = (await db.execute(stmt)).scalar_one_or_none()
    if sentence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sentence_not_found")
    return sentence


async def _get_owned_paragraph(session: SessionModel, paragraph_id: uuid.UUID, db: AsyncSession) -> GeneratedParagraph:
    stmt = (
        select(GeneratedParagraph)
        .join(GeneratedDocument, GeneratedParagraph.document_id == GeneratedDocument.id)
        .where(GeneratedParagraph.id == paragraph_id, GeneratedDocument.session_id == session.id)
    )
    paragraph = (await db.execute(stmt)).scalar_one_or_none()
    if paragraph is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="paragraph_not_found")
    return paragraph


async def _sentence_read(sentence: GeneratedSentence, db: AsyncSession, fact_citations) -> SentenceRead:
    fact_ids = [uuid.UUID(fact_id_str) for fact_id_str in sentence.evidence_fact_ids]
    citations = await fact_citations(fact_ids, db)

    evidence: list[EvidenceRead] = []
    for fact_id in fact_ids:
        fact = await db.get(ConfirmedFact, fact_id)
        if fact is None:
            continue
        citation = citations.get(fact_id)
        evidence.append(EvidenceRead(
            fact_id=fact.id,
            content=fact.content,
            source_type=fact.source_type,
            citation=CitationRead(source_url=citation.source_url, published_at=citation.published_at) if citation else None,
        ))

    return SentenceRead(
        id=sentence.id,
        order_index=sentence.order_index,
        text=sentence.text,
        evidence=evidence,
        consistency_check_passed=sentence.consistency_check_passed,
    )


async def _paragraph_read(paragraph: GeneratedParagraph, db: AsyncSession, fact_citations) -> ParagraphRead:
    stmt = (
        select(GeneratedSentence)
        .where(GeneratedSentence.paragraph_id == paragraph.id)
        .order_by(GeneratedSentence.order_index)
    )
    sentences = (await db.execute(stmt)).scalars().all()
    return ParagraphRead(
        id=paragraph.id,
        order_index=paragraph.order_index,
        topic=paragraph.topic,
        user_confirmed=paragraph.user_confirmed,
        sentences=[await _sentence_read(s, db, fact_citations) for s in sentences],
    )


async def _document_read(document: GeneratedDocument, db: AsyncSession, fact_citations) -> DocumentRead:
    para_stmt = (
        select(GeneratedParagraph)
        .where(GeneratedParagraph.document_id == document.id)
        .order_by(GeneratedParagraph.order_index)
    )
    paragraphs = (await db.execute(para_stmt)).scalars().all()
    paragraph_reads = [await _paragraph_read(p, db, fact_citations) for p in paragraphs]

    # Sentences pre-dating the paragraph_id column (or otherwise orphaned)
    # each become their own single-sentence paragraph, so old documents
    # still render sensibly instead of disappearing.
    sent_stmt = (
        select(GeneratedSentence)
        .where(GeneratedSentence.document_id == document.id, GeneratedSentence.paragraph_id.is_(None))
        .order_by(GeneratedSentence.order_index)
    )
    orphan_sentences = (await db.execute(sent_stmt)).scalars().all()
    for s in orphan_sentences:
        paragraph_reads.append(ParagraphRead(
            id=s.id, order_index=s.order_index, topic="", user_confirmed=False,
            sentences=[await _sentence_read(s, db, fact_citations)],
        ))
    paragraph_reads.sort(key=lambda p: p.order_index)

    return DocumentRead(
        id=document.id,
        tone=document.tone,
        version=document.version,
        status=document.status,
        paragraphs=paragraph_reads,
    )


@router.post("/{session_id}/generate", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def generate_document(
    payload: GenerateRequest,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    fact_citations=Depends(get_fact_citations),
) -> DocumentRead:
    try:
        next_status = orchestrator.require_simple_transition("generate", session.status)
    except orchestrator.StateMachineViolation as exc:
        raise _violation_to_409(exc) from exc

    document = await document_generator.generate_full_document(
        session.id, payload.tone, db, llm, embedding_provider=embedding_provider
    )
    session.status = next_status
    await db.commit()

    return await _document_read(document, db, fact_citations)


@router.get("/{session_id}/document", response_model=DocumentRead)
async def get_document(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    fact_citations=Depends(get_fact_citations),
) -> DocumentRead:
    document = await _get_latest_document(session.id, db)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")
    return await _document_read(document, db, fact_citations)


@router.post("/{session_id}/document/regenerate", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def regenerate_document(
    payload: GenerateRequest,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    fact_citations=Depends(get_fact_citations),
) -> DocumentRead:
    try:
        orchestrator.require_status("regenerate", session.status, "RESULT_REVIEW")
    except orchestrator.StateMachineViolation as exc:
        raise _violation_to_409(exc) from exc

    latest = await _get_latest_document(session.id, db)
    if latest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")

    document = await document_generator.generate_full_document(
        session.id, payload.tone, db, llm, version=latest.version + 1, embedding_provider=embedding_provider
    )
    return await _document_read(document, db, fact_citations)


@router.patch("/{session_id}/document/sentences/{sentence_id}", response_model=SentenceRead)
async def update_sentence(
    sentence_id: uuid.UUID,
    payload: SentenceUpdate,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    fact_citations=Depends(get_fact_citations),
) -> SentenceRead:
    sentence = await _get_owned_sentence(session, sentence_id, db)

    # 재검증 불필요 — 사용자가 직접 쓴 문장은 그 자체로 이미 "확인됨" 상태다
    # (04_document_generation.md 2절). evidence_fact_ids는 그대로 유지한다.
    sentence.text = payload.text
    sentence.consistency_check_passed = True
    await db.commit()
    await db.refresh(sentence)

    return await _sentence_read(sentence, db, fact_citations)


@router.patch("/{session_id}/document/paragraphs/{paragraph_id}", response_model=ParagraphRead)
async def update_paragraph(
    paragraph_id: uuid.UUID,
    payload: ParagraphUpdate,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    fact_citations=Depends(get_fact_citations),
) -> ParagraphRead:
    paragraph = await _get_owned_paragraph(session, paragraph_id, db)
    if payload.topic is not None:
        paragraph.topic = payload.topic
    if payload.user_confirmed is not None:
        paragraph.user_confirmed = payload.user_confirmed
    await db.commit()
    await db.refresh(paragraph)
    return await _paragraph_read(paragraph, db, fact_citations)


@router.post("/{session_id}/document/paragraphs/{paragraph_id}/merge-next", response_model=ParagraphRead)
async def merge_paragraph_with_next(
    paragraph_id: uuid.UUID,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    fact_citations=Depends(get_fact_citations),
) -> ParagraphRead:
    """관련성 확인 단계의 핵심 조작: 인접한 두 문단이 같은 이야기라고 판단되면
    합친다. 임의의 두 문단을 고르는 UI 대신 "다음 문단과 합치기"로 단순화했다
    — 문단은 이미 순서가 있으므로 인접 병합만으로 대부분의 재구성이 된다.
    """
    paragraph = await _get_owned_paragraph(session, paragraph_id, db)
    next_paragraph = (
        await db.execute(
            select(GeneratedParagraph)
            .where(
                GeneratedParagraph.document_id == paragraph.document_id,
                GeneratedParagraph.order_index > paragraph.order_index,
            )
            .order_by(GeneratedParagraph.order_index)
        )
    ).scalars().first()
    if next_paragraph is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_next_paragraph")

    moved_sentences = (
        await db.execute(
            select(GeneratedSentence).where(GeneratedSentence.paragraph_id == next_paragraph.id)
        )
    ).scalars().all()
    for sentence in moved_sentences:
        sentence.paragraph_id = paragraph.id
    # Must flush the reassignment before deleting next_paragraph — the FK's
    # ON DELETE CASCADE fires against whatever paragraph_id is in the DB at
    # delete time, and without this flush the moved sentences can still
    # point at next_paragraph there, so the cascade deletes them too instead
    # of leaving them re-homed on `paragraph`.
    await db.flush()
    await db.delete(next_paragraph)
    await db.commit()
    await db.refresh(paragraph)
    return await _paragraph_read(paragraph, db, fact_citations)


@router.delete("/{session_id}/document/paragraphs/{paragraph_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_paragraph(
    paragraph_id: uuid.UUID,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
):
    # No `-> None` return annotation here — see the comment on
    # sessions.delete_session for why that trips FastAPI's 204-response-body
    # assertion under `from __future__ import annotations`.
    #
    # Removes the paragraph's sentences along with it, rather than re-homing
    # them on a neighbor the way merge-next does — this is "delete this whole
    # block", not "combine it with another one". The underlying confirmed_facts
    # those sentences cited are untouched, so nothing about the
    # interview/honesty-guardrail data is lost.
    #
    # Sentences are deleted explicitly (not left to generated_sentences.paragraph_id's
    # ON DELETE CASCADE) — GeneratedParagraph.sentences has no ORM-level delete
    # cascade, and without one, SQLAlchemy's unit-of-work de-associates a
    # deleted parent's loaded children by nulling their FK instead of deleting
    # them, pre-empting the DB constraint entirely. Confirmed by a failing test:
    # deleting a paragraph this way left its sentence behind as an "orphaned
    # sentence" (paragraph_id NULL) rather than removing it.
    paragraph = await _get_owned_paragraph(session, paragraph_id, db)
    sentences = (
        await db.execute(select(GeneratedSentence).where(GeneratedSentence.paragraph_id == paragraph.id))
    ).scalars().all()
    for sentence in sentences:
        await db.delete(sentence)
    await db.delete(paragraph)
    await db.commit()


@router.post("/{session_id}/document/sentences/{sentence_id}/move", response_model=SentenceRead)
async def move_sentence(
    sentence_id: uuid.UUID,
    payload: MoveSentenceRequest,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    fact_citations=Depends(get_fact_citations),
) -> SentenceRead:
    """관련성 확인의 또 다른 조작: 문장 하나가 잘못된 문단에 묶였다고 판단되면
    이웃 문단으로 옮긴다. 문단을 하나씩 비우면서 옮기면 사실상 분리(split)도
    이 프리미티브로 구성된다.
    """
    sentence = await _get_owned_sentence(session, sentence_id, db)
    if sentence.paragraph_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="sentence_has_no_paragraph")
    current_paragraph = await db.get(GeneratedParagraph, sentence.paragraph_id)

    if payload.direction == "next":
        comparator = GeneratedParagraph.order_index > current_paragraph.order_index
        order_by = GeneratedParagraph.order_index.asc()
    else:
        comparator = GeneratedParagraph.order_index < current_paragraph.order_index
        order_by = GeneratedParagraph.order_index.desc()

    target_paragraph = (
        await db.execute(
            select(GeneratedParagraph)
            .where(GeneratedParagraph.document_id == current_paragraph.document_id, comparator)
            .order_by(order_by)
        )
    ).scalars().first()
    if target_paragraph is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"no_{payload.direction}_paragraph")

    sentence.paragraph_id = target_paragraph.id
    await db.commit()
    await db.refresh(sentence)
    return await _sentence_read(sentence, db, fact_citations)


@router.post("/{session_id}/document/sentences/{sentence_id}/regenerate", response_model=SentenceRead)
async def regenerate_sentence(
    sentence_id: uuid.UUID,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    fact_citations=Depends(get_fact_citations),
) -> SentenceRead:
    sentence = await _get_owned_sentence(session, sentence_id, db)
    document = await db.get(GeneratedDocument, sentence.document_id)

    try:
        sentence = await document_generator.regenerate_sentence(
            sentence, document.tone, db, llm, embedding_provider=embedding_provider
        )
    except document_generator.NoEvidenceToRegenerateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return await _sentence_read(sentence, db, fact_citations)


@router.post("/{session_id}/document/finalize", response_model=DocumentRead)
async def finalize_document(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    fact_citations=Depends(get_fact_citations),
) -> DocumentRead:
    document = await _get_latest_document(session.id, db)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")

    document.status = "FINAL"
    await db.commit()
    await db.refresh(document)

    return await _document_read(document, db, fact_citations)


@router.get("/{session_id}/export")
async def export_document(
    format: str = "txt",
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    if format != "txt":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported_format")

    document = await _get_latest_document(session.id, db)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")
    if document.status != "FINAL":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="document_not_finalized")

    para_stmt = (
        select(GeneratedParagraph)
        .where(GeneratedParagraph.document_id == document.id)
        .order_by(GeneratedParagraph.order_index)
    )
    paragraphs = (await db.execute(para_stmt)).scalars().all()

    sent_stmt = (
        select(GeneratedSentence)
        .where(GeneratedSentence.document_id == document.id)
        .order_by(GeneratedSentence.order_index)
    )
    sentences = (await db.execute(sent_stmt)).scalars().all()

    # Sentences within a paragraph read as one flowing block (space-joined,
    # not one per line); paragraphs are separated by a blank line. The topic
    # label itself is a review-screen aid, not resume prose, so it's never
    # included in the exported text.
    sentences_by_paragraph: dict = {p.id: [] for p in paragraphs}
    blocks: list[tuple[int, str]] = []
    for s in sentences:
        if s.paragraph_id is not None and s.paragraph_id in sentences_by_paragraph:
            sentences_by_paragraph[s.paragraph_id].append(s.text)
        else:
            blocks.append((s.order_index, s.text))
    for p in paragraphs:
        if sentences_by_paragraph[p.id]:
            blocks.append((p.order_index, " ".join(sentences_by_paragraph[p.id])))
    blocks.sort(key=lambda b: b[0])

    text = "\n\n".join(block_text for _, block_text in blocks)

    return PlainTextResponse(content=text)
