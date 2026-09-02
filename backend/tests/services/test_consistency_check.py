from __future__ import annotations

import pytest

from app.models.confirmed_fact import ConfirmedFact
from app.services.consistency_check import _cosine_similarity, check_sentence_consistency, max_cosine_similarity


class FakeEmbeddingProvider:
    """Deterministic stand-in — maps exact text to a fixed vector so
    similarity results are fully controlled by the test, no real
    Ollama/Gemini call involved.
    """

    model_name = "fake"

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vectors[t] for t in texts]

    async def health_check(self) -> bool:
        return True


def _fact(content: str) -> ConfirmedFact:
    return ConfirmedFact(content=content)


@pytest.mark.asyncio
async def test_empty_cited_facts_is_always_false():
    # No embedding provider needed — must short-circuit before any embed call.
    result = await check_sentence_consistency("아무 문장", [], embedding_provider=None)
    assert result is False


@pytest.mark.asyncio
async def test_unrelated_sentence_is_false():
    provider = FakeEmbeddingProvider({
        "무관한 문장": [1.0, 0.0],
        "근거 내용": [0.0, 1.0],
    })
    result = await check_sentence_consistency(
        "무관한 문장", [_fact("근거 내용")], embedding_provider=provider
    )
    assert result is False


@pytest.mark.asyncio
async def test_sentence_matching_a_fact_is_true():
    provider = FakeEmbeddingProvider({
        "근거를 그대로 요약": [1.0, 0.0],
        "근거 내용": [1.0, 0.0],
    })
    result = await check_sentence_consistency(
        "근거를 그대로 요약", [_fact("근거 내용")], embedding_provider=provider
    )
    assert result is True


@pytest.mark.asyncio
async def test_uses_max_similarity_across_multiple_cited_facts():
    provider = FakeEmbeddingProvider({
        "문장": [1.0, 0.0],
        "무관한 근거": [0.0, 1.0],
        "일치하는 근거": [1.0, 0.0],
    })
    result = await check_sentence_consistency(
        "문장",
        [_fact("무관한 근거"), _fact("일치하는 근거")],
        embedding_provider=provider,
    )
    assert result is True


@pytest.mark.asyncio
async def test_max_cosine_similarity_returns_the_highest_score():
    provider = FakeEmbeddingProvider({
        "문장": [1.0, 0.0],
        "낮음": [0.0, 1.0],
        "높음": [1.0, 0.0],
    })
    score = await max_cosine_similarity("문장", ["낮음", "높음"], embedding_provider=provider)
    assert score == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_identical_vectors_is_one():
    assert _cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_similarity_zero_vector_does_not_raise():
    assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
