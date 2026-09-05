from __future__ import annotations

import logging
from datetime import date

from app.core.config import settings
from app.services.llm.base import (
    AllProvidersFailedError,
    CategorySuggestion,
    ConfirmedFact,
    DraftDocument,
    DrilldownDecision,
    FactCandidate,
    InterviewContext,
    LLMProvider,
    PeriodSuggestion,
    ProviderUnavailableError,
    SufficiencyResult,
)
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.local_ollama import LocalOllamaProvider

logger = logging.getLogger(__name__)


def _build_providers() -> list[LLMProvider]:
    mapping: dict[str, LLMProvider] = {
        "local": LocalOllamaProvider(),
        "gemini": GeminiProvider(),
    }
    # .strip().lower() so a blank, differently-cased, or trailing-comma
    # LLM_PROVIDER_ORDER value can't silently produce an empty list — that
    # used to skip the per-provider try/except in FallbackProvider entirely
    # (loop body never runs), so AllProvidersFailedError fired instantly with
    # none of the failure logging below, making it indistinguishable from a
    # real outage in the logs (production incident, 2026-09-04).
    order = [p.strip().lower() for p in settings.llm_provider_order.split(",") if p.strip()]
    providers = [mapping[name] for name in order if name in mapping]
    if not providers:
        logger.error(
            "LLM_PROVIDER_ORDER=%r produced zero usable providers (expected some of %s) — "
            "every LLM call will fail instantly with AllProvidersFailedError",
            settings.llm_provider_order,
            list(mapping),
        )
    return providers


def get_llm_provider() -> LLMProvider:
    """FastAPI DI hook — routes should depend on this (not import FallbackProvider
    directly) so tests can override it with a fake, same pattern as
    get_storage / get_chunk_search / get_embedding_provider.
    """
    return FallbackProvider()


class FallbackProvider:
    def __init__(self, providers: list[LLMProvider] | None = None) -> None:
        self.providers = providers if providers is not None else _build_providers()

    def _log_failure(self, method: str, provider: LLMProvider, exc: Exception) -> None:
        # These get swallowed into a generic AllProvidersFailedError -> 503 by
        # design (spec: fall back silently to the next provider), but that
        # means the *why* is otherwise invisible in prod. Surfacing it here
        # (visible in Render's log stream) was the missing piece when
        # diagnosing the 2026-09-04 llm_unavailable incident.
        logger.warning("%s.%s failed: %s: %s", type(provider).__name__, method, type(exc).__name__, exc)

    async def draft_answer(self, context: InterviewContext, question_text: str) -> str:
        for provider in self.providers:
            try:
                return await provider.draft_answer(context, question_text)
            except (TimeoutError, ProviderUnavailableError) as exc:
                self._log_failure("draft_answer", provider, exc)
        raise AllProvidersFailedError()

    async def extract_facts(
        self, context: InterviewContext, question_text: str, answer_text: str, fact_type_hint: str
    ) -> list[FactCandidate]:
        for provider in self.providers:
            try:
                return await provider.extract_facts(context, question_text, answer_text, fact_type_hint)
            except (TimeoutError, ProviderUnavailableError) as exc:
                self._log_failure("extract_facts", provider, exc)
        raise AllProvidersFailedError()

    async def followup_question(self, context: InterviewContext) -> str:
        for provider in self.providers:
            try:
                return await provider.followup_question(context)
            except (TimeoutError, ProviderUnavailableError) as exc:
                self._log_failure("followup_question", provider, exc)
        raise AllProvidersFailedError()

    async def judge_sufficiency(self, context: InterviewContext) -> SufficiencyResult:
        for provider in self.providers:
            try:
                return await provider.judge_sufficiency(context)
            except (TimeoutError, ProviderUnavailableError) as exc:
                self._log_failure("judge_sufficiency", provider, exc)
        raise AllProvidersFailedError()

    async def judge_drilldown(self, context: InterviewContext) -> DrilldownDecision:
        for provider in self.providers:
            try:
                return await provider.judge_drilldown(context)
            except (TimeoutError, ProviderUnavailableError) as exc:
                self._log_failure("judge_drilldown", provider, exc)
        raise AllProvidersFailedError()

    async def extract_categories(
        self, free_text: str, gap_start: date, gap_end: date
    ) -> list[CategorySuggestion]:
        for provider in self.providers:
            try:
                return await provider.extract_categories(free_text, gap_start, gap_end)
            except (TimeoutError, ProviderUnavailableError) as exc:
                self._log_failure("extract_categories", provider, exc)
        raise AllProvidersFailedError()

    async def extract_period(self, free_text: str, today: date) -> PeriodSuggestion | None:
        # A provider returning None (couldn't confidently parse dates) is a
        # successful result, not a failure — it's returned immediately here,
        # same as extract_categories returning an empty list. Only an actual
        # exception triggers falling through to the next provider.
        for provider in self.providers:
            try:
                return await provider.extract_period(free_text, today)
            except (TimeoutError, ProviderUnavailableError) as exc:
                self._log_failure("extract_period", provider, exc)
        raise AllProvidersFailedError()

    async def generate_document(self, facts: list[ConfirmedFact], tone: str) -> DraftDocument:
        for provider in self.providers:
            try:
                return await provider.generate_document(facts, tone)
            except (TimeoutError, ProviderUnavailableError) as exc:
                self._log_failure("generate_document", provider, exc)
        raise AllProvidersFailedError()

    async def health_check(self) -> bool:
        for provider in self.providers:
            if await provider.health_check():
                return True
        return False
