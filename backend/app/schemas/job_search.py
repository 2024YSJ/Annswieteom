from __future__ import annotations

from pydantic import BaseModel


class JobInfoQueryRequest(BaseModel):
    query: str
    #: 이전 사용자 발화 원문만(가장 오래된 것부터), 구조화된 파라미터는 안 담는다 —
    #: 프론트가 이미 로컬로 들고 있는 turns를 그대로 잘라 보낸다. 백엔드는 세션에
    #: 아무것도 저장하지 않으므로(무상태 대화) 이게 유일한 맥락 전달 경로다
    #: (devlog 44, "그럼 서울도 같이 봐줘" 같은 후속 질문 지원).
    history: list[str] = []


class JobInfoResultRead(BaseModel):
    title: str
    subtitle: str
    meta_lines: list[str]
    detail_url: str | None = None


class JobInfoCategoryResultRead(BaseModel):
    category: str
    category_label: str
    results: list[JobInfoResultRead]
    #: 처음 조건(지역/키워드)대로는 결과가 모자라 조건을 일부 풀고 다시 조회했을
    #: 때만 true — 실제 챗봇이라면 "조건을 넓혀서 찾아봤다"를 사용자에게 설명해야
    #: 한다(devlog 44).
    broadened: bool = False


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
