from __future__ import annotations

from datetime import date

import pytest

from app.core.config import settings
from app.services.llm.base import ProviderUnavailableError
from app.services.llm.gemini_provider import GeminiProvider


@pytest.fixture
def blank_gemini_key(monkeypatch):
    # genai.Client(api_key="") raises ValueError synchronously — this used to
    # happen in GeminiProvider.__init__, which FallbackProvider._build_providers()
    # calls unconditionally regardless of LLM_PROVIDER_ORDER. Because that
    # construction happens during FastAPI dependency resolution (before any
    # endpoint's own try/except runs), the ValueError escaped as a bare 500
    # with no CORS headers instead of the graceful per-provider fallback every
    # other failure mode gets (production bug, 2026-09-04: a missing/blank
    # GEMINI_API_KEY broke every AI-touching endpoint this way).
    monkeypatch.setattr(settings, "gemini_api_key", "")


def test_construction_does_not_raise_with_blank_api_key(blank_gemini_key):
    GeminiProvider()  # must not raise


@pytest.mark.asyncio
async def test_call_with_blank_api_key_raises_provider_unavailable(blank_gemini_key):
    provider = GeminiProvider()
    with pytest.raises(ProviderUnavailableError):
        await provider.extract_period("작년 1월부터 3월까지", date.today())
