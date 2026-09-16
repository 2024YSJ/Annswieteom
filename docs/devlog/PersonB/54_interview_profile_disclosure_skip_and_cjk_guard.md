# 54. 커리어 채우기 인터뷰 — 프로필 공개·건너뛰기 + 중국어 혼입 방지 + 질문 반복 루프 차단 (2026-09-16)

취업 정보 검색 검증에 이어, 페르소나 3명으로 **커리어 채우기(gap-fill) 인터뷰
→ 취업 정보 검색 이관** 전체 흐름을 라이브로 완주시켜 보다가, 애초 조사 목적과
별개로 인터뷰 단계 자체에서 세 가지 문제가 재현됐다. 사용자 요청에 따라 셋 다
같은 라운드에서 고쳤다.

## 무엇을

### 1. 프로필 참고 공개 + "건너뛰기"

`interview_followup_question.jinja`/`interview_drilldown.jinja` 둘 다
`profile_summary`(계정에 저장된 희망직무 등)를 "다시 묻지 말고 질문을 다듬는
데만 참고해라"는 지시로 주입하는데, 사용자에게 그걸 참고했다는 사실을
알려주는 지시가 전혀 없었다. 실측에서는 이게 **다른 페르소나의 프로필
("백엔드 개발자")이 전혀 무관한 인터뷰에 새어 들어가는** 형태로 나타났고,
사용자가 답변으로 명시적으로 정정해도(`user_attributes`는 세션 사이 안
바뀌므로) 다음 턴에 똑같은 낡은 프로필이 다시 주입돼 **거의 동일한 질문이
한 카테고리에서 최대 3회 반복**됐다.

- `interview_followup_question.jinja`/`interview_drilldown.jinja`의
  `profile_summary` 블록에 두 가지를 추가: (1) 프로필을 실제로 반영했으면
  질문 문장에 자연스럽게 밝히도록(예시 문구 포함), (2) 확인된 사실이 프로필과
  모순되면 프로필 쪽을 낡은 정보로 보고 더 이상 참고하지 말도록.
- 신규 `POST /{session_id}/interview/skip` — `pending_turn["question_source"]
  == "followup"`일 때만 허용(드릴다운·후속 둘 다 여기 해당). 고정
  질문(`"base"`)과 소분류 확인(`"split_check"`)은 절대 건너뛸 수 없다 —
  `next_base_question()`의 완료 판정이 모든 fact_type 슬롯의 응답을
  전제하기 때문이다. `/interview/answer`의 뒷부분과 거의 동일하게 흐른다
  (`_decide_next` 재사용, 새 상태머신 분기 없음).
- 건너뛴 턴도 `draft_turns`에 `skipped: true`로 남긴다 — `_build_context`의
  `asked_questions`에 그대로 실려 같은/거의 같은 질문이 바로 다시 나오는 걸
  막고(아래 3번의 근접 중복 검사와 함께 이중 방어), `_review_read()`는 이
  턴을 걸러내 리뷰 화면에 빈 그룹으로 뜨지 않게 한다.
- 건너뛰기도 질문을 낼 때 이미 `followup_questions_asked`가 올라가 있으므로
  후속 질문 예산을 그대로 소비한다 — 건너뛰기 스팸으로 예산 우회 불가.
- 프론트: `InterviewChatThread`가 `question_source === "followup"`일 때만
  질문 아래 "건너뛰기" 버튼을 보여준다.

### 2. 확정 사실·질문에 중국어 문자 혼입 방지

실측에서 확정 사실(`confirmed_facts.content`)에 중국어가 그대로 섞여
저장됐다(예: "...봉사活动中에 활용했어요"). `confirmed_facts`는 정직성
가드레일이 보호하는, 생성 문서에 그대로 들어갈 수 있는 데이터라 우선순위가
가장 높았다.

**원인**: 인터뷰 관련 프롬프트 어디에도 "한국어로만 답하라/다른 언어를
섞지 마라"는 지시가 없었다 — `local_ollama.py`의 공용 시스템 메시지
"Always respond in Korean"만 있었는데, 이건 전체 응답 언어에 대한 것일 뿐
코드스위칭(문장 중간에 다른 언어 단어가 섞이는 것)을 막는 지시가 아니다.
LLM 출력이 저장되기 전 어떤 언어 검증도 거치지 않았다. 이 현상은
2026-09-03에도 다른 모델(qwen2.5:14b)로 한 번 있었고(devlog 08), 그때는
문서 생성 시점의 `consistency_check`(임베딩 유사도 가드)가 우연히 잡아내서
"모델 변동성, 코드 문제 아님"으로 넘어갔다. 하지만 `consistency_check`는
`confirmed_facts.content` 저장 시점이 아니라 문서 생성 시점에만, 그것도
의미 유사도만 보므로(부분적 언어 혼입은 원본과 의미가 가까워 통과할 수
있음) 이번 재현 사례를 막지 못했다 — **그 시점의 "코드 문제 아님" 결론은
틀렸다**, 그저 이 실패 모드를 잡을 별도 방어선이 없었을 뿐이다.

- 프롬프트 레이어: `interview_extract_facts.jinja`(가장 중요 —
  `ConfirmedFact.content`로 직행하는 유일한 프롬프트), 
  `interview_followup_question.jinja`, `interview_drilldown.jinja`,
  `probe_activity_question.jinja` 4개 전부에 "반드시 한국어로만
  답하라(중국어 한자·다른 언어 금지, 기술 용어 영어 단어는 예외)" 지시 추가.
- 코드 레이어(프롬프트만으로 안 잡힐 경우의 하드 백스톱): 신규
  `app/services/llm/language_guard.py`의 `contains_cjk()` — CJK Unified
  Ideographs(`一-鿿`) 정규식 감지. `local_ollama.py`의 4개
  호출부(`extract_facts`/`followup_question`/`judge_drilldown`/
  `probe_activity_question`)가 결과를 검사해 오염되면 "[언어 경고]" 문구를
  덧붙여 **한 번만** 재시도하고, 그래도 오염이면 안전하게 폴백한다:
  `extract_facts`는 여전히 오염된 후보만 드롭(깨끗한 것들은 유지),
  나머지 3개는 `None`/`should_ask=False`로 "이번엔 없음" 처리.
- `LLMProvider` 프로토콜의 `followup_question`/`probe_activity_question`
  반환형을 `str | None`으로 변경. `_decide_next()`의 후속 질문 분기가
  `None`을 기존 "예산 소진 → 확인" 분기와 같은 방식으로 처리한다.

### 3. 근접 중복 후속 질문 코드 백스톱

두 프롬프트 모두 "이미 물어본 질문과 중복되는 질문은 하지 마라"는 지시만
있었고, 코드 쪽에서 실제로 중복을 검사하는 로직이 전혀 없었다 — LLM이 뭘
내놓든 그대로 썼다. 낡은 프로필이 매 턴 재주입되는 문제(1번)와 겹치면 같은
전제의 질문이 표현만 바뀐 채 반복될 수 있고, 실측에서는 "다음 질문으로
넘어가주세요"라고 명시적으로 요청해야만 빠져나올 수 있었다.

- `interview_orchestrator.py`에 `is_near_duplicate_question()` 추가 —
  `difflib.SequenceMatcher` 비율(공백 정규화 후, 임계값 0.7)로 후보 질문이
  `asked_questions` 중 하나와 표현만 다를 뿐 사실상 같은 질문인지 판단하는
  순수 함수. 이 모듈이 이미 `followup_budget` 같은, LLM 호출 없는 순수
  상태-판단 헬퍼들을 모아두는 곳이라 같은 자리에 뒀다.
- `_decide_next()`의 드릴다운 분기와 후속 질문 분기 양쪽에 배선 — 근접
  중복이면 드릴다운은 `should_ask=False`로, 후속 질문은 예산 소진과 같은
  방식으로 처리(2번의 `None` 처리와 같은 분기를 공유).
- 1번의 프롬프트 지시가 낡은 프로필 재사용 "원인"을 줄이고, 이 코드 검사는
  원인이 무엇이든(낡은 프로필, 모델 루프 등) 새어나온 근접 중복을 잡는
  최종 방어선 — 서로 보완 관계다.

## 트러블슈팅

- **`test_followup_budget_caps_ai_questions_but_never_skips_a_fixed_one`
  회귀**: 이 테스트는 "LLM이 매 답변마다 드릴다운을 원하는" 상황을
  재현하려고 완전히 동일한 문구("더 자세히 말해주세요")를 10번 큐에
  넣어뒀는데, 새로 추가한 근접 중복 검사가 이걸 정확히 잡아내 첫 번째
  뒤로는 전부 억제해버렸다(`followup_count`가 3이 아니라 1이 됨). 테스트의
  실제 의도(예산이 고정 질문을 절대 안 건너뛴다)는 "매번 드릴다운을
  원하는 것"이지 "매번 똑같은 문구를 내놓는 것"이 아니었으므로, 큐를 서로
  실질적으로 다른 10개 문장으로 바꿔 테스트 의도와 새 방어 로직이 공존하게
  했다. 처음엔 문구 끝에 번호만 붙였는데("... (관점 0)", "... (관점 1)")
  `SequenceMatcher` 비율이 여전히 0.7을 넘어(문자열 대부분이 같음) 이마저
  근접 중복으로 잡혔다 — 완전히 다른 문장 10개로 교체하고서야 통과했다.
  이 자체가 임계값 0.7이 상당히 관대(민감)하다는 실증이기도 하다.

## eval

- `cd backend && pytest`: 557 → 590 (신규 33개), 전부 통과.
  - `test_prompt_templates.py`: 프로필 공개/폐기 지시, 한국어 전용 지시
    렌더 확인(8개).
  - `test_interview_orchestrator.py`: `is_near_duplicate_question`(4개).
  - `test_language_guard.py`(신규): `contains_cjk`(4개).
  - `test_local_ollama.py`: `ollama_calls` 픽스처에 `content_queue`(순차
    응답) 지원 추가 → 1차 오염·2차 정상 재시도 성공/실패 케이스(8개).
  - `test_interview.py`: 후속 질문 `None` 처리, 근접 중복 억제(드릴다운·
    후속 각각), 건너뛰기 성공/각 409 케이스, 건너뛴 질문의 `asked_questions`
    등록·리뷰 미노출·예산 소비(11개).
- 프론트 `npx tsc --noEmit`: 내가 건드린 파일 기준 오류 0(기존에도 있던,
  무관한 `LayoutProps` 오류 2건은 `next build`를 아직 안 돌려 생성 타입이
  없어서 나는 것 — 이 작업과 무관).
- `npx eslint`: 변경한 4개 프론트 파일 전부 클린.

## 남은 작업

- [ ] 실계정 재현 — 프로필에 무관한 희망직무가 저장된 상태로 드릴다운을
      여러 턴 태워 공개 문구가 실제로 붙는지, 정정 후 프로필을 더 이상
      안 쓰는지, 같은 질문이 3번째로 반복되지 않는지 확인.
- [ ] 실계정에서 "건너뛰기" 버튼이 드릴다운/후속 질문에서만 뜨는지, 고정
      질문에는 안 뜨는지, 눌렀을 때 텍스트 입력 없이 다음으로 넘어가는지
      확인.
- [ ] 실제 로컬 Ollama로 여러 턴을 태워 질문/확정 사실에 한자가 안 섞이는지,
      모델이 여전히 흘릴 경우 경고 로그가 찍히고 오염된 후보만 조용히
      빠지는지 확인.
- [ ] `NEAR_DUPLICATE_QUESTION_THRESHOLD=0.7`이 실사용에서 너무 빡빡한지
      (정말 다른 드릴다운 질문을 오탐으로 억제) 관찰 — 트러블슈팅에서 본
      대로 상당히 관대한 임계값이라 필요하면 낮출 것.

## 관련 커밋

- (머지 전 — `fix/interview-profile-disclosure-skip-cjk-guard` 브랜치, 별도
  worktree에서 작업)
