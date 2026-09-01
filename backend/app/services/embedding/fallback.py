from __future__ import annotations

from app.core.config import settings
from app.services.embedding.base import (
    AllEmbeddingProvidersFailedError,
    EmbeddingDimensionMismatchError,
    EmbeddingProviderUnavailableError,
)
from app.services.embedding.gemini_embedding import GeminiEmbedding
from app.services.embedding.local_ollama_embedding import LocalOllamaEmbedding


def _build_providers() -> list:
    mapping = {
        "local": LocalOllamaEmbedding(),
        "gemini": GeminiEmbedding(),
    }
    order = [p.strip() for p in settings.llm_provider_order.split(",")]
    return [mapping[name] for name in order if name in mapping]


class FallbackEmbedding:
    """Tries providers in LLM_PROVIDER_ORDER order.

    EmbeddingDimensionMismatchError is NOT retried on the next provider —
    it signals a schema incompatibility that no provider can fix, and
    should be surfaced to the caller.
    """

    def __init__(self, providers: list | None = None) -> None:
        self.providers = providers if providers is not None else _build_providers()

    @property
    def model_name(self) -> str:
        for provider in self.providers:
            return provider.model_name
        return "none"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        last_error: Exception = AllEmbeddingProvidersFailedError("No providers configured")
        for provider in self.providers:
            try:
                return await provider.embed(texts)
            except EmbeddingDimensionMismatchError:
                raise  # dimension mismatch cannot be resolved by switching providers
            except (TimeoutError, EmbeddingProviderUnavailableError) as exc:
                last_error = exc
                continue
        raise AllEmbeddingProvidersFailedError(str(last_error)) from last_error

    async def health_check(self) -> bool:
        for provider in self.providers:
            if await provider.health_check():
                return True
        return False
