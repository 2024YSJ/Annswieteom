# 36. 입력창 자동 채우기(draft_answer) 제거 (2026-09-12)

## 무엇을

인터뷰에서 질문이 나올 때마다 AI가 답변 초안을 써서 입력창을 미리 채우고 "AI가 미리 써봤어요 · 이어 쓰거나
고쳐서 보내세요" 태그와 ↺(지우고 새로 쓰기) 버튼을 보여주던 기능을 **백엔드까지 완전히 제거**했다.
사용자 요청이다. 입력창은 이제 항상 빈 칸으로 시작한다.

**취업정보 검색의 첫 질문 초안(`/job-search/draft-query-from-gap`)은 남겼다** — 이관 직후 한 번만 돌고,
사용자가 방금 말한 사실을 질문 문장으로 바꿔주는 다른 용도다. 그래서 `ChatComposer`의 `prefillText` prop과
프리필 UI(태그·↺·강조 테두리)는 손대지 않았다. 인터뷰만 그걸 쓰지 않는다.

## 완료

- [x] 프롬프트 `backend/app/prompts/interview_draft_answer.jinja` 삭제
- [x] `LocalOllamaProvider.draft_answer` 및 `LLMProvider` Protocol 항목 제거
- [x] `InterviewAskRead.draft_answer` 필드 제거 (`InterviewAnswerRead.question`이 이 모델을 품으므로 `/answer` 응답에서도 사라짐)
- [x] `_ensure_draft_answer()` 삭제, `/ask`의 두 호출부 정리
- [x] `_build_pending_turn()`이 **동기 함수**가 됐다 — LLM도 `llm` 인자도 필요 없어졌고, 하는 일은 질문 예산 집계와
      대기 턴 구성뿐이다. 호출부 4곳의 `await`·`llm`·`with_draft=False` 정리
- [x] 프론트: `InterviewSection`의 `onPrefillChange` prop 제거, 페이지의 `composerPrefill` state 제거,
      `InterviewAskRead` 타입에서 필드 제거
- [x] **`/answer` 뒤에 붙던 여분의 `/ask` 왕복 삭제** — 아래 "덤으로 얻은 것"
- [x] 테스트: 프리필 테스트 3개를 회귀 테스트 2개로 교체(응답에 필드 없음 + 프로바이더에 메서드 없음,
      `/answer`가 실어 오는 다음 질문에도 필드 없음), 호출 수 집계 튜플 정리, e2e에서 프리필 단정을
      "입력창이 비어 있다"로 교체
- [x] 모델 비교/벤치 스크립트에서 draft 케이스 제거(`compare_llm_models.py`, `build_spark_bench.py`, `spark_model_bench.py.tmpl`)
- [x] `pytest` 459 passed, `tsc --noEmit` 통과, `eslint` 통과

## 덤으로 얻은 것: 질문당 LLM 호출 하나 + 왕복 하나

`draft_answer`는 출력 토큰이 많은 편이었다(Spark 벤치에서 51토큰 — 문서 생성을 빼면 가장 큰 편).
게다가 프론트엔드는 `/answer` 응답에 **이미 다음 질문을 받고도** 초안만 받으려고 `/ask`를 한 번 더 불렀고,
그 사이 컴포저를 비활성화해 뒀다(초안이 늦게 도착해 사용자가 쓰던 글을 덮어쓰는 걸 막으려고).
초안이 없어지니 그 왕복도, 그 대기도 필요 없다 — 이제 `/answer` 응답의 질문을 바로 화면에 쓴다.

즉 한 턴의 비용이 `extract_facts + 라우팅 판단(드릴다운/충분성)`으로 줄었다. PersonA devlog 09의
"응답 시간 ≈ 출력 토큰 ÷ decode 속도 × 순차 호출 수"에서 곱셈의 두 번째 항이 하나 작아진 셈이다.

## 결정 사항과 이유

**필드를 빈 문자열로 남기지 않고 스키마에서 지웠다.** `draft_answer: str = ""`로 남겨 두면 "나중에 다시 켤 자리"로
읽히고, 프론트가 언제든 다시 읽게 된다. 지우면 되살리려는 변경이 리뷰에서 눈에 띈다. 프론트의 타입에서도 같이 지워
`tsc`가 잔여 참조를 잡게 했다.

**회귀 테스트를 "필드가 없다"로 썼다.** 기능 제거는 조용히 되돌아오기 쉬워서(다음에 누가 프리필을 다시 붙이면
사용자 요청을 되돌리는 것이다), `/ask`·`/answer` 응답에 `draft_answer` 키가 없고 프로바이더에 `draft_answer`
메서드 자체가 없다는 것을 단정했다.

**정직성 가드레일 문구를 옮겼다.** `user_attributes`를 "`draft_answer` 프롬프트에 넣지 말라"던 주의사항
(CLAUDE.md, `profiling_and_matching.md`, `user_attribute.py`, `InterviewContext.profile_summary`)은 이제
없는 프롬프트를 가리킨다. 위험 자체는 그대로이므로 **`extract_facts`·문서 생성 기준으로 다시 썼다** —
추정 속성이 사실 초안에 섞이면 카테고리 확인 한 번으로 confirmed_fact가 된다.

## 관련 커밋

- `5ca548c` 프리필 제거(프롬프트·프로바이더·스키마·프론트·테스트·벤치 스크립트·문서)

## 남은 작업

- 없음. 되돌리려면 이 커밋을 revert하면 되고, 그때 프롬프트 파일도 함께 돌아온다.
