from __future__ import annotations

from pydantic import BaseModel


class JobInfoQueryRequest(BaseModel):
    query: str


class JobInfoResultRead(BaseModel):
    title: str
    subtitle: str
    meta_lines: list[str]
    detail_url: str | None = None


class JobInfoCategoryResultRead(BaseModel):
    category: str
    category_label: str
    results: list[JobInfoResultRead]


class JobInfoQueryRead(BaseModel):
    """`POST /job-search/query` 응답 — 한 번의 자유 텍스트 질문이 여러
    카테고리에 동시에 걸릴 수 있어 categories가 리스트다. 관련 카테고리를
    하나도 못 찾으면 categories는 빈 배열이고 clarification_question이
    채워진다(재질문 패턴, devlog 14와 동일 철학)."""

    categories: list[JobInfoCategoryResultRead]
    clarification_question: str | None = None
    #: 조회나 관련성 판단이 실패/시간초과해서 이번 응답에서 빠진 카테고리 라벨.
    #: 예전에는 그냥 버려서 사용자에게 "AI가 아무 말도 안 하는" 빈 응답으로
    #: 보였다 — 무엇이 빠졌는지 알려주려면 응답에 실려야 한다(devlog 20).
    skipped_category_labels: list[str] = []
    #: 질문의 일부가 6개 카테고리 중 어디에도 해당하지 않을 때(예: 아르바이트/
    #: 파트타임 채용정보 — 이 앱이 다루는 고용24 엔드포인트 중엔 없다) 그게
    #: 뭔지 설명하는 문구. skipped_category_labels("골랐지만 조회 실패")와 달리
    #: 애초에 다루지 않는 개념이라는 뜻이다(devlog 41).
    unsupported_note: str | None = None


class JobInfoDraftQueryRead(BaseModel):
    """`POST /job-search/draft-query-from-gap` 응답 — suggestion만, 미저장."""

    draft_query: str
