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


class JobInfoDraftQueryRead(BaseModel):
    """`POST /job-search/draft-query-from-gap` 응답 — suggestion만, 미저장."""

    draft_query: str
