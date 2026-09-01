from __future__ import annotations

from typing import Protocol, runtime_checkable


class EmbeddingProviderUnavailableError(Exception):
    pass


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


class AllEmbeddingProvidersFailedError(Exception):
    pass


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def health_check(self) -> bool: ...
