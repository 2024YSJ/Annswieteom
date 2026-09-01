"""
임베딩 파이프라인 검증 스크립트.
사용법: cd backend && python scripts/verify_embedding.py
"""
import asyncio
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.services.embedding.local_ollama_embedding import LocalOllamaEmbedding


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x ** 2 for x in a))
    mag_b = math.sqrt(sum(x ** 2 for x in b))
    return dot / (mag_a * mag_b) if mag_a and mag_b else 0.0


async def main() -> None:
    provider = LocalOllamaEmbedding()

    print(f"Model: {provider.model_name}")
    print(f"Health check: {await provider.health_check()}\n")

    sentences = [
        "편의점에서 아르바이트를 하며 고객 응대 경험을 쌓았다.",  # A
        "카페 파트타임으로 일하면서 서비스 스킬을 익혔다.",       # B — A와 의미 유사
        "파이썬으로 머신러닝 모델을 개발하고 배포했다.",          # C — 전혀 다른 주제
    ]

    print("임베딩 생성 중...")
    vectors = await provider.embed(sentences)

    dim = len(vectors[0])
    print(f"벡터 차원: {dim}  (기대값: 1024)")
    assert dim == 1024, f"차원 불일치! {dim}"

    sim_ab = cosine_similarity(vectors[0], vectors[1])
    sim_ac = cosine_similarity(vectors[0], vectors[2])

    print(f"\n코사인 유사도:")
    print(f"  A↔B (비슷한 주제): {sim_ab:.4f}")
    print(f"  A↔C (다른 주제):   {sim_ac:.4f}")

    if sim_ab > sim_ac:
        print("\n✓ 의미가 비슷한 문장끼리 유사도가 더 높습니다.")
    else:
        print("\n✗ 유사도 순서가 예상과 다릅니다. 모델을 확인하세요.")


if __name__ == "__main__":
    asyncio.run(main())
