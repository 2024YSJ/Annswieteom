from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.interview import get_llm_provider
from app.core.deps import get_owned_session
from app.db.session import get_db
from app.models.confirmed_fact import ConfirmedFact
from app.models.generated_document import GeneratedDocument
from app.models.generated_sentence import GeneratedSentence
from app.models.session import Session as SessionModel
from app.schemas.document import (
    CitationRead,
    DocumentRead,
    EvidenceRead,
    GenerateRequest,
    SentenceRead,
    SentenceUpdate,
)
from app.services import document_generator
from app.services import interview_orchestrator as orchestrator
from app.services.embedding import get_embedding_provider
from app.services.embedding.base import EmbeddingProvider
from app.services.llm.base import LLMProvider
from app.services.record_pipeline.citation import get_fact_citation

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


async def _sentence_read(sentence: GeneratedSentence, db: AsyncSession, fact_citation) -> SentenceRead:
    evidence: list[EvidenceRead] = []
    for fact_id_str in sentence.evidence_fact_ids:
        fact = await db.get(ConfirmedFact, uuid.UUID(fact_id_str))
        if fact is None:
            continue
        citation = await fact_citation(fact.id)
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


async def _document_read(document: GeneratedDocument, db: AsyncSession, fact_citation) -> DocumentRead:
    stmt = (
        select(GeneratedSentence)
        .where(GeneratedSentence.document_id == document.id)
        .order_by(GeneratedSentence.order_index)
    )
    sentences = (await db.execute(stmt)).scalars().all()
    sentence_reads = [await _sentence_read(s, db, fact_citation) for s in sentences]

    return DocumentRead(
        id=document.id,
        tone=document.tone,
        version=document.version,
        status=document.status,
        sentences=sentence_reads,
    )


@router.post("/{session_id}/generate", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def generate_document(
    payload: GenerateRequest,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    fact_citation=Depends(get_fact_citation),
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

    return await _document_read(document, db, fact_citation)


@router.get("/{session_id}/document", response_model=DocumentRead)
async def get_document(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    fact_citation=Depends(get_fact_citation),
) -> DocumentRead:
    document = await _get_latest_document(session.id, db)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")
    return await _document_read(document, db, fact_citation)


@router.post("/{session_id}/document/regenerate", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def regenerate_document(
    payload: GenerateRequest,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    fact_citation=Depends(get_fact_citation),
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
    return await _document_read(document, db, fact_citation)


@router.patch("/{session_id}/document/sentences/{sentence_id}", response_model=SentenceRead)
async def update_sentence(
    sentence_id: uuid.UUID,
    payload: SentenceUpdate,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    fact_citation=Depends(get_fact_citation),
) -> SentenceRead:
    sentence = await _get_owned_sentence(session, sentence_id, db)

    # 재검증 불필요 — 사용자가 직접 쓴 문장은 그 자체로 이미 "확인됨" 상태다
    # (04_document_generation.md 2절). evidence_fact_ids는 그대로 유지한다.
    sentence.text = payload.text
    sentence.consistency_check_passed = True
    await db.commit()
    await db.refresh(sentence)

    return await _sentence_read(sentence, db, fact_citation)


@router.post("/{session_id}/document/sentences/{sentence_id}/regenerate", response_model=SentenceRead)
async def regenerate_sentence(
    sentence_id: uuid.UUID,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    fact_citation=Depends(get_fact_citation),
) -> SentenceRead:
    sentence = await _get_owned_sentence(session, sentence_id, db)
    document = await db.get(GeneratedDocument, sentence.document_id)

    try:
        sentence = await document_generator.regenerate_sentence(
            sentence, document.tone, db, llm, embedding_provider=embedding_provider
        )
    except document_generator.NoEvidenceToRegenerateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return await _sentence_read(sentence, db, fact_citation)


@router.post("/{session_id}/document/finalize", response_model=DocumentRead)
async def finalize_document(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    fact_citation=Depends(get_fact_citation),
) -> DocumentRead:
    document = await _get_latest_document(session.id, db)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")

    document.status = "FINAL"
    await db.commit()
    await db.refresh(document)

    return await _document_read(document, db, fact_citation)


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

    stmt = (
        select(GeneratedSentence)
        .where(GeneratedSentence.document_id == document.id)
        .order_by(GeneratedSentence.order_index)
    )
    sentences = (await db.execute(stmt)).scalars().all()
    text = "\n".join(s.text for s in sentences)

    return PlainTextResponse(content=text)
