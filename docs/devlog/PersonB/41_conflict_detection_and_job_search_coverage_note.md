# 41. 카테고리 리뷰 모순 탐지 + 취업정보 검색 미지원 안내 (2026-09-13)

대화형 서비스 다양성 테스트(A~I) 중 발견된 2건을 고쳤다.

## 완료

### Case D — 카테고리 리뷰 단계 모순 탐지
편의점 알바 카테고리에서 "주 3회 저녁 6~10시"와 "주 6일 새벽 5~9시"라는 서로 양립
불가능한 두 근무 스케줄을 둘 다 확인시킨 뒤 문서를 생성하면, LLM이 둘을 한 문장으로
그대로 병합하고 아무 경고도 없었다. `consistency_check.py`는 애초에 "문장이 인용한
근거와 의미상 가까운가"만 검사(할루시네이션 방지)하고 사실 간 논리적 모순은 검사
대상이 아니었다 — 임계값을 조정해도 이 클래스는 못 잡는다.

- `LLMProvider.detect_fact_conflicts(facts: list[str]) -> list[FactConflict]` 신규
  (`app/services/llm/base.py`, `local_ollama.py`), 새 프롬프트
  `app/prompts/detect_fact_conflicts.jinja`.
- `app/api/interview.py`의 `_annotate_fact_conflicts`가 카테고리가 리뷰로 넘어가는
  두 지점(`interview_ask`/`interview_answer`의 `decision == "review"` 분기)에서 딱
  한 번 호출돼, 카테고리의 모든 turn에 걸친 draft를 모아 한 번의 LLM 호출로 모순을
  찾고 `draft_turns`에 박아 넣는다. `_review_read`(새로고침 복원 경로, LLM 호출 없음이
  전제)는 저장된 값만 읽는다 — 계산과 조회를 분리해 idempotent restore 계약을 안
  깼다.
- `FactCandidateRead.conflict_with: list[ConflictRefRead]` 추가(리뷰 카드 응답).
  turn_id+index 조합으로 상대를 가리킨다 — 같은 카테고리라도 다른 턴의 draft를
  가리킬 수 있어 전역 인덱스로는 부족하다.
- 프론트(`InterviewChatThread.tsx`)는 `conflict_with`가 있는 draft에 경고 문구만
  붙인다. 확정을 막지 않는다 — `consistency_check`가 "flag만 남기고 자동 삭제하지
  않는다"는 철학과 동일하게, 판단은 사용자에게 맡긴다.

### Case G — 지원하지 않는 취업정보 카테고리 안내
"경기 카페 알바랑 관련 직업훈련 같이 알려줘"에 직업훈련 결과만 오고 알바 채용정보는
응답에서 통째로 빠졌다. 조사 결과 라우팅 버그가 아니라 데이터 소스 공백이었다 — 이
앱이 연동한 고용24 9개 엔드포인트(공채속보/채용기업/훈련4종/취업프로그램/강소기업)
중 아르바이트·파트타임 채용정보를 다루는 것이 하나도 없다. 분류기는 정확히 판단한
것이고(카페 알바는 6개 카테고리 어디에도 없음 → training_course만 선택), 그걸
사용자에게 알려주지 않는 게 문제였다.

새 데이터소스 연동(Work24 API 신청 등 인프라 작업)은 범위 밖으로 확정하고, 정직한
미지원 안내만 추가했다:

- `classify_job_info_query.jinja` 출력에 `unsupported_note`(질문에 6개 카테고리
  어디에도 안 걸리는 부분이 있으면 그 설명, 없으면 null) 추가.
- `LLMProvider.classify_job_info_query`가 `tuple[list[JobInfoCategoryQuery], str | None]`
  을 반환하도록 시그니처 변경(호출부 하나뿐 — `app/api/job_search.py`).
- `JobInfoQueryRead.unsupported_note` 추가. 카테고리가 매칭됐든 하나도 안 됐든
  둘 다 실릴 수 있다(전자는 결과와 함께, 후자는 `clarification_question` 대신).
- 프론트(`JobSearchChatPage.tsx`)는 `skippedCategoryLabels`("골랐지만 조회 실패")와
  구분되는 별도 말풍선으로 렌더링한다 — 하나는 "이번엔 실패", 하나는 "애초에 안 다룸".

## 핵심 결정과 이유

**Case D를 문서 생성 시점이 아니라 카테고리 리뷰 시점에 잡았다.** 리뷰 카드는
`confirmed_facts`로 넘어가기 전 마지막 지점이라 사용자가 "고쳐 쓰기"/"제외하기"로
바로 고칠 수 있다. 문서 생성 시점에 잡으면 이미 확정된 사실이라 되돌리려면 다시
리뷰로 가야 해서 UX가 나쁘다.

**모순 탐지를 차단이 아니라 경고로만 뒀다.** 스케줄이 실제로 바뀐 경우(예: "처음엔
저녁 근무였는데 나중엔 새벽 근무로 바뀌었다")와 진짜 모순을 사실 목록만으로 항상
구분할 수는 없다. 프롬프트도 "애매하면 포함해라"로 짰다 — 확정을 막으면 애매한
경우까지 사용자를 막게 되고, 경고만 하면 사용자가 직접 판단해서 넘어갈 수 있다.

**계산과 조회를 분리했다(`_annotate_fact_conflicts` vs `_review_read`).**
`_review_read`는 새로고침 복원 경로에서도 불리는데, 그 경로는 "LLM 호출 없음"이
설계 전제다(`test_ask_during_review_returns_the_review_without_calling_the_llm`이
이미 지키고 있었다). 리뷰 진입 시점에 한 번만 계산해 `draft_turns`에 저장해두는
쪽을 택해 이 계약을 안 건드렸다.

**Case G는 데이터 확장 대신 정직한 안내를 택했다(사용자 결정).** Work24 API에
아르바이트/파트타임 전용 엔드포인트가 없어, 새 데이터소스 연동은 별도 인프라
작업(API 키 신청, 승인 대기)이 필요하다 — 이번 범위에서는 "못 찾았다"를 조용히
넘기지 않고 명시적으로 알려주는 것까지만 했다.

## 검증

pytest 507개 통과(신규 11개: local_ollama의 conflict 탐지 4종 + unsupported_note
1종, interview review 모순 탐지 2종, job_search unsupported_note 2종 — 기존
`test_classify_drops_hallucinated_category_names`도 튜플 반환에 맞게 수정).
프론트 `tsc --noEmit` 통과.

**스테이징/실계정에서만 가능(자동화 불가)**:
- Case D 재현 시나리오를 다시 리뷰 카드까지 진행해 경고 배지가 실제로 뜨는지 확인.
- Case G 재현 질의를 다시 보내 훈련 결과와 미지원 안내가 함께 뜨는지 확인.
- 로컬 dev의 약한 모델(qwen2.5:3b)로는 두 신규 판정의 실제 품질을 가늠하기 어렵다 —
  프로덕션 터널(qwen3.5:35b-a3b)로 확인 필요.

## 관련 커밋

- (머지 전)

## 남은 작업

- [ ] 스테이징/실계정 재현 테스트 2건 (위 검증 항목)
- [ ] 카테고리 간 모순(예: 카테고리1 "주 6일 근무"와 카테고리2 "매일 8시간 공부"의
      시간 총량 충돌)은 범위 밖으로 남겨뒀다 — 필요성이 확인되면 후속 작업.
- [ ] Work24 아르바이트/파트타임 채용정보 API 신청 여부는 별도 결정 필요(Person A).
