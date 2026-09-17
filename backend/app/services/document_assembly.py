from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.confirmed_fact import ConfirmedFact
from app.models.generated_document import GeneratedDocument
from app.models.generated_paragraph import GeneratedParagraph
from app.models.generated_sentence import GeneratedSentence
from app.schemas.document import CitationRead, DocumentRead, EvidenceRead, ParagraphRead, SentenceRead
from app.services.evidence import grade_for

"""GeneratedDocument -> DocumentRead 조립 로직.

api/document.py의 private 헬퍼(_get_latest_document/_document_read/_paragraph_read/
_sentence_read)였던 것을 그대로 옮긴 공개 모듈이다 — 동작 변화 없는 순수 이동.
api/demo.py, api/share.py가 이걸 재사용해 "문서를 DocumentRead로 조립하는 법"을
세 곳에서 중복 구현하지 않는다.
"""


async def get_latest_document(session_id: uuid.UUID, db: AsyncSession) -> GeneratedDocument | None:
    stmt = (
        select(GeneratedDocument)
        .where(GeneratedDocument.session_id == session_id)
        .order_by(GeneratedDocument.version.desc())
    )
    return (await db.execute(stmt)).scalars().first()


async def build_sentence_read(sentence: GeneratedSentence, db: AsyncSession, fact_citations) -> SentenceRead:
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
        consistency_score=sentence.consistency_score,
        edited_by_user=sentence.edited_by_user,
        evidence_grade=grade_for(e.source_type for e in evidence),
    )


async def build_paragraph_read(paragraph: GeneratedParagraph, db: AsyncSession, fact_citations) -> ParagraphRead:
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
        sentences=[await build_sentence_read(s, db, fact_citations) for s in sentences],
    )


async def build_document_read(document: GeneratedDocument, db: AsyncSession, fact_citations) -> DocumentRead:
    para_stmt = (
        select(GeneratedParagraph)
        .where(GeneratedParagraph.document_id == document.id)
        .order_by(GeneratedParagraph.order_index)
    )
    paragraphs = (await db.execute(para_stmt)).scalars().all()
    paragraph_reads = [await build_paragraph_read(p, db, fact_citations) for p in paragraphs]

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
            sentences=[await build_sentence_read(s, db, fact_citations)],
        ))
    paragraph_reads.sort(key=lambda p: p.order_index)

    return DocumentRead(
        id=document.id,
        tone=document.tone,
        version=document.version,
        status=document.status,
        paragraphs=paragraph_reads,
    )
