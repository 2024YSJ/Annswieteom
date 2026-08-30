# B-2. 인터뷰 상태머신 및 세션/인터뷰 API

근거: 명세서 8절, 9-2절, 9-3절
선행 조건: [01_auth.md](01_auth.md), [00_shared/02_database_schema.md](../00_shared/02_database_schema.md)
폴더: `backend/app/services/interview_orchestrator.py`, `backend/app/api/sessions.py`, `backend/app/api/interview.py`
브랜치: `feature/interview-flow` (`dev`에서 분기, 완료 후 `dev`로 PR)
시점: 1~2주차

> **용어**: "상태 머신"은 시스템이 가질 수 있는 상태들의 목록과, 어떤 조건에서 한 상태에서 다른 상태로 넘어가는지를 명시적으로 정의한 것이다. `sessions.status` 한 컬럼으로 "지금 사용자가 인터뷰의 어느 단계에 있는지"를 관리한다.

## 1. 상태 전이 정의 (8절)

전체 흐름:
```
PERIOD_INPUT → CATEGORY_SELECT → RECORD_UPLOAD(선택)
  → [카테고리별 반복: FREQ_DRAFT → FREQ_CONFIRM → TASK_DRAFT → TASK_CONFIRM → ACHIEVEMENT_DRAFT → ACHIEVEMENT_CONFIRM]
  → RESULT_GENERATE → RESULT_REVIEW
```

- [ ] 8-2절 전이 표를 그대로 코드로 옮긴 상태 전이 함수/딕셔너리 작성 (허용되지 않은 전이 시도 시 `409 상태머신 위반` — 9-6절)
- [ ] `ACHIEVEMENT_CONFIRM`에서 다음 카테고리가 있으면 `FREQ_DRAFT`(다음 카테고리)로, 없으면 `RESULT_GENERATE`로 분기하는 로직 작성
- [ ] `RECORD_UPLOAD` 상태에서의 `POST /sessions/{id}/records` 반복 호출은 상태를 그대로 `RECORD_UPLOAD`로 유지한다(전이 없음) — 이 엔드포인트 자체의 구현은 [03_records_feature.md](03_records_feature.md)에서 하지만, 상태 전이 표(8-2절) 전체를 여기서 함께 검토할 것

## 2. `InterviewContext` 구성 (8-1절)

- [ ] Pydantic 모델로 정의: `session_id, status, gap_period, categories, current_category, confirmed_facts, available_record_chunks`
- [ ] `available_record_chunks`는 A가 노출하는 `record_pipeline.search_relevant_chunks(session_id, category_label)`([04_record_pipeline.md](../person_A_infra_ai/04_record_pipeline.md) 6번)를 호출해 현재 카테고리와 관련성 높은 조각을 채움 — 반드시 `session_id`를 넘겨서 다른 세션의 기록물이 섞이지 않게 한다

## 3. 세션 API (`api/sessions.py`, 9-2절)

> 아래 모든 `/sessions/{id}` 계열 엔드포인트는 [01_auth.md](01_auth.md) 4-1절의 `get_owned_session` 의존성으로 소유권을 확인한 뒤 처리한다 (**타인 세션 접근 시 `403`**, 없는 세션이면 `404`) — `GET /sessions/{id}`만이 아니라 이 절과 4절의 모든 엔드포인트에 동일하게 적용한다.

- [ ] `POST /sessions` 🔒: 새 세션 생성, `status='PERIOD_INPUT'`, `user_id`를 `current_user.id`로 채움 (다른 사용자 소유로 생성될 수 없도록)
- [ ] `GET /sessions/{id}` 🔒: `get_owned_session`으로 소유권 확인 후 `InterviewContext` 반환
- [ ] `DELETE /sessions/{id}` 🔒: `get_owned_session`으로 소유권 확인 후 세션 및 하위 데이터 CASCADE 삭제, 204

> **참고(의도된 범위 제한)**: 명세서 9-2절에는 "내 세션 목록 조회"(`GET /sessions`) API나 이를 보여줄 화면이 없다 — 즉 사용자가 세션 ID를 잃어버리면 그 세션에 다시 접근할 방법이 없다. 이는 3주 해커톤 범위에서 의도적으로 생략하기로 확인된 사항이다(팀 논의 결과). 프론트는 로그인 직후 바로 `POST /sessions`로 새 세션을 만들어 이어서 진행하는 흐름을 전제로 구현한다.

## 4. 인터뷰 진행 API (`api/interview.py`, 9-3절)

- [ ] `POST /sessions/{id}/period`: `get_owned_session` 확인 후 `{start_date, end_date}` → `gap_periods` insert → `CATEGORY_SELECT`
- [ ] `POST /sessions/{id}/categories`: `get_owned_session` 확인 후 `{categories: [{category_type}]}` → `activity_categories` bulk insert → `RECORD_UPLOAD`
- [ ] `POST /sessions/{id}/records/skip`: `get_owned_session` 확인 후 기록물 없이 진행 → 첫 카테고리로 `current_category_id` 설정, `FREQ_DRAFT`
- [ ] `GET /sessions/{id}/interview/next`: 현재 step에 맞는 AI 초안을 A의 `LLMProvider.draft_suggestion()`으로 요청, **`confirmed_facts`에는 저장하지 않고** 그대로 반환 (`{step, category_id, ai_draft, based_on}`) — 정직성 가드레일: 이 값은 아직 사실이 아니다
- [ ] ⚠️ **초안 임시 보관(구현 필수)**: `interview/confirm`이 받는 요청 바디는 `{step, final_text, was_edited}`뿐이라 `ai_draft_text`나 `based_on` 정보가 함께 오지 않는다 — 이 두 값을 confirm 시점에 알려면, `interview/next`가 초안을 반환할 때 그 내용(`ai_draft`, `based_on`)을 세션+step 단위로 어딘가에 임시 보관해뒀다가 confirm에서 꺼내 써야 한다. `confirmed_facts` 같은 "확정된 사실" 테이블이 아니라 별도의 임시 저장소(예: 세션 프로세스 내 인메모리 캐시, 또는 `sessions` 테이블의 임시 컬럼/경량 테이블)를 쓴다 — 정직성 가드레일은 "확정 전 초안이 confirmed_facts에 들어가면 안 된다"는 것이지 "초안을 어디에도 잠시 저장하면 안 된다"는 뜻이 아니므로 원칙 위반이 아니다. 같은 step에 대해 `interview/next`를 다시 호출하면(새로고침 등) 캐시된 초안을 최신 것으로 덮어쓴다
- [ ] `POST /sessions/{id}/interview/confirm`: `{step, final_text, was_edited}` → 위에서 임시 보관해둔 초안을 조회해 **여기서만** `confirmed_facts` insert, `ai_draft_text`에 그 초안 텍스트 보관. `source_type` 결정 규칙(6-6절 CHECK: `user_confirmed`/`user_edited`/`record_cited`):
  - `was_edited=true` → `user_edited`
  - `was_edited=false`이고 직전 `interview/next` 초안이 기록물 조각(`based_on`)에 직접 근거했다면 → `record_cited`, 이때 `source_record_chunk_id`도 함께 채움
  - `was_edited=false`이고 근거가 일반 패턴 추측(12-1절 `based_on: "generic_pattern"`)이었다면 → `user_confirmed`
  - ⚠️ 참고: 9-3절 API 표의 `interview/next` 응답 예시는 `"based_on": [...]`(배열)로, 12-1절 프롬프트 출력 형식의 `"based_on": "record" | "generic_pattern"`(문자열)과 형태가 다르다. **통일안**: `based_on`을 `{"type": "record", "excerpts": [{"chunk_id": UUID, "text": str, "published_at": date}]}` 또는 `{"type": "generic_pattern"}`으로 쓴다 — `chunk_id`는 confirm 시 `confirmed_facts.source_record_chunk_id`를 채우는 데, `text`/`published_at`은 프론트가 바로 보여주는 데 쓰인다(A의 `search_relevant_chunks()`가 반환하는 `RecordChunkExcerpt`에 `chunk_id`도 포함하도록 04_record_pipeline.md 6번에 맞춰 확장). 이 값을 정하면 A의 [02_llm_adapter_layer.md](../person_A_infra_ai/02_llm_adapter_layer.md) `Suggestion` 모델과 반드시 맞춰라
- [ ] `confirm` 처리 시 카테고리 반복 로직(다음 fact_type으로, 또는 다음 카테고리로, 또는 RESULT_GENERATE로) 반영

## 5. 정직성 가드레일 준수 확인 (1-2절, 필수)

- [ ] `interview/next`가 반환하는 AI 초안이 어떤 경로로도 `confirmed_facts`에 직접 쓰이지 않는지 코드 리뷰
- [ ] `confirmed_facts` insert는 오직 `interview/confirm` 엔드포인트 한 곳에서만 일어나는지 확인 (다른 경로로 우회해서 쓰는 코드가 없는지)

## 6. 더미 텍스트로 우선 검증 (마일스톤 2)

- [ ] A의 LLM 연동이 아직 없어도, `draft_suggestion`을 고정 문자열을 반환하는 스텁으로 대체해 상태머신 자체의 흐름(PERIOD_INPUT → 카테고리 반복 루프)이 끝까지 도는지 먼저 확인
- [ ] 이후 A의 실제 `FallbackProvider`로 교체

## 검증 기준

- [ ] 카테고리 하나를 끝까지(빈도→업무→성과) 확인/정정해서 `confirmed_facts`에 실제로 3개 row가 저장된다
- [ ] 카테고리를 2개 이상 선택했을 때 첫 카테고리의 ACHIEVEMENT_CONFIRM 이후 두 번째 카테고리의 FREQ_DRAFT로 정상 전환된다
- [ ] 정의되지 않은 순서로 API를 호출하면(예: PERIOD_INPUT 상태에서 곧바로 confirm 호출) `409`가 반환된다
- [ ] 다른 사용자의 세션 ID로 이 절의 **모든** 엔드포인트(period/categories/records-skip/interview-next/interview-confirm 포함)에 접근 시 `403`이 반환된다
