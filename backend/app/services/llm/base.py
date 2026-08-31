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
    """Source attribution for a draft suggestion."""
    type: str  # "record" | "generic_pattern"
    excerpts: list[RecordExcerpt] = field(default_factory=list)


@dataclass
class Suggestion:
    draft_text: str
    based_on: BasedOn


@dataclass
class SentenceWithEvidence:
    text: str
    fact_indices: list[int]


@dataclass
class DraftDocument:
    sentences: list[SentenceWithEvidence]


@dataclass
class ConfirmedFact:
    id: str
    content: str
    source_type: str  # user_confirmed | user_edited | record_cited
    fact_type: str    # frequency | task | achievement


@dataclass
class InterviewContext:
    session_id: str
    category_label: str
    gap_start: date
    gap_end: date
    confirmed_facts_so_far: list[ConfirmedFact]
    record_excerpts: list[RecordExcerpt] = field(default_factory=list)


class ProviderUnavailableError(Exception):
    pass


class AllProvidersFailedError(Exception):
    pass


@runtime_checkable
class LLMProvider(Protocol):
    async def draft_suggestion(self, context: InterviewContext, step: str) -> Suggestion: ...
    async def generate_document(self, facts: list[ConfirmedFact], tone: str) -> DraftDocument: ...
    async def health_check(self) -> bool: ...
