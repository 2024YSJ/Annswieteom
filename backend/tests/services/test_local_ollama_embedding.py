from __future__ import annotations

import pytest

from app.models.record_chunk import EMBEDDING_DIM
from app.services.embedding import local_ollama_embedding
from app.services.embedding.local_ollama_embedding import LocalOllamaEmbedding


@pytest.mark.asyncio
async def test_embed_pins_keep_alive(monkeypatch):
    # 없으면 Ollama 기본값(5분)이 걸려 잠깐 쉬면 bge-m3 재적재부터 기다린다.
    sent: list[dict] = []

    class _Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"embeddings": [[0.0] * EMBEDDING_DIM]}

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info) -> None:
            return None

        async def post(self, url: str, json: dict, headers: dict | None = None):  # noqa: A002 - httpx의 인자명
            sent.append(json)
            return _Resp()

    monkeypatch.setattr(local_ollama_embedding.httpx, "AsyncClient", _Client)

    await LocalOllamaEmbedding().embed(["문장"])

    assert sent[0]["keep_alive"] == -1
    assert sent[0]["model"] == "bge-m3"
