# 52. 게스트 세션 개수 제한 제거 (2026-09-15)

## 무엇을

`POST /sessions`에서 게스트(`is_guest=True`)가 이미 세션을 1개 이상 갖고 있으면 `409
guest_session_limit_reached`를 던지던 체크를 제거했다. 사용자 요청이다 — "비회원이 생성 가능한
세션 수에 제한을 두지 말자. 단 저장되는 것은 회원가입을 한 후로."

## 왜 두 번째 조건("저장은 회원가입 후")을 별도로 구현하지 않았는가

Phase 1 설계([docs/specs/phase1_guest_sessions_and_sidebar.md](../../specs/phase1_guest_sessions_and_sidebar.md))부터
게스트는 특수한 익명 상태가 아니라 `email`/`password_hash`가 `NULL`인 평범한 `users` 행이고,
세션은 생성되는 즉시 그 행에 딸려 DB에 저장된다. 회원가입("업그레이드")은 같은 행에 email/password를
채우고 `is_guest`를 끄는 것뿐 — 데이터 이관이 없다. 즉 "게스트 세션은 회원가입 전엔 저장 안 됨"으로
바꾸려면 인터뷰 상태 머신·`confirmed_facts`·`record_chunks` 등 여러 계층을 관통하는 재설계가 필요하다.

사용자에게 범위를 확인한 결과([[feedback_present_options_for_problems]] 패턴대로 AskUserQuestion으로
제시), "1개 제한만 제거" 쪽을 선택받았다 — 게스트 데이터는 지금처럼 즉시 저장되고, 회원가입은 여전히
그 신원을 영구화(쿠키 삭제에도 살아남게)하는 역할만 한다.

## 완료

- [x] `backend/app/api/sessions.py`: `guest_session_limit_reached` 체크 삭제, 미사용 `func` import 제거
- [x] `backend/app/api/profile.py`: `_require_registered`의 주석이 삭제된 1세션 제한을 근거로 들고
      있어서, "게스트 신원은 쿠키 삭제로 버려질 수 있는 임시 신원이라 누적 기록의 주인이 되기 부적합"으로
      다시 씀 (동작 자체는 안 바뀜 — 게스트는 여전히 `/me/answers` 아카이브 접근 불가)
- [x] `backend/tests/api/test_sessions.py`: `test_guest_second_session_returns_409` →
      `test_guest_can_create_multiple_sessions`로 교체
- [x] `frontend/lib/error-messages.ts`: 더 이상 백엔드가 보내지 않는 `guest_session_limit_reached`
      매핑 삭제
- [x] `frontend/e2e/guest.spec.ts`: 두 번째 세션 생성 시 제한 메시지를 기대하던 단정을 201 성공 + 세션
      페이지 이동 확인으로 교체
- [x] `docs/specs/phase1_guest_sessions_and_sidebar.md` 갱신 (제한 제거 반영, "동시에 1개" 서술 삭제)
- [x] `pytest tests/api/test_sessions.py tests/api/test_profile.py` 21 passed

## 남은 작업

- 게스트가 등록 없이 세션을 무제한으로 만들 수 있게 되어 방치되는 게스트 행이 이전보다 빠르게 쌓일 수
  있다. Phase 1 spec이 이미 "게스트 세션 정리(cleanup)는 범위 밖"이라고 명시해 뒀던 사안이라 이번
  변경으로 새로 생긴 문제는 아니지만, 무제한 생성이 그 압력을 키우므로 다음에 손댈 후보로 적어 둔다.
