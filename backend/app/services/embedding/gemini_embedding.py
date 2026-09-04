from __future__ import annotations

# Gemini text-embedding-004 is capped at 768 dims, which does NOT match the
# VECTOR(1024) column (bge-m3 output). This provider intentionally raises
# EmbeddingDimensionMismatchError so the fallback layer can surface the
# problem clearly rather than silently storing wrong-sized vectors.
#
# Resolution options (discuss with B before changing the DB schema):
#   A) Switch to a Gemini model that supports output_dimensionality=1024
#      (e.g. gemini-embedding-exp-03-07 if it reaches GA with 1024-dim support)
#   B) Migrate record_chunks.embedding to VECTOR(768) and rebuild ivfflat index
#   C) Queue embedding jobs for retry instead of falling back to Gemini

from google import genai

from app.core.config import settings
from app.models.record_chunk import EMBEDDING_DIM
from app.services.embedding.base import (
    EmbeddingDimensionMismatchError,
    EmbeddingProviderUnavailableError,
)

_MODEL = "models/text-embedding-004"
_GEMINI_DIM = 768  # hard ceiling for text-embedding-004


class GeminiEmbedding:
    """Gemini text-embedding-004 — KNOWN dimension mismatch (768 vs 1024)."""

    def __init__(self) -> None:
        # Lazy, same reasoning as GeminiProvider (services/llm/gemini_provider.py):
        # genai.Client(api_key="") raises ValueError synchronously, and
        # FallbackEmbedding._build_providers() constructs every configured
        # provider unconditionally — for the /generate, /document/regenerate,
        # and /sentences/{id}/regenerate endpoints, that construction happens
        # directly in a FastAPI dependency (Depends(get_embedding_provider))
        # with no surrounding try/except, so a blank GEMINI_API_KEY crashed
        # the request with a bare 500 instead of falling back to local
        # embeddings (production incident, 2026-09-04 — this endpoint has no
        # equivalent to interview.py's broad `except Exception: excerpts = []`
        # around its own FallbackEmbedding() use, which is why that path never
        # surfaced this).
        self._client: genai.Client | None = None

    def _ensure_client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(api_key=settings.gemini_api_key)
        return self._client

    @property
    def model_name(self) -> str:
        return _MODEL

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not settings.gemini_api_key:
            raise EmbeddingProviderUnavailableError("GEMINI_API_KEY not set")

        # Raise immediately — see module docstring for resolution options.
        if _GEMINI_DIM != EMBEDDING_DIM:
            raise EmbeddingDimensionMismatchError(EMBEDDING_DIM, _GEMINI_DIM, _MODEL)

        try:
            client = self._ensure_client()
            vectors: list[list[float]] = []
            for text in texts:
                result = await client.aio.models.embed_content(
                    model=_MODEL,
                    contents=text,
                )
                vectors.append(list(result.embeddings[0].values))
            return vectors
        except Exception as exc:
            raise EmbeddingProviderUnavailableError(f"Gemini embedding failed: {exc}") from exc

    async def health_check(self) -> bool:
        return bool(settings.gemini_api_key)
