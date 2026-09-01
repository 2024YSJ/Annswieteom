from __future__ import annotations

from app.core.config import settings
from app.services.llm.base import (
    AllProvidersFailedError,
    ConfirmedFact,
    DraftDocument,
    InterviewContext,
    LLMProvider,
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
