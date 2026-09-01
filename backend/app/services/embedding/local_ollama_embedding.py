from __future__ import annotations

import httpx

from app.core.config import settings
from app.models.record_chunk import EMBEDDING_DIM
from app.services.embedding.base import (
    EmbeddingDimensionMismatchError,
    EmbeddingProviderUnavailableError,
)

_MODEL = "bge-m3"


class LocalOllamaEmbedding:
    """Ollama bge-m3 embedding via /api/embed (batch-capable, Ollama 0.3+)."""

    @property
    def model_name(self) -> str:
        return _MODEL

    async def embed(self, texts: list[str]) -> list[list[float]]:
        base_url = settings.local_llm_base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{base_url}/api/embed",
                    json={"model": _MODEL, "input": texts},
                )
                resp.raise_for_status()
                vectors: list[list[float]] = resp.json()["embeddings"]
        except httpx.TimeoutException as exc:
            raise TimeoutError("Ollama embedding timed out") from exc
        except Exception as exc:
            raise EmbeddingProviderUnavailableError(f"Ollama unavailable: {exc}") from exc

        if vectors and len(vectors[0]) != EMBEDDING_DIM:
            raise EmbeddingDimensionMismatchError(EMBEDDING_DIM, len(vectors[0]), _MODEL)

        return vectors

    async def health_check(self) -> bool:
        base_url = settings.local_llm_base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False
