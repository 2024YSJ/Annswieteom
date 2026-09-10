from __future__ import annotations

from pydantic import BaseModel


class LLMHealthRead(BaseModel):
    """추론 서버 도달 여부를 운영자가 한 번에 확인하는 응답.

    `base_url_host`는 전체 URL이 아니라 호스트만 담는다 — 지금은 URL에 비밀이
    없지만 Cloudflare Access 토큰이 붙은 뒤로는 URL 주변이 자격증명 자리이고,
    운영자가 확인해야 하는 건 "어느 기계를 보고 있는가"뿐이다.
    """

    llm_reachable: bool
    embedding_reachable: bool
    model_name: str
    embedding_model_name: str
    base_url_host: str
