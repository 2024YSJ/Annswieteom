from app.services.llm.local_ollama import LocalOllamaProvider


def get_llm_provider() -> LocalOllamaProvider:
    """FastAPI DI 훅 — 라우터는 LocalOllamaProvider를 직접 import하지 말고
    이걸 의존성으로 받는다(테스트가 FakeLLMProvider로 갈아끼울 수 있게).

    2026-09-09 Gemini를 제거하기 전까지 이 훅은 services/llm/fallback.py에서
    FallbackProvider를 돌려줬다. 프로바이더가 로컬 Ollama 하나만 남으면서
    폴백 계층 자체가 사라졌고, 훅은 이 패키지 __init__으로 옮겼다
    (services/embedding/__init__.py의 get_embedding_provider와 같은 모양).
    이름과 시그니처는 그대로라 호출부는 import 경로만 바뀐다.
    """
    return LocalOllamaProvider()


__all__ = ["LocalOllamaProvider", "get_llm_provider"]
