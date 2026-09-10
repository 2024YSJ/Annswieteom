from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.schemas.health import LLMHealthRead
from app.services.embedding import get_embedding_provider
from app.services.embedding.base import EmbeddingProvider
from app.services.llm import get_llm_provider
from app.services.llm.base import LLMProvider

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/llm", response_model=LLMHealthRead)
async def llm_health(
    llm: LLMProvider = Depends(get_llm_provider),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
) -> LLMHealthRead:
    """추론 서버가 이 백엔드에서 실제로 닿는지 확인한다.

    왜 필요한가: 폴백이 없으므로(2026-09-09 Gemini 제거) 이 서버가 죽으면 AI
    기능 전체가 멈춘다. 그런데 그 사실을 지금은 사용자가 인터뷰 중간에 503을
    맞고 나서야 알게 된다. 두 프로바이더에 `health_check()`가 있었지만 호출하는
    곳이 없었다.

    노트북에서 터널로 직접 curl하는 것과는 **다른 경로**를 검사한다는 점이
    핵심이다. 실제 경로는 Render → Cloudflare(Access) → Spark이고, 그 경로에는
    Render의 환경변수(모델 이름, Access 토큰)까지 얽혀 있다. 여기가 유일하게
    그 전체를 한 요청으로 확인하는 지점이다.

    **항상 200을 돌려준다.** 상태는 본문에 담는다 — 운영자용 프로브가 503을
    내면 "AI 서버만 죽었다"와 "앱 전체가 죽었다"를 구분할 수 없어져서 정확히
    쓸모가 없어진다.

    `app/main.py`의 `/health`와 절대 합치지 않는다. 그건 Render의 플랫폼
    liveness probe라서 의존성 없이 즉시 답해야 한다. 거기서 터널을 호출하기
    시작하면 Spark 장애가 서비스 재시작 루프로 번져 부분 장애가 전체 장애가
    된다. 이 분리가 이 엔드포인트 설계의 핵심이다.

    인증을 걸지 않았다. 데모 중 담당자가 JWT 없이 휴대폰으로 확인할 수 있어야
    하고, 노출되는 값은 명세서에 이미 적혀 있는 모델 이름과 호스트명뿐이다.
    """
    llm_ok, embedding_ok = await asyncio.gather(
        llm.health_check(),
        embedding_provider.health_check(),
    )
    return LLMHealthRead(
        llm_reachable=bool(llm_ok),
        embedding_reachable=bool(embedding_ok),
        model_name=settings.local_llm_model_name,
        embedding_model_name=embedding_provider.model_name,
        base_url_host=urlparse(settings.local_llm_base_url).netloc,
    )
