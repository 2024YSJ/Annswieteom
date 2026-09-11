# 35. 공백기 채우기 — 카테고리 단위 확인 (2026-09-11)

## 요청

"각 질문에 대한 답변이 끝나면 사용자에게 바로 확인을 받는다. 이건 번거롭다. 각 카테고리에 대한
질문이 끝날 때 사용자에게 종합적인 내용을 확인받는 것으로 확인 절차를 간소화하자."

## 결정 (사용자 선택)

- 종합 확인 형태: **질문별로 묶은 사실 목록을 한 화면에** — 고쳐 쓰기·제외·항목 추가 후
  "모두 맞아요, 다음으로" 한 번. AI 요약 문단을 승인받는 방식은 채택하지 않았다 — 요약문
  자체는 사용자가 확인한 사실이 아니라서 문서 인용 근거와 어긋난다.
- 답변 직후: **바로 다음 질문**.
- "여러 활동이 있나요?"(소분류 분할): **지금처럼 즉시 확인** — 이후 질문 순서를 바꾸는
  라우팅이라 카테고리 끝까지 미룰 수 없다.
- 초안 저장: **새 컬럼 `activity_categories.draft_turns`**(JSON).
- 사실이 하나도 안 뽑힌 질문도 확인 화면에 묶음으로 보여준다("정리된 내용이 없어요" + 항목 추가).

## 구현

### 백엔드 (`app/api/interview.py`)

- 답변 1건 = 초안 턴 1개: `{turn_id, answer_log_id, question_text, question_source,
  fact_type_hint, answer_text, drafts: [{content, based_on}]}`. `based_on`은 이전과 같이
  그 턴 컨텍스트의 청크로 검증된 값만 남는다.
- **진행 판단은 확정 사실 + 초안**(`_known_facts`, `_answered_fact_types`)으로 한다 —
  LLM 컨텍스트, 남은 고정 질문, 드릴다운·충분성 판단, 기간 추론. 초안은 라우팅용일 뿐
  인용되지 않는다. 답한 고정 질문은 **턴 단위**로 센다(사실 0개인 "잘 모르겠어요"도 답한 것
  — 사실 단위로 세면 같은 질문이 무한 반복된다).
- `/answer`: 턴을 `draft_turns`에 추가하고 **먼저 커밋**한 뒤 `_decide_next`로 다음 질문
  또는 확인 단계를 정한다. 판단 LLM이 실패해도 답이 사라지지 않고, 다음 `/ask`가 초안
  기준으로 이어 간다. 후속 질문 생성이 실패하면 붙잡지 않고 확인으로 넘긴다.
- `/ask`: 확인 대기 중이면 LLM 없이 `mode="review"`(새로고침 복원). 질문 대기 중이면 입력창
  미리 채우기(draft_answer)를 **여기서 처음 한 번** 만든다 — `/answer`의 막히는 경로에서
  LLM 호출 하나를 뺐다(Spark 32b ≈ 13 tok/s).
- 새 `POST /interview/review`: 일반 답변 사실이 `confirmed_facts`에 들어가는 **유일한** 경로.
  source_type·fact_type·원 질문·AI 초안은 서버의 턴에서만 가져오고 클라이언트 값은 무시한다.
  턴별 `InterviewAnswer.confirmed_facts` 스냅샷(전부 빼면 `[]`), 이후 카테고리 DONE.
  확인 대기가 아니면 409 `no_pending_review`(이중 제출 방지).
- `/confirm`: 소분류 분기만 남기고 나머지는 409 `use_category_review`.
- 확인 대기 중 `/answer`는 409 `category_review_pending`, `/coverage/fill`도 초안이 있으면
  같은 409(초안 고아화 방지). 공백 답은 422 `empty_answer`(턴 단위로 세므로 빈 답이
  "답함"으로 처리되는 걸 막는다).
- 배포 순간 옛 방식 후보가 `pending_turn`에 걸린 세션은 `/ask`가 초안 턴으로 흡수한다.
- 프롬프트 문구: 컨텍스트를 부르는 "확인된 사실" → "지금까지 들은 내용"(출력 형식은 그대로).

### 프론트

- `InterviewSection`: 답변 응답 `mode`에 따라 다음 질문 / 확인 카드. 다음 질문은 바로 띄우고,
  미리 채우기가 올 때까지만 입력창을 잠근다(늦게 온 prefill이 사용자가 치던 글을 덮지 않게).
- `InterviewChatThread`: 카테고리별 확정 사실 → 확인 전 대화(질문·답변, "확인됨" 라벨 없음)
  → 현재 질문 또는 `CategoryReviewCard`(기존 `CandidateRow` 재사용).

### 운영 DB

- 마이그레이션 `c7d1e5a9f2b4`(down `b8e4d2a6c1f9`), 운영 SQL `docs/ops/prod_migration_c7d1e5a9f2b4.sql`.
  **배포 순서: 운영 SQL → 백엔드 → 프론트** — 컬럼 없이 새 백엔드가 뜨면 `GET /sessions/{id}`가 500.

## 테스트

- `pytest` 460 통과. 신규: 확인 전 confirmed_facts 0행, 질문별 확인 목록, 확인 대기 중 `/ask`
  LLM 0회, `/answer` 409, 이중 제출 409, 잘못된 turn_id/index 409, 클라이언트 source_type 무시,
  직접 추가 항목 user_edited, 턴별 아카이브 스냅샷, 옛 후보 흡수, `pending_turn=None`에도 초안
  유지, 커버리지 채우기 409, 사실 0개 답도 다음 질문으로 진행.
- 프론트 `tsc`·`eslint` 통과. e2e 목의 `/ask` 응답에 `mode`/`review` 추가.

## 보류

- `clamp_activity_period`의 "공백기 전체 ±7일도 버린다" 방어: 기존 테스트
  (`test_clamp_keeps_a_period_one_day_short_of_the_whole_gap`)가 "거의 전 기간을 채운 활동은
  버리지 않는다"를 일부러 지키고 있다. 운영 32b 검증에서 ±며칠 되뱉기 패턴이 실제로 보일 때 바꾼다.
- 운영 32b 추출 검증(프로필 속성·기간): 터널 토큰 또는 배포 사이트 대화로.
