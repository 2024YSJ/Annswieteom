from __future__ import annotations

from typing import Protocol, runtime_checkable


class EmbeddingUnavailableError(Exception):
    """로컬 Ollama bge-m3로 임베딩을 못 만든 경우(타임아웃 포함).

    llm/base.py의 LLMUnavailableError와 같은 이유로 합쳤다 — Gemini 임베딩을
    제거하면서 프로바이더가 하나가 됐다. 애초에 Gemini 임베딩은 768차원이라
    EMBEDDING_DIM(1024)과 안 맞아 호출되는 족족 실패했으므로, 이 제거로
    실제 동작이 바뀌는 경로는 없다.
    """


class EmbeddingDimensionMismatchError(Exception):
    """Raised when a provider returns vectors of unexpected dimension."""
    def __init__(self, expected: int, got: int, model: str) -> None:
        super().__init__(
            f"Embedding dimension mismatch: expected {expected}, got {got} from {model}. "
            "Cannot store mismatched vectors in VECTOR(1024) column."
        )
        self.expected = expected
        self.got = got
        self.model = model


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def health_check(self) -> bool: ...
