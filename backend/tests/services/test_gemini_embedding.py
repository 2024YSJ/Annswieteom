from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.embedding.base import EmbeddingProviderUnavailableError
from app.services.embedding.gemini_embedding import GeminiEmbedding


@pytest.fixture
def blank_gemini_key(monkeypatch):
    # Same bug as GeminiProvider (services/llm/gemini_provider.py): eager
    # genai.Client(api_key="") raised synchronously in __init__, which
    # FallbackEmbedding._build_providers() calls unconditionally. Unlike the
    # chat-completion path, none of /generate, /document/regenerate, or
    # /sentences/{id}/regenerate wrap Depends(get_embedding_provider) in a
    # try/except, so this crashed those endpoints with a bare 500 on
    # production whenever GEMINI_API_KEY was blank (2026-09-04).
    monkeypatch.setattr(settings, "gemini_api_key", "")


def test_construction_does_not_raise_with_blank_api_key(blank_gemini_key):
    GeminiEmbedding()  # must not raise


@pytest.mark.asyncio
async def test_embed_with_blank_api_key_raises_provider_unavailable(blank_gemini_key):
    provider = GeminiEmbedding()
    with pytest.raises(EmbeddingProviderUnavailableError):
        await provider.embed(["hello"])
