from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.confirmed_fact import ConfirmedFact
from app.models.generated_document import GeneratedDocument
from app.models.generated_sentence import GeneratedSentence

"""정직성 가드레일 지표 집계 — A(정직성 스코어보드)의 핵심 서비스이자 C(데모 모드)/
D(공유 카드)가 재사용하는 공유 자산.

스키마 변경이 전혀 없다: evidence_fact_ids/consistency_check_passed/consistency_score/
edited_by_user(GeneratedSentence)와 ai_draft_text(ConfirmedFact, 인터뷰 확정 시 항상
채워짐 — api/interview.py의 confirm/review 핸들러 참고)만 읽는 순수 집계다.

문장 개수가 세션당 수십 개 수준이라 SQL 집계 함수 대신 파이썬에서 계산한다 —
evidence_fact_ids가 SQLite/Postgres 양쪽에서 컴파일되는 제네릭 JSON이라(테스트를
SQLite로 돌리는 이유와 동일, generated_sentence.py 주석 참고) DB별 JSON 함수에
의존하지 않는 편이 이식성이 좋다.
"""


@dataclass
class TrustStats:
    total_sentences: int
    sentences_with_evidence: int
    machine_checked_sentences: int
    machine_checked_passed: int
    user_edited_sentences: int
    ai_draft_facts_total: int
    ai_draft_facts_accepted: int

    @property
    def evidence_coverage_ratio(self) -> float | None:
        if self.total_sentences == 0:
            return None
        return self.sentences_with_evidence / self.total_sentences

    @property
    def consistency_pass_rate(self) -> float | None:
        if self.machine_checked_sentences == 0:
            return None
        return self.machine_checked_passed / self.machine_checked_sentences

    @property
    def ai_acceptance_rate(self) -> float | None:
        """문서 단계: 재생성/직접수정을 거치지 않고 AI 초안이 그대로 남은 문장 비율."""
        if self.total_sentences == 0:
            return None
        return (self.total_sentences - self.user_edited_sentences) / self.total_sentences

    @property
    def interview_ai_acceptance_rate(self) -> float | None:
        """인터뷰 단계: 확정된 사실 중 AI가 제시한 초안(ai_draft_text) 그대로 확정된 비율."""
        if self.ai_draft_facts_total == 0:
            return None
        return self.ai_draft_facts_accepted / self.ai_draft_facts_total


def _aggregate(sentences: Sequence[GeneratedSentence], facts: Sequence[ConfirmedFact]) -> TrustStats:
    checked = [s for s in sentences if s.consistency_score is not None]
    draft_facts = [f for f in facts if f.ai_draft_text is not None]
    return TrustStats(
        total_sentences=len(sentences),
        sentences_with_evidence=sum(1 for s in sentences if s.evidence_fact_ids),
        machine_checked_sentences=len(checked),
        machine_checked_passed=sum(1 for s in checked if s.consistency_check_passed),
        user_edited_sentences=sum(1 for s in sentences if s.edited_by_user),
        ai_draft_facts_total=len(draft_facts),
        ai_draft_facts_accepted=sum(1 for f in draft_facts if f.content == f.ai_draft_text),
    )


async def _facts_for_categories(category_ids: set[uuid.UUID], db: AsyncSession) -> list[ConfirmedFact]:
    if not category_ids:
        return []
    stmt = select(ConfirmedFact).where(ConfirmedFact.category_id.in_(category_ids))
    return list((await db.execute(stmt)).scalars().all())


async def compute_document_trust(document_id: uuid.UUID, db: AsyncSession) -> TrustStats:
    """문서 하나(세션의 최신 버전)의 지표."""
    stmt = select(GeneratedSentence).where(GeneratedSentence.document_id == document_id)
    sentences = list((await db.execute(stmt)).scalars().all())
    category_ids = {s.category_id for s in sentences}
    facts = await _facts_for_categories(category_ids, db)
    return _aggregate(sentences, facts)


async def compute_global_trust(db: AsyncSession) -> TrustStats:
    """확정(FINAL)된 문서 전체를 대상으로 한 발표용 지표.

    DRAFT(아직 재검증/편집 중인) 문서를 섞으면 "아직 손보는 중"인 상태가 숫자를
    왜곡한다 — 발표 지표는 사용자가 최종적으로 내보낸 결과만 대표해야 한다.
    """
    final_ids = list(
        (await db.execute(select(GeneratedDocument.id).where(GeneratedDocument.status == "FINAL")))
        .scalars()
        .all()
    )
    if not final_ids:
        return _aggregate([], [])

    stmt = select(GeneratedSentence).where(GeneratedSentence.document_id.in_(final_ids))
    sentences = list((await db.execute(stmt)).scalars().all())
    category_ids = {s.category_id for s in sentences}
    facts = await _facts_for_categories(category_ids, db)
    return _aggregate(sentences, facts)
