from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.models.confirmed_fact import ConfirmedFact
from app.services.embedding import LocalOllamaEmbedding
from app.services.embedding.base import EmbeddingProvider


@dataclass(frozen=True)
class ConsistencyResult:
    passed: bool
    #: 판정에 쓰인 실제 최대 코사인 유사도. 인용 근거가 아예 없어 검사를
    #: 수행조차 못 한 경우에만 None.
    score: float | None


async def evaluate_sentence_consistency(
    sentence: str,
    cited_facts: list[ConfirmedFact],
    embedding_provider: EmbeddingProvider | None = None,
) -> ConsistencyResult:
    """정직성 가드레일의 마지막 방어선 (12-4절).

    confirmed_facts만 프롬프트 입력으로 강제하는 것만으로는 LLM이 지시를
    무시하고 사실무근인 내용을 지어낼 가능성을 막지 못한다 — 생성된 문장이
    실제로 인용한 근거들과 의미상 가깝다고 사후에 확인하는 게 이 함수의 역할.

    유사도 실수값을 함께 돌려주는 이유(2026-09-09): 예전에는 bool만 남기고
    점수를 버려서, 실패한 문장이 임계값 바로 아래였는지(0.54) 완전히 딴소리였는지
    (0.11) 구분할 수 없었다. settings.consistency_threshold를 실제 샘플에 맞춰
    조정하려면 이 분포가 있어야 한다.

    embedding_provider는 문서 생성 오케스트레이션에서는 생략하고 기본
    LocalOllamaEmbedding()을 쓰면 되고, 테스트에서만 실제 Ollama/Gemini 없이
    검증하기 위해 주입한다.
    """
    if not cited_facts:
        return ConsistencyResult(passed=False, score=None)

    similarity = await max_cosine_similarity(
        sentence,
        [f.content for f in cited_facts],
        embedding_provider,
    )
    return ConsistencyResult(passed=similarity >= settings.consistency_threshold, score=similarity)


async def check_sentence_consistency(
    sentence: str,
    cited_facts: list[ConfirmedFact],
    embedding_provider: EmbeddingProvider | None = None,
) -> bool:
    """`evaluate_sentence_consistency`의 bool만 필요한 호출자를 위한 얇은 래퍼."""
    result = await evaluate_sentence_consistency(sentence, cited_facts, embedding_provider)
    return result.passed


async def max_cosine_similarity(
    sentence: str,
    fact_contents: list[str],
    embedding_provider: EmbeddingProvider | None = None,
) -> float:
    if not fact_contents:
        return 0.0

    provider = embedding_provider or LocalOllamaEmbedding()
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
