# Phase 1. 게스트 세션 + 세션 목록 사이드바 devlog

관련 spec: [docs/specs/phase1_guest_sessions_and_sidebar.md](../../specs/phase1_guest_sessions_and_sidebar.md)
날짜: 2026-09-03

---

이건 원래 마일스톤 체크리스트(00_shared, person_A, person_B)에 있던 항목이 아니라, 인터뷰 마법사 UI를 Claude Desktop처럼 하나의 채팅창으로 바꾸는 4단계 재설계의 첫 단계다. 대응하는 체크리스트 파일이 없어서 이 devlog는 checklist 대신 spec 문서에 대응한다.

## 완료 항목

- `users` 테이블에 `is_guest` 추가, `email`/`password_hash`를 nullable로 완화하는 마이그레이션(`e28bf881dfa3`) — 실 Supabase에 적용 완료
- `POST /auth/guest` (게스트 로그인), `POST /auth/register` 수정(게스트 인증 상태로 호출하면 새 행을 만드는 대신 그 행을 업그레이드)
- `get_current_user_optional` 의존성 (`app/core/deps.py`)
- `POST /sessions` 게스트 1개 제한(`guest_session_limit_reached`), `GET /sessions` 목록 신규
- 프론트: 좌상단 `AuthHeader`, `frontend/app/sessions/layout.tsx` 우측 세션 사이드바, 홈 화면 게스트 CTA, 회원가입 페이지의 게스트 업그레이드 처리(`refreshUser` 후 `/login`이 아니라 `/`로 이동)
- 백엔드 테스트 10개 추가(`test_auth.py`, 신규 `test_sessions.py`), 프론트 e2e 2개 추가(`e2e/guest.spec.ts`)
- 실 Supabase에 대고 curl로 게스트→세션 생성→2번째 세션 409→회원가입 업그레이드→같은 토큰으로 `/me` 재조회까지 전체 흐름 재확인, Playwright로 브라우저 레벨까지 재확인. 테스트로 만든 행은 전부 삭제.

## 핵심 결정 사항과 이유

**게스트 = `is_guest=True`인 평범한 `User` 행.** 세션에 `user_id` 없이 떠 있는 별도 상태를 만들지 않고 기존 인증 인프라(JWT 발급, 리프레시 쿠키, `get_owned_session`)를 그대로 재사용하기 위한 선택. 액세스 토큰이 `user_id`만 담고 있어서, 회원가입 시 그 행에 email/password를 채우고 `is_guest`만 끄면 —데이터 이관도, 토큰 재발급도 없이— 세션이 그대로 이어진다. 자세한 설계 이유는 spec 문서 참고.

**`get_current_user_optional`은 "헤더 없음"과 "헤더는 있는데 무효"를 구분한다.** 후자도 조용히 익명 취급해버리면, 30분 지나 만료된 게스트 토큰으로 회원가입을 시도했을 때 그걸 놓치고 새 익명 계정을 만들어버려 게스트의 기존 세션이 고아가 된다. 그래서 헤더가 있는데 깨졌으면 기존 `get_current_user`와 동일하게 401을 던지고, 프론트의 기존 401→refresh→재시도 로직이 알아서 처리하게 둔다.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `test_list_sessions_returns_own_sessions_newest_first`가 간헐적으로 순서가 뒤바뀜 | `sessions.created_at`이 `server_default=func.now()`인데, SQLite는 (Postgres와 달리) 이 값을 초 단위까지만 해상도로 돌려줘서 빠르게 연달아 만든 두 세션이 같은 타임스탬프로 찍혀 정렬이 불안정해짐 | 테스트에서 두 번째 생성 전에 `time.sleep(1.1)`로 초 경계를 강제로 넘김. 실제 Postgres는 마이크로초 단위라 운영 환경에선 발생하지 않는 테스트 전용 이슈 |
| `.env` 값 확인용 `grep -v -i "password\|secret\|key"` 명령이 `DATABASE_URL` 값(비밀번호 평문 포함)을 그대로 출력함 | 필터가 "그 줄에 password/secret/key라는 **단어**가 있는가"만 봤는데, `DATABASE_URL=postgresql+asyncpg://user:실제비밀번호@host/db` 줄 자체엔 그런 단어가 없어서 걸러지지 않음 — [01_auth.md](01_auth.md)의 사고와 같은 "정규식/키워드로 자격증명을 가리려다 실패"하는 패턴이 반복됨 | 즉시 사용자에게 노출 사실을 알리고 DB 비밀번호 재발급을 권고. **교훈(반복 확인): 자격증명이 포함될 수 있는 줄은 애초에 절대 통째로 출력하지 말 것 — 값의 존재 여부만 `grep -q`로 확인하거나, 파일을 읽지 않고 별도 non-secret 설정 파일로 분리하는 방향이 근본적으로 더 안전함** |

## 남은 작업

없음 — Phase 1 범위 전체 완료. 다음은 Phase 2(기간입력·카테고리선택·기록물업로드·인터뷰를 하나의 채팅 UI로 통합) — 착수 시 별도 spec 문서 작성 예정.
