from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, runtime_checkable


@dataclass
class RecordExcerpt:
    chunk_id: str
    text: str
    published_at: date | None


@dataclass
class BasedOn:
    """Source attribution for an extracted fact candidate."""
    type: str  # "record" | "generic_pattern"
    excerpts: list[RecordExcerpt] = field(default_factory=list)


@dataclass
class FactCandidate:
    content: str
    fact_type: str
    based_on: BasedOn


@dataclass
class SufficiencyResult:
    sufficient: bool
    reason: str


@dataclass
class DrilldownDecision:
    """Whether the answer just confirmed is worth an immediate, narrower
    follow-up before continuing — e.g. a base question answered with "기획과
    개발" (planning and development) is a candidate for drilling into one of
    those with a concrete-example question, rather than moving straight to
    the next, unrelated fixed question (2026-09-05 request)."""
    should_ask: bool
    question_text: str | None = None


@dataclass
class SentenceWithEvidence:
    text: str
    fact_indices: list[int]


@dataclass
class DraftDocument:
    sentences: list[SentenceWithEvidence]


@dataclass
class CategorySuggestion:
    category_type: str
    custom_label: str


@dataclass
class PeriodSuggestion:
    start_date: date
    end_date: date


@dataclass
class ConfirmedFact:
    id: str
    content: str
    source_type: str  # user_confirmed | user_edited | record_cited
    fact_type: str    # see app.models.confirmed_fact.FACT_TYPES


@dataclass
class InterviewContext:
    session_id: str
    category_label: str
    gap_start: date
    gap_end: date
    confirmed_facts_so_far: list[ConfirmedFact]
    record_excerpts: list[RecordExcerpt] = field(default_factory=list)
    asked_questions: list[str] = field(default_factory=list)


class ProviderUnavailableError(Exception):
    pass


class AllProvidersFailedError(Exception):
    pass


@runtime_checkable
class LLMProvider(Protocol):
    async def draft_answer(self, context: InterviewContext, question_text: str) -> str: ...
    async def extract_facts(
        self, context: InterviewContext, question_text: str, answer_text: str, fact_type_hint: str
    ) -> list[FactCandidate]: ...
    async def followup_question(self, context: InterviewContext) -> str: ...
    async def judge_sufficiency(self, context: InterviewContext) -> SufficiencyResult: ...
    async def judge_drilldown(self, context: InterviewContext) -> DrilldownDecision: ...
    async def generate_document(self, facts: list[ConfirmedFact], tone: str) -> DraftDocument: ...
    async def extract_categories(
        self, free_text: str, gap_start: date, gap_end: date
    ) -> list[CategorySuggestion]: ...
    async def extract_period(self, free_text: str, today: date) -> PeriodSuggestion | None: ...
    async def health_check(self) -> bool: ...
