# 57. 문답 기록 초기화 기능 (2026-09-17)

devlog 56(프로필 초기화)의 연장 — 사용자 요청: "문답 기록 초기화 기능까지
추가". `/archive` 페이지엔 `user_attributes` 일괄 초기화는 이제 있지만,
바로 아래 "문답 기록"(`InterviewAnswer` 아카이브)엔 여전히 개별 삭제
(`DELETE /me/answers/{id}`)뿐이었다.

## 무엇을

- 신규 서비스 함수 `attrs.forget_all_answers(db, user_id)` — 기존
  `forget_answer(db, user_id, answer_id)`의 전체 버전. 답변 하나를 지울 때
  하던 정리(그 답변에서 추정한 `inferred` 속성은 삭제, 나머지는
  `evidence_text`/`source_answer_id`만 비움)를 계정의 모든 답변에 대해
  한 번에 한다.
- 신규 `POST /me/answers/reset` — `AnswersResetRead{reset_count}`를 돌려주고,
  `InterviewAnswer`를 전부 지우기 전에 `forget_all_answers`를 먼저 불러
  연결된 속성부터 정리한다(개별 삭제와 순서 동일).
- 프론트: `/archive`의 "문답 기록" 제목 옆에 "문답 기록 초기화" 버튼 —
  기록이 있을 때만 보이고, `window.confirm`으로 확인한 뒤 문답 아카이브와
  속성 쿼리를 함께 무효화한다(삭제된 답변에서 추정된 속성이 사라질 수
  있으므로).

프로필 초기화(devlog 56)와 다른 점: 여기는 `rejected`처럼 "재추정 차단"
개념이 아예 없다 — 답변 원문(`InterviewAnswer`)은 애초에 재추정의 대상이
아니라 그냥 사라지는 기록이므로, 개별 삭제든 전체 초기화든 항상 완전
삭제다. 그래서 이번 기능은 개별 삭제 로직을 사용자 범위로 넓히기만 하면
됐고, 프로필 초기화처럼 "삭제 방식을 다르게 할지" 고민할 지점이 없었다.

## 검증

- `cd backend && pytest` — 610 passed (기존 607 + 3개: 전체 삭제와 개수
  반환, 연결된 추정 속성까지 정리되는지, 다른 사용자에게 영향 없는지).
- `cd frontend && npx tsc --noEmit` — 새 타입 오류 없음(기존 무관한
  `LayoutProps` 오류 2건만).

## 남은 작업

- [ ] 배포 후 실계정에서 "문답 기록 초기화" 버튼이 실제로 목록을 비우고,
      그 답변들에서 나온 프로필 속성도 함께 사라지는지 확인.

## 관련 커밋

- (머지 전 — `feat/answers-reset` 브랜치, 별도 worktree에서 작업)
