# 일자리 찾기 선호도를 공백기 채우기처럼 한 번에 하나씩 묻기

관련 spec: 없음(11/12와 동일하게 체크리스트 밖 항목, Claude Code 세션 계획 후 착수)
날짜: 2026-09-08

---

## 배경

[12_job_search_frontend.md](12_job_search_frontend.md)까지로 일자리 찾기 기능 자체와, 그 직후 요청으로 확정 후 자유 텍스트/폼으로 조건을 다시 고치는 "조건 수정하기" 대화형 재편집(커밋 `4083727`)까지 끝난 상태였다. 이번 요청은 그 전 단계 — **최초 1회차 입력**을 손보는 것: 지금까지는 "어떤 조건의 일자리를 찾고 계신가요?"라는 열린 질문 하나에 급여·근무지·학력·경력·업무 스타일을 자유 텍스트로 한 번에 다 적어야 했는데, 이걸 공백기 채우기 인터뷰처럼 질문 하나당 답 하나씩 주고받는 턴 기반 대화로 바꿔달라는 요청이었다.

조사 중에 스키마 자체의 빈틈도 하나 발견했다: 워크넷 검색에 실제로 쓰이는 키워드가 `location`/`education_level`/`work_style_tags`를 억지로 이어붙인 것뿐이었고, 정작 제일 중요한 검색어인 "직무/분야"(예: "백엔드 개발")가 스키마에 아예 없었다. 사용자 확인 후 `desired_keyword` 필드를 새로 추가하기로 하고, 이번 질문 설계에 첫 질문으로 포함시켰다.

범위는 사용자 확인대로 **최초 1회차 입력에만** 한정 — 직전에 만든 확정 후 "조건 수정하기"(자유 텍스트+폼 재편집) 플로우는 손대지 않았다.

## 완료 항목

- **`desired_keyword` 필드 추가**: `JobPreferences`/`JobPreferencesRead`/`JobPreferencesSuggestionRead`/`JobPreferencesConfirmInput`, `extract_job_preferences.jinja` 출력 스키마, `job_fit_judgment.jinja`의 조건 요약(직무 불일치를 부적합 판단 근거로 사용하도록 지시 추가), `worknet_client.py::search()`(이제 `desired_keyword`를 우선 키워드로 쓰고, 없을 때만 기존 location/education/tags 조합으로 대체).
- **DB 마이그레이션** `a194faedf943`: `job_search_preferences.desired_keyword`(nullable String), `.completed_fields`(NOT NULL JSON, 기본값 `[]`) 추가. 로컬 dev DB에 적용 완료.
- **질문 은행** (`app/services/job_search_question_bank.py`, 신규): 고정 6문항(keyword→location→salary→education→career→work_style) 리스트에서 `completed_fields`에 없는 첫 항목을 고르는 순수 함수 `next_question`. `interview_question_bank.py`와 원리는 같되, 카테고리 분기가 없어 훨씬 단순.
- **엔드포인트 2개** (`app/api/job_search.py`): `POST /job-search/preferences/ask`(다음 질문 계산, `Session.pending_turn`에 캐싱해 idempotent, 6개 다 답하면 `status→JOB_SEARCHING`), `POST /job-search/preferences/turn-confirm`(현재 턴의 필드만 반영 — 어느 필드인지는 서버가 `pending_turn`에서 판단해 클라이언트가 우기지 못하게 함). 기존 `POST /job-search/preferences/extract`(제안만, 미저장)는 변경 없이 그대로 재사용 — "자유 텍스트 → 구조화 제안"은 턴 진행 중에도 정확히 같은 일이라 새 엔드포인트를 안 만들었다.
- **연동(seed-from-gap) 연결 시점 이동**: `keyword_hints`(이번에 처음 실제로 쓰임)/`work_style_tags`를 "진입 즉시 시드"에서 "해당 질문 턴에서 시드"로 옮김 — `ask`가 keyword/work_style 질문을 낼 때만 `_seed_from_gap`을 호출해 `draft_answer`를 채움.
- **프론트 신규**: `JobSearchInterviewSection.tsx`(질문 하나씩 누적 표시, 필드 타입별 위젯 — 텍스트/숫자 2개/숫자 1개/태그), `JobStyleTagEditor.tsx`(태그 편집 마크업을 `JobSearchPreferencesSection`에서 뽑아 공용화 — 두 컴포넌트가 유일하게 실제로 코드 재사용할 부분). `JobSearchChatPage`는 `status===JOB_PREFERENCES_INPUT`이면 `JobSearchInterviewSection`을, 그 외엔 기존 `JobSearchPreferencesSection`(이제 "완료 요약 + 자유 재편집" 역할만)을 렌더링하도록 배타적으로 분기.
- 백엔드 신규 테스트 10개(질문 은행 4개 + `ask`/`turn-confirm` 왕복 6개, 6문항 전체 완주 테스트 포함) — 전체 185개 통과. `e2e/job-search-flow.spec.ts`를 새 턴 기반 흐름으로 재작성, 2회 연속 통과 확인. `eslint`/`next build` 클린.

## 핵심 결정 사항과 이유

**턴 진행 상태를 새 테이블 대신 기존 `job_search_preferences.completed_fields` + `Session.pending_turn`으로.** `pending_turn`은 원래 공백기 채우기 인터뷰 전용으로 쓰이던 범용 JSON 컬럼인데, `job_search`/`gap_fill`은 서로 다른 `kind`의 세션이라 실제로 값이 섞일 일이 없다 — 그래도 방어적으로 `{"kind": "job_search_preferences", ...}` 형태로 캐싱해 나중에 혼동 여지를 없앴다.

**턴별 "답변 해석"에 새 엔드포인트를 만들지 않았다.** 자유 텍스트를 구조화된 제안으로 바꾸는 일은 최초 입력이든 확정 후 재편집이든 정확히 같은 작업(DB에 아무것도 안 쓰고 suggestion만 반환)이라, 기존 `preferences/extract`를 그대로 재사용하고 프론트가 응답에서 현재 턴의 필드만 골라 보여주게 했다.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| 백엔드 단위/통합 테스트(`test_turn_confirm_walks_all_six_questions_...`)는 6문항 전부 그린인데, 실제 브라우저 e2e는 Q4(학력)→Q5(경력) 전환에서 멈춘 것처럼 보임(`error-context.md` 스냅샷엔 "학력" 질문이 확정 이력에도, 활성 질문으로도 동시에 찍혀 있었음) | 처음엔 진짜 버그로 의심했으나, 똑같은 시퀀스를 좁게 재현하는 디버그 스펙(`page.on("requestfinished")`로 네트워크 왕복 전부 로깅)을 두 번 만들어 돌려보니 **양쪽 다 깨끗하게 통과** — 즉 이 특정 재현은 콜드스타트류의 우연한 타이밍 문제였을 뿐, 실제 코드 결함이 아니었다 | 디버그 스펙을 지우고 실제 `job-search-flow.spec.ts`를 그대로 재실행 — 이번엔 다른 지점(아래 항목)에서 실패하며 진짜 버그가 드러남 |
| 실제 e2e가 6문항을 전부 답한 뒤 "완료 요약 화면" 진입에서 실패(`찾는 직무/분야: 백엔드 개발` 텍스트가 안 보임) — 스크린샷엔 요약 화면 대신 곧바로 "조건 수정하기" 편집 폼이 열려 있고 저장 버튼이 "저장 중..."에 멈춰 있었음 | **진짜 버그.** `JobSearchInterviewSection`이 6번째(work_style) 턴을 끝내고 언마운트되면, `JobSearchChatPage`가 그 자리에 `JobSearchPreferencesSection`을 새로 마운트한다. 이때 부모의 `composerEvent` 상태는 인터뷰 마지막 질문에 답할 때 보낸 메시지가 그대로 남아있는데(같은 state를 두 컴포넌트가 공유), 새로 마운트된 `JobSearchPreferencesSection`의 `answeredNonceRef`는 `null`로 시작하므로 이 "이미 소비된" composerEvent를 "새 메시지"로 오인해 곧장 재편집 폼을 열고 `extractPreferences`를 한 번 더 호출해버림 | `answeredNonceRef`의 초기값을 `useRef<number\|null>(null)` 대신 `useRef<number\|null>(composerEvent?.nonce ?? null)`로 — 마운트 시점에 이미 떠 있던 nonce를 "처리됨"으로 시드해서, 그 이후에 실제로 새로 들어온 composerEvent만 반응하게 함. `JobSearchInterviewSection` 쪽도 동일 원인의 잠재 버그라 방어적으로 같이 고침 |

## 남은 작업

- `JobStyleTagEditor`의 태그 `<input>` 너비가 `Math.max(tag.length, 3)}ch`로 계산되는데, 한글(CJK)은 1글자가 1ch보다 넓어서 "재택 가능" 같은 태그가 살짝 잘려 보이는 코스메틱 이슈 발견(이번 작업 범위 밖이라 손대지 않음).
- 나머지는 [11](11_job_search_backend.md)/[12](12_job_search_frontend.md)와 동일 — 실 `WORKNET_API_KEY`로 최소 1회 수동 확인 아직 미완.
