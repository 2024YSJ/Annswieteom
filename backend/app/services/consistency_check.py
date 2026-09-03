from __future__ import annotations

from app.core.config import settings
from app.models.confirmed_fact import ConfirmedFact
from app.services.embedding import FallbackEmbedding
from app.services.embedding.base import EmbeddingProvider


async def check_sentence_consistency(
    sentence: str,
    cited_facts: list[ConfirmedFact],
    embedding_provider: EmbeddingProvider | None = None,
) -> bool:
    """정직성 가드레일의 마지막 방어선 (12-4절).

    confirmed_facts만 프롬프트 입력으로 강제하는 것만으로는 LLM이 지시를
    무시하고 사실무근인 내용을 지어낼 가능성을 막지 못한다 — 생성된 문장이
    실제로 인용한 근거들과 의미상 가깝다고 사후에 확인하는 게 이 함수의 역할.

    embedding_provider는 문서 생성 오케스트레이션에서는 생략하고 기본
    FallbackEmbedding()을 쓰면 되고, 테스트에서만 실제 Ollama/Gemini 없이
    검증하기 위해 주입한다.
    """
    if not cited_facts:
        return False

    similarity = await max_cosine_similarity(
        sentence,
        [f.content for f in cited_facts],
        embedding_provider,
    )
    return similarity >= settings.consistency_threshold


async def max_cosine_similarity(
    sentence: str,
    fact_contents: list[str],
    embedding_provider: EmbeddingProvider | None = None,
) -> float:
    if not fact_contents:
        return 0.0

    provider = embedding_provider or FallbackEmbedding()
    vectors = await provider.embed([sentence, *fact_contents])
    sentence_vector, fact_vectors = vectors[0], vectors[1:]
    return max(_cosine_similarity(sentence_vector, v) for v in fact_vectors)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
