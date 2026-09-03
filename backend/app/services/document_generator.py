from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_category import ActivityCategory
from app.models.confirmed_fact import ConfirmedFact
from app.models.generated_document import GeneratedDocument
from app.models.generated_sentence import GeneratedSentence
from app.services.consistency_check import check_sentence_consistency
from app.services.embedding.base import EmbeddingProvider
from app.services.llm.base import ConfirmedFact as LLMConfirmedFact, LLMProvider


class NoEvidenceToRegenerateError(Exception):
    """A sentence with no cited facts (or an LLM that returns nothing) can't be regenerated."""


async def generate_full_document(
    session_id: uuid.UUID,
    tone: str,
    db: AsyncSession,
    llm: LLMProvider,
    version: int = 1,
    embedding_provider: EmbeddingProvider | None = None,
) -> GeneratedDocument:
    """카테고리별로 LLMProvider.generate_document()를 한 번씩 호출해 세션 전체 문서를 만든다.

    정직성 가드레일(1-2절): LLMProvider에는 카테고리의 confirmed_facts 목록과
    tone 문자열만 넘긴다 — 세션/카테고리 ORM 객체 전체를 넘기지 않는다. 그래야
    "확정된 사실만 최종 생성 입력이 될 수 있다"는 경계가 코드 상에서 강제된다.
    """
    categories = (
        await db.execute(
            select(ActivityCategory)
            .where(ActivityCategory.session_id == session_id)
            .order_by(ActivityCategory.order_index)
        )
    ).scalars().all()

    document = GeneratedDocument(session_id=session_id, tone=tone, version=version)
    db.add(document)
    await db.flush()

    order_index = 0
    for category in categories:
        facts = (
            await db.execute(
                select(ConfirmedFact)
                .where(ConfirmedFact.category_id == category.id)
                .order_by(ConfirmedFact.created_at)
            )
        ).scalars().all()
        if not facts:
            continue

        llm_facts = [
            LLMConfirmedFact(id=str(f.id), content=f.content, source_type=f.source_type, fact_type=f.fact_type)
            for f in facts
        ]
        draft = await llm.generate_document(llm_facts, tone)

        for sentence in draft.sentences:
            cited_facts = [facts[i] for i in sentence.fact_indices if 0 <= i < len(facts)]
            passed = await check_sentence_consistency(sentence.text, cited_facts, embedding_provider)

            db.add(GeneratedSentence(
                document_id=document.id,
                category_id=category.id,
                order_index=order_index,
                text=sentence.text,
                evidence_fact_ids=[str(f.id) for f in cited_facts],
                consistency_check_passed=passed,
            ))
            order_index += 1

    await db.commit()
    await db.refresh(document)
    return document


async def regenerate_sentence(
    sentence: GeneratedSentence,
    tone: str,
    db: AsyncSession,
    llm: LLMProvider,
    embedding_provider: EmbeddingProvider | None = None,
) -> GeneratedSentence:
    """단건 재생성 (9-5절). LLMProvider는 카테고리 단위로만 생성하므로, 이 문장이
    원래 인용했던 confirmed_facts만 다시 넘겨 그 근거에 한정된 새 초안을 받고
    첫 문장을 채택한다 — 여전히 confirmed_facts 외의 입력은 섞이지 않는다.
    """
    fact_ids = [uuid.UUID(fid) for fid in sentence.evidence_fact_ids]
    facts = [f for f in [await db.get(ConfirmedFact, fid) for fid in fact_ids] if f is not None]
    if not facts:
        raise NoEvidenceToRegenerateError("Sentence has no cited facts to regenerate from")

    llm_facts = [
        LLMConfirmedFact(id=str(f.id), content=f.content, source_type=f.source_type, fact_type=f.fact_type)
        for f in facts
    ]
    draft = await llm.generate_document(llm_facts, tone)
    if not draft.sentences:
        raise NoEvidenceToRegenerateError("LLM returned no sentences to regenerate from")

    new_sentence = draft.sentences[0]
    cited_facts = [facts[i] for i in new_sentence.fact_indices if 0 <= i < len(facts)] or facts

    sentence.text = new_sentence.text
    sentence.evidence_fact_ids = [str(f.id) for f in cited_facts]
    sentence.consistency_check_passed = await check_sentence_consistency(sentence.text, cited_facts, embedding_provider)

    await db.commit()
    await db.refresh(sentence)
    return sentence
