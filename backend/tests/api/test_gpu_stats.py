from __future__ import annotations

from app.main import app
from app.services.llm import get_llm_provider
from app.services.llm.base import LLMCallStats
from tests.api.conftest import FakeLLMProvider
from tests.api.test_document import _advance_to_result_generate, _register_and_login


class _FakeLLMProviderWithGpuStats(FakeLLMProvider):
    """FakeLLMProvider는 로컬 GPU 배지가 읽는 `generation_stats` 속성이 없다
    (실제 tok/s를 잴 방법이 없으니 당연하다) — 이 서브클래스는 그 속성을
    LocalOllamaProvider와 같은 모양으로 시뮬레이션해 API 응답 배선(document.py의
    _gpu_stats)이 실제로 값을 옮겨 담는지 확인한다."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.generation_stats: list[LLMCallStats] = []

    async def generate_document(self, facts, tone, category_label):
        result = await super().generate_document(facts, tone, category_label)
        self.generation_stats.append(
            LLMCallStats(label="generate_document", out_tokens=42, decode_seconds=2.0, tokens_per_second=21.0)
        )
        return result


def test_generate_response_carries_gpu_generation_stats(document_client):
    fake_llm = _FakeLLMProviderWithGpuStats()
    app.dependency_overrides[get_llm_provider] = lambda: fake_llm
    try:
        headers = _register_and_login(document_client)
        session_id = _advance_to_result_generate(document_client, headers, category_types=("part_time", "study"))

        resp = document_client.post(
            f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"}
        )
        assert resp.status_code == 201
        stats = resp.json()["generation_stats"]
        assert stats is not None
        assert stats["processed_locally"] is True
        # 두 카테고리 각각 generate_document를 한 번씩 호출하므로(document_generator.py) 2건이 쌓인다.
        assert stats["call_count"] == 2
        assert stats["total_output_tokens"] == 84
        assert stats["tokens_per_second"] == 21.0

        # 평범한 재조회(GET /document)에는 계측이 없다 — persist하지 않고 "방금
        # 생성한 응답에만" 실리는 게 의도된 동작이다.
        refetched = document_client.get(f"/api/v1/sessions/{session_id}/document", headers=headers)
        assert refetched.json()["generation_stats"] is None
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


def test_generate_response_has_no_gpu_stats_without_a_real_provider(document_client):
    """FakeLLMProvider(기본 document_client fixture)에는 generation_stats가 없다
    — getattr 폴백으로 조용히 None이어야지, 예외가 나면 안 된다."""
    headers = _register_and_login(document_client)
    session_id = _advance_to_result_generate(document_client, headers)

    resp = document_client.post(f"/api/v1/sessions/{session_id}/generate", headers=headers, json={"tone": "neutral"})
    assert resp.status_code == 201
    assert resp.json()["generation_stats"] is None
