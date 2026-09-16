# 55. 카테고리 분류 오배정 수정 + 인터뷰 요청 무한 대기 방지 (2026-09-17)

배포 후 재검증(devlog 54의 실계정 검증 라운드를 배포 이후 다시 돌린 것)에서
새로 나온 문제 중 두 가지를 이번 라운드에서 고쳤다. 프로필 공개·모순 시
폐기(devlog 54의 Fix 1a)는 재검증에서도 여전히 실효성이 없다는 게 확인됐지만,
이번 라운드에서는 의도적으로 손대지 않기로 했다 — 프롬프트 지시만으로는 안
된다는 게 두 번째로 확인된 셈이라, 다음에 다시 붙잡을 때는 코드가 직접
판단·삽입하는 방식으로 접근을 바꿔야 한다(아래 "남은 작업" 참고).

## 무엇을

### 1. 카테고리 질문 은행 오배정 — internship/club 신설 + 재분류 기능

6인 페르소나 검증 두 라운드 모두에서 재현된 문제: 3개월짜리 정규 인턴십이
"아르바이트" 질문 은행으로("이 아르바이트를 얼마나 자주..."), 가벼운 독서
모임이 "자격증 공부" 질문 은행으로("무엇을 목표로 공부/자격증 준비를...")
배정됐다. 원인은 `CATEGORY_TYPES`가 8종뿐이라 인턴십·동호회 패턴이 어디에도
자연스럽게 안 맞았기 때문 — LLM은 강제로 가장 가까운 걸 골라야 했다.

- `app/models/activity_category.py`의 `CATEGORY_TYPES`에 `internship`,
  `club` 추가 (CHECK 제약도 같이 넓힘 — 마이그레이션
  `b7e2f4a9c1d5_widen_category_types_internship_club`).
- `interview_question_bank.py`에 두 유형 전용 고정 질문 5종/4종 추가 —
  internship은 part_time과 달리 "얼마나 자주 알바했냐"가 아니라 맡은
  업무·전환 여부를 묻고, club은 study와 달리 "공부 목표"가 아니라 모임
  성격과 얻은 것을 묻는다.
- `extract_categories.jinja`에 10종 목록 + part_time/internship,
  study/club을 가르는 기준 문장 + 예시 1개 추가.
- 신규 `PATCH /{session_id}/categories/{category_id}/type` — 분류가
  잘못됐을 때 사용자가 직접 바로잡는다. **아직 아무것도 답하지 않은
  카테고리에서만 허용**한다(`draft_turns`와 `confirmed_facts`가 둘 다
  비어 있어야 함) — 고정 질문의 fact_type 슬롯이 유형마다 달라서, 이미
  답한 뒤에 유형을 바꾸면 새 질문 은행이 이미 답한 슬롯을 다시 셀 수
  없어 순서가 어긋난다. 캐시된 `pending_turn`이 이 카테고리를 가리키면
  같이 비워서, 다음 `/interview/ask`가 새 유형의 질문으로 다시 만들게
  했다 — 안 지우면 `/ask`의 idempotent 캐싱 때문에 옛 유형 질문 문구가
  그대로 다시 나온다.
- 프론트: 질문 옆에 "분류가 이상한가요?" 드롭다운 + "바꾸기" 버튼을
  현재 카테고리가 아직 아무것도 안 답한 상태일 때만 노출(백엔드와 같은
  조건).

### 2. 장시간 세션에서 인터뷰 요청이 영원히 멈추는 문제

배포 후 재검증 중 하네스가 새로 찾은 진짜 프로덕션 버그: 1시간 이상 이어진
세션에서 답변 제출 후 채팅 UI가 "답변을 정리하고 다음 질문을 준비하고
있어요"에 영구히 멈췄다 — 서버는 답변을 실제로 저장했는데(네트워크 탭으로
확인) 클라이언트만 멈춘 상태였다.

원인: `frontend/lib/api/client.ts`의 `request()`/`withAuthRetry()`가 쓰는
`fetch()` 호출 어디에도 타임아웃이 없었다. 액세스 토큰 재발급(401 → refresh
→ 재시도) 왕복 어딘가에서 네트워크가 멈추면(1시간 이상 열려 있던 탭에서
있을 법한 상황), `await`가 영원히 안 끝나 `submitAnswer`의
`try/catch/finally`가 아예 발동하지 않았다 — `finally`는 프라미스가
"끝나야만" 실행되기 때문이다. `frontend/lib/use-session-context.ts`에 이미
같은 클래스의 버그(devlog 20, job-search 무한 대기)를 고친 선례가 있었는데
(`Promise.race` + `SESSION_FETCH_TIMEOUT_MS=65000`), 그건 세션 GET 쿼리
하나에만 적용돼 있었고 인터뷰 관련 호출들은 보호되지 않고 있었다.

- `frontend/lib/api/job-search.ts`가 이미 쓰고 있던(devlog 20)
  `signal: AbortSignal.timeout(ms)` 패턴을 그대로 재사용 —
  `interviewAsk`/`interviewAnswer`/`interviewSkip`/`interviewConfirm`/
  `interviewReview`/`retypeCategory` 전부에 `INTERVIEW_TIMEOUT_MS=65_000`
  적용(Render 콜드 스타트도 버틸 만큼 넉넉한 값 — `use-session-context.ts`와
  같은 값을 재사용).
  `error-messages.ts`가 이미 `AbortSignal.timeout()`이 던지는
  `TimeoutError` DOMException을 처리하고 있어서(job-search 때 이미
  붙여둔 코드) 별도 에러 문구 작업은 필요 없었다.
- `client.ts`의 공용 `request()`를 건드리는 대신 각 호출부에 `signal`을
  붙이는 쪽을 택했다 — `job-search.ts`가 이미 이 패턴이라 새 관례를
  만들지 않고 기존 관례를 따름.

## 트러블슈팅

- 새 테스트 하나가 `/interview/answer`에서 `409 no_pending_question`으로
  실패 — `_advance_to_first_category` 헬퍼는 첫 실제 질문까지 "위치만"
  잡아줄 뿐 `pending_turn`을 만들어두진 않는다는 걸 놓쳤다.
  `/interview/ask`를 한 번 더 불러야 실제로 답할 수 있는 상태가 된다
  (기존 `test_deeper_category_specific_questions_for_study_and_part_time_differ`도
  같은 패턴을 쓰고 있었다).
- 로컬 공유 dev DB(`annswieteom-dev` Supabase, 이 노트북의 모든 세션이
  공유)가 이 워크트리가 아는 마이그레이션 head보다 앞서 있어서(다른
  동시 세션의 브랜치가 자체 마이그레이션을 이미 적용해둔 상태)
  `alembic upgrade head`를 로컬에서 직접 검증하지 못했다 — 공유 DB를
  건드릴 위험이 있어 중단했다. 마이그레이션 자체는 기존에 검증된 패턴
  (`a2b3c4d5e6f7_widen_fact_types_content_technical`)을 그대로 복제한
  것이라 코드 리뷰로 갈음했고, 실제 적용은 배포 파이프라인에 맡긴다.

## 검증

- `cd backend && pytest` — 603 passed (기존 595 + retype 엔드포인트 테스트
  7개 + internship/club 질문 은행 구분 테스트 1개).
- `cd frontend && npx tsc --noEmit` — 새 타입 오류 없음(기존에 있던,
  무관한 `LayoutProps` 오류 2건만 그대로 — `next dev`/`next build`가
  만드는 생성 타입이라 워크트리에 없는 게 정상).
- 로컬 dev DB에 마이그레이션 실적용은 못 함(위 트러블슈팅 참고) — 배포
  후 실계정으로 재확인 필요.

## 남은 작업

- [ ] 배포 후 실계정에서 internship/club 분류가 실제로 잘 나뉘는지,
      "분류가 이상한가요?" 컨트롤이 첫 질문 옆에 뜨고 바꾼 뒤 질문이
      실제로 새 유형으로 바뀌는지 확인.
- [ ] 배포 후 장시간(1시간 이상) 세션을 다시 태워 무한 로딩이 실제로
      재현 안 되는지, 타임아웃이 발동했을 때 에러 문구가 자연스러운지
      확인.
- [ ] 프로필 공개·모순 시 폐기(devlog 54 Fix 1a)는 두 라운드 연속으로
      프롬프트 지시만으론 실패했다 — 다음에는 (1) 공개 문구를 모델이
      "자연스럽게" 넣게 하는 대신 코드가 매칭·삽입하는 방식, (2) 모순되는
      프로필 속성을 프롬프트로 "무시하라"는 대신 그 즉시
      `user_attributes.status`를 `rejected`로 DB에 직접 반영하는 방식으로
      접근을 바꿔서 다시 시도할 것.

## 관련 커밋

- (머지 전 — `fix/category-templates-and-session-timeout` 브랜치, 별도
  worktree에서 작업)
