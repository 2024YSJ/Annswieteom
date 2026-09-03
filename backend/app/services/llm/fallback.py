from __future__ import annotations

from datetime import date

from app.core.config import settings
from app.services.llm.base import (
    AllProvidersFailedError,
    CategorySuggestion,
    ConfirmedFact,
    DraftDocument,
    InterviewContext,
    LLMProvider,
    PeriodSuggestion,
    ProviderUnavailableError,
    Suggestion,
)
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.local_ollama import LocalOllamaProvider


def _build_providers() -> list[LLMProvider]:
    mapping: dict[str, LLMProvider] = {
        "local": LocalOllamaProvider(),
        "gemini": GeminiProvider(),
    }
    order = [p.strip() for p in settings.llm_provider_order.split(",")]
    return [mapping[name] for name in order if name in mapping]


class FallbackProvider:
    def __init__(self, providers: list[LLMProvider] | None = None) -> None:
        self.providers = providers if providers is not None else _build_providers()

    async def draft_suggestion(self, context: InterviewContext, step: str) -> Suggestion:
        for provider in self.providers:
            try:
                return await provider.draft_suggestion(context, step)
            except (TimeoutError, ProviderUnavailableError):
                continue
        raise AllProvidersFailedError()

    async def extract_categories(
        self, free_text: str, gap_start: date, gap_end: date
    ) -> list[CategorySuggestion]:
        for provider in self.providers:
            try:
                return await provider.extract_categories(free_text, gap_start, gap_end)
            except (TimeoutError, ProviderUnavailableError):
                continue
        raise AllProvidersFailedError()

    async def extract_period(self, free_text: str, today: date) -> PeriodSuggestion | None:
        # A provider returning None (couldn't confidently parse dates) is a
        # successful result, not a failure — it's returned immediately here,
        # same as extract_categories returning an empty list. Only an actual
        # exception triggers falling through to the next provider.
        for provider in self.providers:
            try:
                return await provider.extract_period(free_text, today)
            except (TimeoutError, ProviderUnavailableError):
                continue
        raise AllProvidersFailedError()

    async def generate_document(self, facts: list[ConfirmedFact], tone: str) -> DraftDocument:
        for provider in self.providers:
            try:
                return await provider.generate_document(facts, tone)
            except (TimeoutError, ProviderUnavailableError):
                continue
        raise AllProvidersFailedError()

    async def health_check(self) -> bool:
        for provider in self.providers:
            if await provider.health_check():
                return True
        return False
