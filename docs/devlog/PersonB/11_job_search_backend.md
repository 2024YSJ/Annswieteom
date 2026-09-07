# 일자리 찾기 백엔드 devlog

관련 spec: 없음(원래 마일스톤 체크리스트에 없던 항목 — Claude Code 세션에서 계획 후 착수, 계획 파일은 세션 로컬에만 존재)
날짜: 2026-09-07

---

## 배경

사용자 요청: (1) "일자리 찾기" 기능 — 대화형으로 희망 급여/근무지/학력·경력/업무 스타일을 받아 구인 API를 조회하고, 응답을 그대로 보여주는 게 아니라 LLM으로 적합도를 판단해 추천, (2) 공백기 채우기 결과(확정된 사실)를 일자리 찾기 입력으로 연동, (3) 카테고리/후보 목록 CRUD가 "AI가 후보를 제시하고 사용자가 확인하는 바로 그 턴"에서 두 플로우 모두 가능해야 함.

(3)은 조사 결과 기존 공백기 채우기 플로우(카테고리 선택 후보/활동 세부 분할 후보/사실 확인 후보)가 이미 전부 충족하고 있어 추가 작업이 필요 없었다 — 신규 일자리 찾기 플로우의 확인 단계만 같은 패턴을 따르면 되는 것으로 범위가 좁혀졌다.

이번 devlog는 그중 **백엔드 부분만** 다룬다. 프론트엔드(선호도 확인 화면, 사이드바 kind별 그룹핑, 연동 버튼, e2e)는 사용자에게 "이어서 구현할지" 확인을 요청해둔 상태로 아직 시작하지 않았다.

## 완료 항목

- **LLM 어댑터 신규 능력 3개** (`extract_job_preferences`, `judge_job_fit`, `infer_job_preferences_from_facts`) — `base.py` Protocol/dataclass, `fallback.py`의 `FallbackProvider`, `local_ollama.py`/`gemini_provider.py` 양쪽 구현, 프롬프트 3개(`extract_job_preferences.jinja`, `job_fit_judgment.jinja`, `infer_job_preferences.jinja`) — 기존 `judge_sufficiency` 등과 동일한 `[SYSTEM]/[USER]/[출력 형식]` + JSON-only 컨벤션을 그대로 따름.
- **워크넷(고용24) 채용정보 API 클라이언트** (`app/services/job_pipeline/worknet_client.py`) — `httpx` + `Settings` + DI 팩토리 패턴(`storage.py`와 동일), XML 응답은 표준 라이브러리 `xml.etree.ElementTree`로 파싱(신규 의존성 없음). `WORKNET_API_KEY`/`WORKNET_API_BASE_URL` 설정 추가.
- **DB 스키마**: `sessions.kind`(`gap_fill`/`job_search`), `sessions.linked_gap_session_id`(자기참조 FK, SET NULL), `sessions.status` CHECK에 job-search 3개 상태(`JOB_PREFERENCES_INPUT`/`JOB_SEARCHING`/`JOB_RESULTS_REVIEW`) 추가, 신규 테이블 `job_search_preferences`. 마이그레이션 `4d7aacb4bfe8`을 dev Supabase DB에 실제 적용 완료.
- **엔드포인트 5개** (`app/api/job_search.py`, 신규 라우터): `GET /job-search`(상태+선호도+캐시된 검색 결과), `POST /job-search/preferences/extract`(제안만, 미저장), `POST /job-search/preferences`(확정 저장), `POST /job-search/search`(워크넷 최대 15건 → `judge_job_fit`을 동시성 4로 병렬 판단 → fit 우선 정렬 → 캐시), `POST /job-search/seed-from-gap`(연동 — 링크된 gap 세션의 confirmed_facts에서 추론, 제안만/미저장).
- `POST /sessions`를 확장해 `kind`/`linked_gap_session_id`를 받도록 함(`SessionCreate`에 기본값이 있어 기존 "본문 없는 세션 생성" 호출은 그대로 동작).
- 신규 테스트 12개(`test_job_search.py`, `test_job_search_seed.py`) + 기존 스위트 전부 — **174개 전부 통과**.

## 핵심 결정 사항과 이유

**카테고리 CRUD는 이번 범위에서 뺐다.** 처음엔 "확정된 카테고리를 아무 때나 추가/삭제/수정" 기능으로 넓게 계획했으나(문서 자동 재생성 포함), 사용자가 "확인 단계에서만 되면 된다"고 범위를 좁혔고, 조사 결과 기존 플로우가 이미 그 요구를 충족하고 있어서 아예 새 작업이 필요 없었다. 계획을 다시 세우며 문서(`plans/expressive-singing-dahl.md`)를 전면 재작성했다.

**일자리 찾기는 별도 `kind`를 가진 같은 `Session` 모델로.** 완전히 새 테이블/상태머신을 만드는 대신 `sessions.status` CHECK에 3개 상태를 추가해 기존 컬럼을 공유했다 — `Session`이 이미 "상태머신 전용" 모델이라 분리할 이유가 없다고 판단. 다만 전이 규칙(`_require_status`)은 `interview_orchestrator.py`를 재사용하지 않고 `job_search.py` 안에 별도 헬퍼로 뒀다 — 두 플로우가 상태 컬럼만 공유할 뿐 전이 로직은 도메인이 완전히 달라서, 억지로 묶으면 오히려 `interview_orchestrator`가 두 플로우 모두를 이해해야 하는 모듈이 돼버린다.

**워크넷 단일 소스, 지역/학력 코드 매핑은 후속 과제.** 사람인(승인 대기+일 500회 제한)·잡코리아(공공기관/학교 우선, 개인 프로젝트는 승인 불확실) 대비 워크넷은 즉시 무료 발급이라 3주 일정에 유리하다고 이전 대화에서 판단했다. 코드 매핑 대신 자유 텍스트를 `keyword` 파라미터에 실어 검색하는 v1 단순화를 명시적으로 남겼다.

**`judge_job_fit`은 동시성 4로 병렬 호출.** 로컬 Ollama가 호출당 수십 초 걸릴 수 있어(기존 devlog들에 반복 기록됨), 최대 15건을 순차로 판단하면 너무 느리다. `asyncio.Semaphore(4)` + `asyncio.gather`로 묶었고, 판단 자체가 실패해도(`AllProvidersFailedError`) 검색 전체를 실패시키지 않고 "판단 불가"로 표시만 하도록 함.

**seed-from-gap은 급여/근무지를 절대 채우지 않는다.** STAR 사실만으로는 유추 불가능한 항목이라 `JobPreferenceInferenceResult`에 애초에 필드 자체가 없다 — 프롬프트에도 명시. 테스트(`test_seed_infers_preferences_from_linked_sessions_confirmed_facts`)로 응답에 해당 키가 아예 없는 것까지 확인.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `app/services/job_pipeline/__init__.py`를 Write로 만들었는데 곧바로 `ImportError: cannot import name ... (unknown location)` | 첫 Write 호출이 디스크에 실제로 반영되지 않은 채 성공 응답을 반환함(도구 자체의 일시적 문제로 보임, 재현 원인 불명) — `ls`로 확인해보니 파일이 없었음 | 같은 내용으로 Write를 한 번 더 호출하니 정상 생성됨. 이후 매번 `ls`로 실제 생성 여부를 확인하는 습관 필요 |
| `Edit` 도구가 `app/models/session.py`에 "File does not exist" 에러 | 대화 중간에 plan mode를 두 번 드나들면서 이전에 읽어둔 파일 상태가 컨텍스트에서 유실된 것으로 추정 | `Read`로 파일을 다시 읽은 뒤 재시도하니 정상 동작 |
| `alembic revision --autogenerate`가 이번 변경과 무관한 `generated_paragraphs.created_at` NOT NULL 변경과 `record_chunks`의 ivfflat 인덱스 drop까지 같이 감지함 | dev Supabase DB와 현재 모델 정의 사이에 이미 있던 drift(이번 세션이 만든 게 아님) — pgvector 인덱스는 autogenerate가 완전히 introspect 못 하는 것으로 보임 | 생성된 마이그레이션 파일에서 그 두 줄을 수동으로 제거. `sessions.kind` NOT NULL 컬럼에 `server_default='gap_fill'`도 수동 추가(기존 row가 있어서 필요), `ck_sessions_status` 재정의도 autogenerate가 named 제약의 본문 변경은 못 잡아서 수동으로 drop+recreate 추가. `create_foreign_key(None, ...)`로 나온 익명 FK도 downgrade에서 이름을 못 찾는 문제라 명시적 이름(`fk_sessions_linked_gap_session_id`)으로 바꿈 |
| 새 모델 추가 후 `test_sessions.py::test_delete_session_removes_it_from_list` 등 2개 실패, `no such table: job_search_preferences` | `tests/api/conftest.py`의 SQLite 테스트 픽스처들이 `Base.metadata.create_all(tables=[...])`로 테이블을 명시적으로 골라 만드는 방식이라, `Session.job_search_preferences`(cascade="all, delete-orphan") 관계가 세션 삭제 시 lazy-load되면서 없는 테이블을 침 | `session_client`류 픽스처 3곳의 `tables` 목록에 `JobSearchPreferences.__table__` 추가 |

## 남은 작업

- 프론트엔드: `JobSearchPreferencesSection`(스칼라 폼 + 태그 편집기, `PeriodSection`/`CategorySection` 패턴 재사용), `JobSearchResultsSection`, 사이드바 kind별 그룹핑, `ResultSection`의 "이 결과로 일자리 찾기 시작" 버튼.
- e2e(`job-search-flow.spec.ts`).
- 실 로컬 Ollama + 실 `WORKNET_API_KEY`로 최소 1회 수동 확인(로컬 `.env`에 아직 키 없음 — 발급 필요).
- 사용자가 프론트엔드 착수 여부를 확인해주면 이어서 진행.
