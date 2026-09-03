# B-1. 인증 (이메일 + 비밀번호)

근거: 명세서 7절, 9-1절
선행 조건: [00_shared/02_database_schema.md](../00_shared/02_database_schema.md) (`users`, `refresh_tokens` 테이블)
폴더: `backend/app/api/auth.py`, `backend/app/core/security.py`, `backend/app/core/deps.py`
브랜치: `feature/auth` (`dev`에서 분기, 완료 후 `dev`로 PR — 프론트 로그인/회원가입 화면도 이 브랜치에서 함께 작업)
시점: 1주차

> **용어**: JWT(JSON Web Token)는 로그인한 사용자를 식별하기 위해 서버가 발급하는, 위조 방지 서명이 붙은 문자열이다. 브라우저는 API 요청마다 이 토큰을 함께 보내고, 서버는 서명을 검증해 "이 요청이 진짜 이 사용자가 보낸 것"임을 확인한다.

## 1. 비밀번호 처리 (`core/security.py`)

- [x] `passlib[bcrypt]`로 비밀번호 해싱 함수(`hash_password`, `verify_password`) 작성 — ⚠️ `bcrypt>=4.1`은 passlib 1.7.4와 호환 안 됨(`__about__.__version__` 속성 제거됨, "password cannot be longer than 72 bytes" 에러 발생). `requirements.txt`에 `bcrypt==4.0.1` 고정해서 해결
- [x] 평문 비밀번호는 어떤 경로로도 로그·DB에 남지 않도록 확인 — 해시만 저장, 로그 출력 없음 (`test_hash_password_never_stores_plaintext`)

## 2. JWT 발급/검증 (`core/security.py`)

- [x] `python-jose[cryptography]`로 Access Token(만료 30분) 발급 함수 작성
- [x] Refresh Token(만료 14일)은 무작위 문자열로 생성하고, DB에는 SHA-256 해시만 저장 (원문은 저장하지 않음, 6-2절)
- [x] `JWT_SECRET` 환경변수로 서명

## 3. API 구현 (`api/auth.py`)

- [x] `POST /auth/register`: `{email, password, nickname}` → 이메일 중복 확인 후 `users` insert, `{"user_id": UUID}` 반환. 중복 시 `409 email_already_exists`
- [x] `POST /auth/login`: 이메일로 사용자 조회 → 비밀번호 검증 → 성공 시 Access Token을 응답 바디로, Refresh Token을 쿠키로 내려줌. 실패 시 `401 invalid_credentials`
  - ⚠️ **쿠키 속성 관련 배포 시 주의**: 명세서 7-1절은 `httpOnly + Secure + SameSite=Lax`로 적어뒀지만, 이 프로젝트는 프론트(Vercel, `*.vercel.app`)와 백엔드(Railway, `*.up.railway.app`)가 **서로 다른 최상위 도메인**에 배포된다(15절). `SameSite=Lax` 쿠키는 이런 교차 사이트(cross-site) JS 요청(프론트에서 fetch로 `/auth/refresh` 호출)에는 브라우저가 아예 실어 보내지 않아, **로컬 개발(둘 다 localhost라 문제없음)에서는 잘 되다가 배포 후에만 로그인 유지가 깨지는** 상황이 생긴다. 배포본에서는 `SameSite=None; Secure`(HTTPS 필수, Railway/Vercel 모두 기본 제공)로 설정한다. `httpOnly`는 그대로 유지
    - [x] 구현 완료: `settings.environment`(신규 config 값, 기본 `development`)로 로컬은 `Lax`, `production`은 `None; Secure`로 자동 전환 (`app/api/auth.py`의 `_refresh_cookie_kwargs`). Railway 배포 시 `ENVIRONMENT=production` 환경변수 설정 필요
  - 이에 맞춰 FastAPI `CORSMiddleware`에 `allow_credentials=True`를 추가하고, 프론트의 `fetch`/axios 호출에 `credentials: "include"`를 반드시 붙인다(안 그러면 브라우저가 쿠키를 아예 요청에 담지 않는다) — [00_shared/01_repo_and_env_setup.md](../00_shared/01_repo_and_env_setup.md)의 CORS 설정과 [05_frontend_routes_components.md](05_frontend_routes_components.md)의 `lib/api-client.ts`에 함께 반영 — `frontend/lib/api-client.ts`에 이미 반영됨
- [x] `POST /auth/refresh`: 쿠키의 Refresh Token 해시를 `refresh_tokens`에서 조회(만료·revoked 확인) → 새 Access Token 발급
- [x] `POST /auth/logout` 🔒: 현재 Refresh Token을 `revoked_at` 처리, 204 반환
- [x] `GET /auth/me` 🔒: 현재 로그인된 사용자 정보 반환

## 4. 인증 의존성 (`core/deps.py`)

- [x] `get_current_user` FastAPI 의존성: Authorization 헤더의 Access Token을 검증해 `User` 객체 주입 — 이후 모든 🔒 API에서 재사용
- [x] 만료/위조 토큰은 `401`로 응답

## 4-1. 세션 소유권 검증 의존성 (사용자별 데이터 격리의 실제 강제 지점 — 필수)

이 서비스의 모든 데이터(`gap_periods`, `activity_categories`, `confirmed_facts`, `records`, `generated_documents` 등)는 `sessions.user_id`를 거쳐 특정 사용자에게 귀속된다(6-11절 관계 요약). 이 격리가 실제로 지켜지려면, `/sessions/{id}/...` 아래의 **모든** 엔드포인트가 매번 "이 세션이 정말 요청자 소유인가"를 확인해야 한다 — 9-6절이 `403(타인 세션 접근)`을 공통 에러로 정의해둔 것도 이 때문이다.

- [x] `get_owned_session(session_id: UUID, current_user: User = Depends(get_current_user)) -> Session` 의존성 작성: `session_id`로 세션을 조회해 없으면 `404`, 있는데 `session.user_id != current_user.id`면 `403` 반환, 맞으면 `Session` 객체 주입. FastAPI는 경로 파라미터를 이름으로 매칭하므로, 이 의존성을 쓰는 모든 라우트 데코레이터의 경로도 `@router.post("/sessions/{session_id}/period")`처럼 `{id}`가 아니라 `{session_id}`로 통일해서 쓴다(9절 API 표의 `{id}` 표기는 설명 편의상 축약한 것일 뿐, 실제 구현에서의 변수명까지 `id`로 맞출 필요는 없다)
- [ ] 이 의존성을 [02_interview_state_machine_api.md](02_interview_state_machine_api.md)(`sessions`, `interview`), [03_records_feature.md](03_records_feature.md)(`records`), [04_document_generation.md](04_document_generation.md)(`document`)의 **모든** `/sessions/{id}/...` 엔드포인트에서 공통으로 사용 — 개별 라우터마다 소유권 검증 코드를 따로 작성하지 않도록 여기서 한 번만 구현 — **의존성 자체는 준비됨, 실제 사용은 02~04 작업 시 진행**
- [ ] `document/sentences/{sentence_id}`처럼 세션보다 더 안쪽 리소스를 다루는 엔드포인트는, 먼저 `get_owned_session`으로 세션 소유권을 확인한 뒤 그 세션 하위에 `sentence_id`가 실제로 속하는지(다른 세션의 문장 ID를 잘못 넣은 경우 `404`)까지 확인 — 04 작업 시 진행

## 검증 기준 추가 (사용자별 데이터 격리)

- [x] `get_owned_session` 단위 테스트로 확인: 소유자가 아닌 사용자가 호출하면 `403`, 존재하지 않는 세션이면 `404` (`tests/core/test_deps.py`) — 실제 `/sessions/...` 라우트가 아직 없어 엔드투엔드 확인은 02~04에서
- [ ] 존재하지 않는 세션 ID로 호출하면 `404`가 반환된다 — 위와 동일, 라우트 생기면 재확인

## 5. 비밀번호 검증 규칙 (7-2절)

- [x] 최소 8자 이상 — 백엔드(`UserCreate.password: str = Field(min_length=8)`)에서 확인. 프론트 폼에도 `minLength={8}` 반영

## 6. 최소 프론트 화면

- [x] `frontend/app/register/page.tsx`: 이메일/비밀번호/닉네임 입력 폼
- [x] `frontend/app/login/page.tsx`: 이메일/비밀번호 입력 폼, 성공 시 Access Token을 React Context(`frontend/lib/auth-context.tsx`)에 저장
- [x] Access Token은 메모리(React state/Context)에만 보관, localStorage에 저장하지 않음 — 새로고침 시 `/auth/refresh`로 재발급 (`AuthProvider`의 초기 `useEffect`가 처리)

## 검증 기준 (마일스톤 1)

- [x] 회원가입 → 로그인 → 발급받은 Access Token으로 `GET /auth/me` 호출이 실제로 사용자 정보를 반환한다 — 실제 uvicorn 서버 + curl로 라이브 검증(2026-09-02, 임시 SQLite), **실 Supabase로 재검증 완료(2026-09-02)**
- [x] 잘못된 비밀번호로 로그인 시 `401`이 반환된다 — 실 Supabase로 검증 완료
- [x] 이미 가입된 이메일로 재가입 시도 시 `409`가 반환된다 — 실 Supabase로 검증 완료
- [x] Access Token 없이 🔒 API를 호출하면 `401`이 반환된다 — 실 Supabase로 검증 완료

**실 Supabase 검증 완료 (2026-09-02)**: `backend/.env` 생성 → `alembic upgrade head`로 11개 테이블 전체 생성 확인 → 위 시나리오(회원가입/로그인/me/오답401/중복409/refresh/logout revocation)를 실제 Supabase 세션 풀러 연결로 재확인, Playwright E2E 3개도 실 DB 기준으로 재실행해서 통과. 테스트로 생성된 사용자는 확인 후 삭제해서 DB에 남아있지 않음.

이 과정에서 `.env` 작성 시 흔히 겪을 함정 2개를 발견해서 기록해둔다 (다음에 또 `.env`를 새로 만들 일이 있으면 참고):
- Supabase가 대시보드에서 그대로 복사해주는 연결 문자열은 `postgresql://`로 시작하는데, 이 프로젝트는 비동기 드라이버가 필요해서 **`postgresql+asyncpg://`**로 직접 고쳐야 한다
- Supabase "Connect" 모달에 나오는 풀러 포트가 두 개(5432=Session, 6543=Transaction)인데, **Transaction 모드(6543)는 asyncpg의 prepared statement와 호환이 안 돼서 간헐적 오류가 날 수 있다** — 반드시 Session 모드(포트 5432)를 쓸 것

- [x] **실제 브라우저 클릭 테스트** — Playwright로 실제 Chromium을 띄워 회원가입 폼 작성→제출→로그인 페이지 이동→로그인 폼 작성→제출→로그인 응답에 실제 `access_token`이 들어있는지→홈으로 이동, 그리고 중복 이메일/오답 비밀번호일 때 화면에 에러 문구가 뜨는지까지 전부 실제 브라우저로 확인 완료(2026-09-02). `frontend/e2e/auth.spec.ts`, `npm run test:e2e`로 재실행 가능(백엔드가 `localhost:3000`을 CORS로 허용하고 있어야 하므로 프론트는 반드시 기본 포트 3000으로 띄울 것 — 아래 "E2E 테스트 실행법" 참고)

### E2E 테스트 실행법 (`frontend/e2e/auth.spec.ts`)

이 테스트를 실행하려면 백엔드와 프론트를 둘 다 띄워둬야 한다. 처음 실행 시 원인 파악에 시간이 걸렸던 함정 두 가지를 미리 적어둔다:

1. **Next.js 개발 서버는 기본적으로 `localhost` 오리진만 허용한다** — `127.0.0.1`로 접속하면 정적 자산 요청이 전부 `403`으로 막혀서 하이드레이션 자체가 안 되고(클릭해도 반응 없음), 폼이 브라우저 기본 GET 제출로 새로고침돼버린다. 반드시 `http://localhost:PORT`로 접속할 것 (`127.0.0.1` 금지)
2. **백엔드 CORS 허용 오리진이 `http://localhost:3000`으로 고정돼 있다** (`app/main.py`) — 프론트를 다른 포트로 띄우면 CORS에 막혀 회원가입/로그인 요청 자체가 실패한다(콘솔에 조용히 에러만 남고 화면엔 아무 반응 없음). 프론트는 반드시 **기본 포트 3000**으로 띄울 것

```powershell
# 터미널 1 — 백엔드 (임시 SQLite로 실행하는 예시, 실 DB가 있으면 그걸 써도 됨)
cd backend
$env:DATABASE_URL="sqlite+aiosqlite:///./e2e_test.db"; $env:JWT_SECRET="test-secret"
python -c "..."   # tests/api/conftest.py 참고해 users/refresh_tokens 테이블만 생성
venv\Scripts\python -m uvicorn app.main:app --port 8123

# 터미널 2 — 프론트 (기본 포트 3000 그대로)
cd frontend
$env:NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8123"; npm run dev

# 터미널 3
cd frontend
npm run test:e2e
```
