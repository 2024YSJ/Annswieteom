# B-2. 인터뷰 상태머신 및 세션/인터뷰 API

근거: 명세서 8절, 9-2절, 9-3절
선행 조건: [01_auth.md](01_auth.md), [00_shared/02_database_schema.md](../00_shared/02_database_schema.md)
폴더: `backend/app/services/interview_orchestrator.py`, `backend/app/api/sessions.py`, `backend/app/api/interview.py`
브랜치: `feature/interview-flow` (`feature/auth`에서 분기 — 작업 당시 `dev`가 아직 B-1을 머지받지 못해서 `feature/auth` 위에서 시작함). **2026-09-02에 `feature/auth`, `feature/interview-flow` 순서로 `dev`에 머지 완료.**
시점: 1~2주차

> **용어**: "상태 머신"은 시스템이 가질 수 있는 상태들의 목록과, 어떤 조건에서 한 상태에서 다른 상태로 넘어가는지를 명시적으로 정의한 것이다. `sessions.status` 한 컬럼으로 "지금 사용자가 인터뷰의 어느 단계에 있는지"를 관리한다.

> ⚠️ **구현 중 발견한 버그**: `app/models/session.py`의 `SESSION_STATUSES`(및 DB의 `ck_sessions_status` CHECK 제약)가 이 문서의 상태값과 전혀 다른 옛날 값(`INTERVIEW_FREQ`/`INTERVIEW_TASK`/`INTERVIEW_ACHIEVEMENT`/`GENERATING`/`DONE`)으로 들어있었다 — 8-2절 상태머신을 구현하는 이 시점까지 아무도 실제로 안 써봐서 안 걸렸던 것으로 보인다. 이번 작업에서 이 문서의 상태값(`PERIOD_INPUT`~`RESULT_REVIEW`)으로 교정하고 마이그레이션 `90edf5d28f6a`를 추가했다. **2026-09-02에 실제 Supabase DB에도 적용 완료** (`alembic current` → `90edf5d28f6a (head)` 확인).

## 1. 상태 전이 정의 (8절)

전체 흐름:
```
PERIOD_INPUT → CATEGORY_SELECT → RECORD_UPLOAD(선택)
  → [카테고리별 반복: FREQ_DRAFT → FREQ_CONFIRM → TASK_DRAFT → TASK_CONFIRM → ACHIEVEMENT_DRAFT → ACHIEVEMENT_CONFIRM]
  → RESULT_GENERATE → RESULT_REVIEW
```

- [x] 8-2절 전이 표를 그대로 코드로 옮긴 상태 전이 함수/딕셔너리 작성 (허용되지 않은 전이 시도 시 `409 상태머신 위반` — 9-6절) — `app/services/interview_orchestrator.py`: `SIMPLE_TRANSITIONS`(period/categories/records_skip), `NEXT_STEP_AFTER_DRAFT`, `NEXT_STEP_AFTER_CONFIRM`. 위반 시 `StateMachineViolation`을 던지고 라우터가 이를 409로 변환한다.
- [x] `ACHIEVEMENT_CONFIRM`에서 다음 카테고리가 있으면 `FREQ_DRAFT`(다음 카테고리)로, 없으면 `RESULT_GENERATE`로 분기하는 로직 작성 — `resolve_after_achievement_confirm()`, `order_index` 기준으로 다음 카테고리를 찾는다.
- [ ] `RECORD_UPLOAD` 상태에서의 `POST /sessions/{id}/records` 반복 호출은 상태를 그대로 `RECORD_UPLOAD`로 유지한다(전이 없음) — 이 엔드포인트 자체의 구현은 [03_records_feature.md](03_records_feature.md)에서 함 (검토는 완료: `SIMPLE_TRANSITIONS`에 `records` 액션 자체가 없다는 것 자체가 "전이 없음"을 의미하도록 설계했다 — 03에서 `POST /sessions/{id}/records`를 구현할 때 상태를 아예 안 건드리면 된다)

## 2. `InterviewContext` 구성 (8-1절)

- [x] Pydantic 모델로 정의: `session_id, status, gap_period, categories, current_category, confirmed_facts, available_record_chunks` — `app/schemas/session.py`의 `SessionContextRead` (LLM 프롬프트용 dataclass `app.services.llm.base.InterviewContext`와 이름이 같지만 별개이니 혼동 주의 — 전자는 API 응답, 후자는 내부 프롬프트 조립용)
- [x] `available_record_chunks`는 A가 노출하는 `record_pipeline.search_relevant_chunks(session_id, category_label)`를 호출해 현재 카테고리와 관련성 높은 조각을 채움 — `session_id`를 항상 넘겨서 다른 세션 기록물이 안 섞이게 했다. 임베딩 인프라가 죽어있어도 `GET /sessions/{id}` 자체는 계속 동작하도록 예외를 삼키고 빈 리스트로 대체한다(이 필드는 참고 정보일 뿐 상태 전이에는 안 쓰인다).

## 3. 세션 API (`api/sessions.py`, 9-2절)

> 아래 모든 `/sessions/{id}` 계열 엔드포인트는 [01_auth.md](01_auth.md) 4-1절의 `get_owned_session` 의존성으로 소유권을 확인한 뒤 처리한다 (**타인 세션 접근 시 `403`**, 없는 세션이면 `404`) — `GET /sessions/{id}`만이 아니라 이 절과 4절의 모든 엔드포인트에 동일하게 적용한다.

- [x] `POST /sessions` 🔒: 새 세션 생성, `status='PERIOD_INPUT'`, `user_id`를 `current_user.id`로 채움 (다른 사용자 소유로 생성될 수 없도록)
- [x] `GET /sessions/{id}` 🔒: `get_owned_session`으로 소유권 확인 후 `InterviewContext` 반환
- [x] `DELETE /sessions/{id}` 🔒: `get_owned_session`으로 소유권 확인 후 세션 및 하위 데이터 CASCADE 삭제, 204

> **참고(의도된 범위 제한)**: 명세서 9-2절에는 "내 세션 목록 조회"(`GET /sessions`) API나 이를 보여줄 화면이 없다 — 즉 사용자가 세션 ID를 잃어버리면 그 세션에 다시 접근할 방법이 없다. 이는 3주 해커톤 범위에서 의도적으로 생략하기로 확인된 사항이다(팀 논의 결과). 프론트는 로그인 직후 바로 `POST /sessions`로 새 세션을 만들어 이어서 진행하는 흐름을 전제로 구현한다.

## 4. 인터뷰 진행 API (`api/interview.py`, 9-3절)

- [x] `POST /sessions/{id}/period`: `get_owned_session` 확인 후 `{start_date, end_date}` → `gap_periods` insert → `CATEGORY_SELECT`
- [x] `POST /sessions/{id}/categories`: `get_owned_session` 확인 후 `{categories: [{category_type}]}` → `activity_categories` bulk insert → `RECORD_UPLOAD` — 기존 스키마 초안(`CategorySelect.category_types: list[str]`)이 명세서 9-3절의 실제 요청 형태(`{categories: [{category_type}]}`)와 달랐던 것도 이번에 같이 교정했다(`CategoryInput` + `CategorySelect.categories`).
- [x] `POST /sessions/{id}/records/skip`: `get_owned_session` 확인 후 기록물 없이 진행 → 첫 카테고리로 `current_category_id` 설정, `FREQ_DRAFT`
- [x] `GET /sessions/{id}/interview/next`: 현재 step에 맞는 AI 초안을 A의 `LLMProvider.draft_suggestion()`으로 요청, **`confirmed_facts`에는 저장하지 않고** 그대로 반환 (`{step, category_id, ai_draft, based_on}`) — 정직성 가드레일: 이 값은 아직 사실이 아니다. `llm`은 `Depends(get_llm_provider)`로 주입해서 테스트에서 실제 Ollama/Gemini 호출 없이 스텁으로 교체 가능하게 했다.
- [x] ⚠️ **초안 임시 보관(구현 필수)**: `sessions` 테이블에 `pending_draft`(제네릭 `JSON` 컬럼, 마이그레이션 `90edf5d28f6a`) 추가해서 여기 사용. `interview/next`가 `{step(확정될 CONFIRM 상태), category_id, draft_text, based_on}`을 저장하고, `interview/confirm`이 꺼내 쓴 뒤 `None`으로 비운다. (인메모리 캐시가 아니라 DB 컬럼을 택한 이유: Railway가 워커를 여러 개 띄우면 인메모리 캐시는 요청마다 다른 프로세스로 갈 수 있어 안전하지 않다.)
- [x] `POST /sessions/{id}/interview/confirm`: `{step, final_text, was_edited}` → 위에서 임시 보관해둔 초안을 조회해 **여기서만** `confirmed_facts` insert, `ai_draft_text`에 그 초안 텍스트 보관. `source_type` 결정 규칙(6-6절 CHECK: `user_confirmed`/`user_edited`/`record_cited`):
  - `was_edited=true` → `user_edited`
  - `was_edited=false`이고 직전 `interview/next` 초안이 기록물 조각(`based_on`)에 직접 근거했다면 → `record_cited`, 이때 `source_record_chunk_id`도 함께 채움
  - `was_edited=false`이고 근거가 일반 패턴 추측이었다면 → `user_confirmed`
  - **`source_type`은 요청 바디에 없다 — 클라이언트가 지정할 수 없게 스키마에서 아예 뺐다.** 클라이언트가 `record_cited`를 자유롭게 주장할 수 있으면 정직성 가드레일이 API 레벨에서 뚫리기 때문에, 서버가 `pending_draft`에 저장해둔 값만으로 판단한다.
  - `based_on`은 `{"type": "record", "excerpts": [{"chunk_id": UUID, "text": str, "published_at": date|null}]}` 또는 `{"type": "generic_pattern", "excerpts": []}`로 통일 — A의 `Suggestion.based_on`(`app/services/llm/base.py`) 구조와 이미 일치했다.
- [x] `confirm` 처리 시 카테고리 반복 로직(다음 fact_type으로, 또는 다음 카테고리로, 또는 RESULT_GENERATE로) 반영 — `payload.step != session.status`이면 409(클라이언트와 서버 상태가 어긋났다는 뜻)로 막는 이중 체크도 추가했다.

## 5. 정직성 가드레일 준수 확인 (1-2절, 필수)

- [x] `interview/next`가 반환하는 AI 초안이 어떤 경로로도 `confirmed_facts`에 직접 쓰이지 않는지 코드 리뷰 — `app/api/interview.py` 전체에서 `db.add(ConfirmedFact(...))` 호출은 `interview_confirm()` 함수 안, 딱 한 곳뿐이다.
- [x] `confirmed_facts` insert는 오직 `interview/confirm` 엔드포인트 한 곳에서만 일어나는지 확인 — 위와 동일 확인. 추가로 `source_type`을 클라이언트가 직접 지정 못 하게 한 것(4절 참고)도 같은 원칙의 연장선.

## 6. 더미 텍스트로 우선 검증 (마일스톤 2)

- [x] A의 LLM 연동이 아직 없어도, `draft_suggestion`을 고정 문자열을 반환하는 스텁으로 대체해 상태머신 자체의 흐름이 끝까지 도는지 먼저 확인 — 테스트에서는 `FakeLLMProvider`(`tests/api/conftest.py`)로 대체해서 확인했다.
- [x] 이후 A의 실제 `FallbackProvider`로 교체 — A가 이미 `LocalOllamaProvider`/`GeminiProvider`/`FallbackProvider`를 실제로 구현해뒀어서(스텁이 필요했던 시점을 이미 지남), `get_llm_provider()`가 프로덕션에서는 곧바로 `FallbackProvider()`를 반환하도록 했다. 로컬 Ollama/Gemini 키가 없는 개발 환경에서는 `AllProvidersFailedError` → `interview/next`가 `503`을 반환한다.

## 검증 기준

- [x] 카테고리 하나를 끝까지(빈도→업무→성과) 확인/정정해서 `confirmed_facts`에 실제로 3개 row가 저장된다 — `tests/api/test_interview.py::test_full_category_round_creates_three_confirmed_facts`
- [x] 카테고리를 2개 이상 선택했을 때 첫 카테고리의 ACHIEVEMENT_CONFIRM 이후 두 번째 카테고리의 FREQ_DRAFT로 정상 전환된다 — `test_two_categories_second_starts_at_freq_draft`
- [x] 정의되지 않은 순서로 API를 호출하면(예: PERIOD_INPUT 상태에서 곧바로 confirm 호출) `409`가 반환된다 — `test_confirm_before_any_draft_returns_409`, `test_interview_next_before_period_returns_409`, `test_confirm_step_mismatch_returns_409`
- [x] 다른 사용자의 세션 ID로 이 절의 **모든** 엔드포인트(period/categories/records-skip/interview-next/interview-confirm 포함)에 접근 시 `403`이 반환된다 — `test_other_users_session_returns_403_on_every_endpoint` (GET/DELETE `/sessions/{id}`까지 포함해서 확인)

## 미완 / 남은 작업

- [x] **마이그레이션 `90edf5d28f6a`를 실제 Supabase DB에 적용 (`alembic upgrade head`)** — 2026-09-02 완료. `alembic current` → `90edf5d28f6a (head)`, `ck_sessions_status` 제약과 `sessions.pending_draft` 컬럼 모두 실제 DB에서 확인.
- [x] `feature/auth`, `feature/interview-flow`를 순서대로 `dev`에 머지 완료 (둘 다 conflict 없이 merge). `dev`에서 전체 테스트 42개 재확인.
- [ ] 실제 브라우저/curl로 전체 인터뷰 플로우를 실제 LLM(Ollama 또는 Gemini)과 함께 왕복 테스트 — 지금까지는 `FakeLLMProvider`로만 검증했다.
