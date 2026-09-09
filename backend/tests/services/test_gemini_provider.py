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


class _StubGeminiClient:
    """`_ensure_client()`가 돌려줄 가짜 클라이언트 — 넘어간 config를 기록한다."""

    def __init__(self, response_text: str) -> None:
        self.configs = []
        outer = self

        class _Models:
            async def generate_content(self, *, model, contents, config):
                outer.configs.append(config)
                return type("_Resp", (), {"text": response_text})()

        self.aio = type("_Aio", (), {"models": _Models()})()


@pytest.mark.asyncio
async def test_gemini_passes_temperature_to_config():
    # 온도를 지정하지 않으면 모델 기본값(~0.7)이 걸려 분류/판단 호출이 회차마다
    # 다른 답을 낸다 — Ollama 쪽과 같은 결함이라 여기도 같이 막는다(devlog 19).
    provider = GeminiProvider()
    provider._client = _StubGeminiClient('{"relevant_indices": []}')

    await provider.select_relevant_job_info_results("질문", "직업훈련과정", [])
    assert provider._client.configs == []  # 후보가 없으면 모델을 아예 안 부른다

    provider._client = _StubGeminiClient('{"categories": ["training_course"]}')
    await provider.classify_job_info_query("훈련과정 있어?")
    assert provider._client.configs[0].temperature == 0.0

    provider._client = _StubGeminiClient('{"draft_query": "카페 알바 경험 살릴 훈련과정"}')
    await provider.draft_job_info_query_from_facts([])
    assert provider._client.configs[0].temperature == 0.7
