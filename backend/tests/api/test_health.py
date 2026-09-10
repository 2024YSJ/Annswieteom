from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.embedding import get_embedding_provider
from app.services.llm import get_llm_provider

from tests.api.conftest import FakeEmbeddingProvider, FakeLLMProvider


class _UnreachableLLM(FakeLLMProvider):
    async def health_check(self) -> bool:
        return False


class _UnreachableEmbedding(FakeEmbeddingProvider):
    async def health_check(self) -> bool:
        return False


@pytest.fixture
def health_client():
    """DB를 안 쓰는 엔드포인트라 client 픽스처(SQLite 셋업)가 필요 없다."""
    llm = FakeLLMProvider()
    embedding = FakeEmbeddingProvider()
    app.dependency_overrides[get_llm_provider] = lambda: llm
    app.dependency_overrides[get_embedding_provider] = lambda: embedding
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_reports_both_providers_reachable(health_client):
    resp = health_client.get("/api/v1/health/llm")

    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_reachable"] is True
    assert body["embedding_reachable"] is True
    assert body["model_name"] == settings.local_llm_model_name
    assert body["embedding_model_name"] == "fake"


def test_unreachable_provider_still_returns_200(health_client):
    # 운영자용 프로브가 503을 내면 "AI 서버만 죽었다"와 "앱 전체가 죽었다"를
    # 구분할 수 없어진다 — 상태는 본문으로만 알린다.
    app.dependency_overrides[get_llm_provider] = lambda: _UnreachableLLM()
    app.dependency_overrides[get_embedding_provider] = lambda: _UnreachableEmbedding()

    resp = health_client.get("/api/v1/health/llm")

    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_reachable"] is False
    assert body["embedding_reachable"] is False


def test_never_exposes_the_full_base_url(health_client, monkeypatch):
    # Access 토큰이 붙은 뒤로는 URL 주변이 자격증명 자리다. 운영자가 알아야 하는
    # 건 "어느 기계를 보고 있는가"뿐이므로 호스트만 내려준다.
    monkeypatch.setattr(settings, "local_llm_base_url", "https://llm.example.com/some/path")

    body = health_client.get("/api/v1/health/llm").json()

    assert body["base_url_host"] == "llm.example.com"
    assert "/some/path" not in str(body)


def test_platform_liveness_probe_stays_dependency_free(health_client):
    # app/main.py의 /health는 Render의 liveness probe다. 여기서 터널을 호출하기
    # 시작하면 Spark 장애가 서비스 재시작 루프로 번져 부분 장애가 전체 장애가
    # 된다. 이 엔드포인트가 LLM 상태와 무관하게 즉시 ok를 주는지 고정해둔다.
    app.dependency_overrides[get_llm_provider] = lambda: _UnreachableLLM()
    app.dependency_overrides[get_embedding_provider] = lambda: _UnreachableEmbedding()

    resp = health_client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
