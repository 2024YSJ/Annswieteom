# 일자리 찾기 + 공백기 결과 연동

Phase 1~5 로드맵과 마찬가지로 원래 마일스톤 체크리스트에는 없던 항목. 대화형으로 계획한 뒤 착수했고(계획 파일 자체는 저장소 밖에 있었음), 이 문서는 그 계획을 실제 구현 시점 기준으로 정리한 설계 기록이다. 대응하는 devlog: [PersonB/11_job_search_backend.md](../devlog/PersonB/11_job_search_backend.md), [PersonB/12_job_search_frontend.md](../devlog/PersonB/12_job_search_frontend.md).

## 목표

1. **일자리 찾기**: 대화형으로 희망 급여/근무지/학력·경력/업무 스타일을 받아 구인 API를 조회하고, 결과를 그대로 나열하지 않고 LLM으로 적합도(fit)를 판단해 보여준다.
2. **연동**: 공백기 채우기 결과(확정된 사실)를 일자리 찾기 입력의 시드로 재사용한다.
3. **확인 단계 CRUD**: 카테고리/후보 목록처럼, AI가 제안하고 사용자가 확인하는 지점은 두 플로우 모두에서 추가/삭제/수정이 가능해야 한다 — 조사 결과 기존 공백기 채우기 플로우(카테고리 선택 후보, 활동 세부 분할 후보, 사실 확인 후보)는 이미 이 요구를 충족하고 있었으므로, 신규 작업은 일자리 찾기 쪽 확인 단계(선호도 확인)에만 필요했다.

## 아키텍처 — 같은 `Session`, 다른 `kind`

완전히 새 테이블/상태머신을 만드는 대신 기존 `sessions` 테이블에 `kind`(`"gap_fill"` | `"job_search"`)와 `linked_gap_session_id`(연동 출처, 자기참조 FK, `SET NULL`)를 추가하고, `status` CHECK 제약에 job-search 전용 3개 상태(`JOB_PREFERENCES_INPUT`/`JOB_SEARCHING`/`JOB_RESULTS_REVIEW`)를 얹었다. 두 플로우는 `status` 컬럼만 공유할 뿐 전이 규칙은 완전히 분리돼 있다 — `interview_orchestrator.py`(공백기 채우기 전용)를 건드리지 않고 `app/api/job_search.py` 안에 자체 `_require_status` 헬퍼를 뒀다.

프론트도 마찬가지로 `app/sessions/[id]/page.tsx`가 세션의 `kind`(사이드바가 이미 불러온 `useSessionsList()` 캐시에서 조회)에 따라 완전히 다른 컴포넌트 트리(`JobSearchChatPage` vs 기존 공백기 채우기 트리)로 분기한다.

## 백엔드

- **LLM 어댑터 신규 능력 3개** (`app/services/llm/base.py`/`fallback.py`/`local_ollama.py`/`gemini_provider.py`, 기존 `judge_sufficiency` 등과 동일한 Protocol+Jinja 프롬프트 패턴):
  - `extract_job_preferences(free_text) -> JobPreferences` — 자유 텍스트에서 구조화된 선호도 추출. 언급 안 된 항목은 절대 추측하지 않고 null/빈 배열.
  - `judge_job_fit(preferences, posting) -> JobFitResult` — bool(`fit`) + 이유 한 줄. 사용자가 언급 안 한 항목은 판단 기준에서 제외.
  - `infer_job_preferences_from_facts(confirmed_facts) -> JobPreferenceInferenceResult` — 연동용. `work_style_tags`/`keyword_hints`/`notes`만 있고 급여·근무지 필드 자체가 없다(STAR 사실만으로 유추 불가능하므로).
- **고용24 채용정보 API 클라이언트** (`app/services/job_pipeline/worknet_client.py`) — `httpx` + `Settings` + DI 팩토리(`storage.py`와 동일 패턴), XML은 표준 라이브러리 `xml.etree.ElementTree`로 파싱. 사람인(승인 대기+일 500회 제한)·잡코리아(공공기관/학교 우선)보다 즉시 발급이 가능해 v1 단일 소스로 선택. 지역/학력/경력 코드 매핑은 후속 과제로 미루고 자유 텍스트를 `keyword` 파라미터로 검색.
- **엔드포인트** (`app/api/job_search.py`, prefix `/sessions`):
  - `GET /{id}/job-search` — 상태+선호도+캐시된 검색 결과 조회(외부 API 재호출 없음, 새로고침용).
  - `POST /{id}/job-search/preferences/extract` — 제안만 반환, 미저장.
  - `POST /{id}/job-search/preferences` — 확정 저장.
  - `POST /{id}/job-search/search` — 고용24 최대 15건 조회 → `asyncio.Semaphore(4)`로 병렬 `judge_job_fit` → fit 우선 정렬 → 캐시.
  - `POST /{id}/job-search/seed-from-gap` — 연동 출처 세션 소유자 확인 후 `infer_job_preferences_from_facts` 호출, 제안만 반환.
  - `POST /sessions`를 확장해 `kind`/`linked_gap_session_id`를 받음(기본값 있어 기존 호출 하위 호환).

## 프론트

- **첫 화면 분기** (`app/page.tsx`): 세션 0개인 사용자는 "공백기 채우기"/"일자리 찾기" 선택 화면을 본다(기존의 "세션 없으면 자동 생성" 동작을 제거) — 세션이 있으면 기존처럼 최근 세션으로 자동 이동.
- **사이드바** (`app/sessions/layout.tsx`): kind별 두 섹션으로 그룹핑, 각각 별도 "+ 새로 시작" 버튼과 status 라벨 세트(`GAP_FILL_STATUS_LABELS`/`JOB_SEARCH_STATUS_LABELS`).
- **`JobSearchPreferencesSection`**: 기존 `PeriodSection`(스칼라 폼 프리필→확정) + `CategorySection`(로컬 배열 인라인 편집+삭제+추가) 패턴을 그대로 재사용 — 급여/근무지/학력/경력은 폼 필드, `work_style_tags`는 태그 칩. 연동된 세션이면 마운트 시 자동으로 `seed-from-gap` 호출.
- **`JobSearchResultsSection`**: `ResultSection`의 `generateFiredRef` 패턴과 동일하게 `JOB_SEARCHING` 진입 시 검색을 한 번 자동 트리거, "다시 찾기" 버튼으로 재검색.
- **연동 진입점**: `ResultSection`에 "이 결과로 일자리 찾기 시작" 버튼 — `kind:"job_search", linked_gap_session_id:<현재 세션>`으로 새 세션 생성 후 이동.

## 의도적으로 처리하지 않은 것 (이번 범위 밖)

- 사람인/원티드/잡코리아 등 추가 구인 API 소스, 다중 소스 통합.
- 고용24 지역/학력/경력 코드 정밀 매핑(v1은 keyword 텍스트 검색으로 대체).
- 검색 결과 저장/북마크 기능(세션당 마지막 검색 결과 1건만 캐시).
- "이미 확정된 선호도를 확인 단계 밖에서 나중에 고치는" 별도 관리 기능 — 카테고리 CRUD와 동일한 이유로, 확인 단계에서만 되면 충분하다고 범위를 좁힘.

## 다음 단계

- 실 `WORKNET_API_KEY` 발급 후 실 로컬 Ollama와 함께 최소 1회 수동 확인(현재는 mock으로만 왕복 검증).
- 고용24 XML 응답의 정확한 래핑 태그명은 실 키로 첫 응답을 받아본 뒤 `worknet_client.py`의 파싱 로직을 한 번 더 확인해야 한다.
