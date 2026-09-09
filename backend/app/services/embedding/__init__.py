from app.services.embedding.local_ollama_embedding import LocalOllamaEmbedding


def get_embedding_provider() -> LocalOllamaEmbedding:
    """FastAPI DI 훅 — 테스트가 실제 Ollama 대신 가짜 임베딩을 주입할 수 있게
    라우터/서비스가 이걸 거친다. get_llm_provider와 같은 컨벤션.

    Gemini 임베딩 제거 전까지는 FallbackEmbedding을 돌려줬지만, Gemini는
    768차원이라 EMBEDDING_DIM(1024)과 안 맞아 호출될 때마다
    EmbeddingDimensionMismatchError로 즉시 실패했다 — 폴백이 이름만 폴백이었다.
    이제 로컬 bge-m3 하나뿐이라는 사실을 코드가 그대로 드러낸다.
    """
    return LocalOllamaEmbedding()


__all__ = ["LocalOllamaEmbedding", "get_embedding_provider"]
