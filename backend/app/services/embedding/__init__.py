from app.services.embedding.fallback import FallbackEmbedding


def get_embedding_provider() -> FallbackEmbedding:
    """FastAPI DI hook — lets routes (and the services they call, like
    document_generator's consistency check) swap in a fake embedding
    provider in tests instead of hitting real Ollama/Gemini, same pattern
    as get_llm_provider / get_chunk_search / get_storage.
    """
    return FallbackEmbedding()


__all__ = ["FallbackEmbedding", "get_embedding_provider"]
