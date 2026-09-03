# B-1. 인증 (이메일 + 비밀번호) devlog

체크리스트: `docs/checklists/person_B_frontend_backend/01_auth.md`
날짜: 2026-09-02

---

## 완료 항목

- 비밀번호 해싱/검증, JWT Access Token 발급/검증, Refresh Token 생성/해시 (`app/core/security.py`)
- `POST /auth/register`, `/login`, `/refresh`, `/logout`, `GET /auth/me` (`app/api/auth.py`)
- `get_current_user`, `get_owned_session` 의존성 (`app/core/deps.py`)
- 비밀번호 최소 8자 검증 (백엔드 Pydantic + 프론트 `minLength`)
- 최소 프론트 화면: `frontend/app/register`, `frontend/app/login`, `frontend/lib/auth-context.tsx`(Access Token 메모리 보관 + 새로고침 시 refresh), `frontend/lib/api-client.ts`
- 단위/통합 테스트 25개 (`backend/tests/core/`, `backend/tests/api/`)

## 미완 항목

- `get_owned_session`을 실제 `/sessions/...` 라우트에서 사용하는 것 — 02(인터뷰 상태머신)~04(문서생성)에서 라우트가 생기는 대로 적용
- 실제 브라우저에서 로그인 버튼을 눌러 백엔드까지 왕복하는 클릭 테스트 — 브라우저 자동화 도구가 없어 못 함 (아래 "테스트 전략" 참고)

## 핵심 결정 사항과 이유

**쿠키 SameSite를 환경별로 자동 전환**: 체크리스트가 이미 짚어준 문제(로컬은 `Lax`로 되는데 배포하면 Vercel↔Railway가 서로 다른 최상위 도메인이라 쿠키가 안 실림)를 코드 레벨에서 해결했다. `app/core/config.py`에 `environment: str = "development"`를 추가하고, `app/api/auth.py`의 `_refresh_cookie_kwargs()`가 이 값을 보고 로컬은 `Lax`, `production`은 `None; Secure`를 반환한다. Railway 배포 시 `ENVIRONMENT=production` 환경변수만 추가하면 되도록 [00_shared/03_deployment.md](../../checklists/00_shared/03_deployment.md)에도 반영해뒀다.

**`api/__init__.py`를 라우터 취합 지점으로**: `api_router = APIRouter()`에 각 기능별 라우터(`auth_router` 등)를 `include_router`로 모아서 `main.py`는 `api_router` 하나만 `/api/v1` prefix로 붙이면 되게 했다. 02~04에서 새 라우터(sessions, records, document)를 추가할 때 `main.py`를 안 건드리고 `api/__init__.py`에 한 줄만 추가하면 되는 구조.

**Refresh Token 쿠키의 `path`를 `/api/v1/auth`로 제한**: 스펙엔 명시 안 돼있지만, 이 쿠키는 `/auth/refresh`와 `/auth/logout`에서만 필요하므로 다른 API 요청에까지 실려갈 이유가 없다 — 노출 범위를 줄이는 방향으로 판단.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `hash_password()` 호출 시 `ValueError: password cannot be longer than 72 bytes` + `AttributeError: module 'bcrypt' has no attribute '__about__'` | `passlib==1.7.4`가 `bcrypt` 백엔드 초기화 시 `bcrypt.__about__.__version__`을 읽는데, `bcrypt>=4.1`부터 이 속성이 제거됨. `pip install`이 최신 bcrypt(5.0.0)를 끌고 오면서 발생 | `requirements.txt`에 `bcrypt==4.0.1` 명시적으로 고정 |
| `/auth/refresh`에서 `TypeError: can't compare offset-naive and offset-aware datetimes` | 테스트에 쓴 SQLite가 `DateTime(timezone=True)` 컬럼이어도 tzinfo를 보존하지 않고 naive datetime으로 돌려줌(Postgres/asyncpg라면 안 생길 문제지만, 어느 DB에서 실행되든 깨지지 않도록 방어하는 게 안전하다고 판단) | `security.py`에 `ensure_utc()` 헬퍼 추가, DB에서 읽은 `expires_at`을 비교 전에 정규화 |
| `pytest`가 `ModuleNotFoundError: fastapi` 등 계속 발생 | 이 PC의 Python 3.14가 매우 최신이라 `requirements.txt`의 옛 버전 핀(예: `pydantic==2.9.2`)이 프리빌드 wheel을 못 찾아 소스 빌드하다 실패(Rust 툴체인 필요 등) — [[project-a6-consistency-check]]에서 겪은 것과 동일한 문제 | `backend/venv`에 핀 무시하고 최신 호환 버전으로 설치해서 로직만 검증. 정확한 버전 재조정은 팀에서 별도 논의 필요 |
| Playwright로 회원가입 버튼을 눌러도 반응 없음, URL이 `/register?`로 바뀜(빈 쿼리스트링 붙은 GET) | 프론트를 `http://127.0.0.1:PORT`로 접속함. Next.js 개발 서버는 기본적으로 `localhost` 오리진만 허용하고 그 외(`127.0.0.1` 포함)에서 온 정적 자산 요청은 `403`으로 막는다(`allowedDevOrigins` 설정으로 풀 수 있음) — JS 번들이 로드는 됐지만 실행이 막혀 리액트가 이벤트 핸들러를 못 붙였고, 그래서 폼이 브라우저 기본 GET 제출로 처리됨 | `127.0.0.1` 대신 반드시 `localhost`로 접속 |
| Host를 `localhost`로 고쳤는데도 여전히 로그인/회원가입이 아무 반응 없음(이번엔 URL에 `?`도 안 붙음) | 프론트를 포트 3123으로 띄웠는데, 백엔드 `app/main.py`의 `CORSMiddleware`가 `allow_origins=["http://localhost:3000"]`으로 고정돼 있어서 다른 포트에서 온 요청이 CORS에 막힘(브라우저 콘솔에만 조용히 에러가 남고 화면엔 아무 표시도 안 됨 — 내 코드의 `catch` 블록이 에러 문구를 보여주지만 `fetch` 자체가 CORS 프리플라이트에서 막히면 그 이전 단계라 원인 파악이 더 어려웠음) | E2E 테스트 시 프론트를 반드시 기본 포트 3000으로 띄움. 체크리스트에 이 함정을 명시해서 다음에 안 헤매게 해둠 |
| `frontend/AGENTS.md`가 "이 Next.js는 학습 데이터와 다르다"고 경고 | Next.js 16.3.3은 `PageProps<'/route'>`/`LayoutProps<'/route'>` 같은 새 타입 헬퍼를 자동 생성함(기존 `layout.tsx`가 이미 `LayoutProps<"/">`를 쓰고 있었음) | 코드 작성 전에 `node_modules/next/dist/docs/`를 실제로 읽고 확인. 새 회원가입/로그인 페이지는 라우트 파라미터가 없어 이 타입 헬퍼가 필요 없어서 기존 관례(`app/page.tsx`)와 동일하게 무타입 컴포넌트로 작성 |

## 테스트 전략

DB가 필요한 라우트를 실제 Supabase 없이 검증하기 위해 두 단계로 나눠 확인했다.

1. **자동 테스트 (pytest, 25개)**: `backend/tests/api/conftest.py`가 매 테스트마다 새 in-memory SQLite(StaticPool로 커넥션 하나 유지)를 만들고 `get_db` 의존성을 그걸로 오버라이드한다. `pgvector.Vector` 타입을 쓰는 다른 테이블들은 SQLite가 컴파일 못하므로, `Base.metadata.create_all(tables=[User.__table__, RefreshToken.__table__])`처럼 필요한 테이블만 명시해서 생성했다.
2. **실제 서버 라이브 검증**: pytest의 `TestClient`가 아니라 진짜 `uvicorn`으로 서버를 띄우고 `curl`로 회원가입→로그인→중복가입(409)→틀린 비밀번호(401)→`/me`→`/refresh`→`/logout`→로그아웃 후 refresh 재시도(401) 전체 흐름을 확인했다(체크리스트 "검증 기준" 항목 전부 여기서 통과 확인). 이건 `backend/smoke_test.db`라는 임시 SQLite 파일을 썼고, 확인 후 삭제해서 저장소에는 안 남았다.

3. **실제 브라우저 E2E (Playwright, 2026-09-02 추가)**: 별도의 브라우저 자동화 "도구" 없이도 Playwright는 그냥 npm 패키지라서 설치해서 직접 돌릴 수 있었다. `npm install -D @playwright/test` + `npx playwright install chromium`으로 헤드리스 Chromium을 받고, `frontend/e2e/auth.spec.ts`에 회원가입→로그인→(로그인 응답의 실제 `access_token` 확인)→홈 이동, 그리고 중복 이메일/오답 비밀번호 시 에러 문구 노출까지 실제 클릭으로 검증하는 테스트 3개를 작성했다. 처음 두 번은 실패했는데, 둘 다 진짜 원인이 있었다(아래 트러블슈팅 참고). 원인을 고치고 나니 3개 다 통과.
4. **실 Supabase 검증 (2026-09-02, 같은 날 이어서)**: `backend/.env`가 준비된 뒤 `alembic upgrade head`로 11개 테이블 전체 생성 확인, 위 2번의 curl 시나리오와 3번의 Playwright 스위트를 그대로 실 DB에 대고 재실행해서 전부 통과. 검증에 쓴 테스트 유저는 확인 후 DB에서 삭제.

## `.env` 작성 중 겪은 사고 — 비밀번호 부분 노출

실 DB 검증을 준비하며 `DATABASE_URL` 값이 올바른 형식인지 확인하려고 `sed`로 자격증명 부분을 가리는 명령을 짰는데, 정규식이 "첫 번째 `@` 앞까지만" 가리는 방식이었다. 그런데 당시 비밀번호에 URL 인코딩되지 않은 `@`가 들어있어서, 정규식이 그 지점에서 멈춰버렸고 **비밀번호 뒷부분 일부가 대화 로그에 그대로 노출되는 사고**가 있었다. 즉시 사용자에게 알리고 Supabase 비밀번호를 재발급받도록 안내했다. 이후로는 절대 정규식/문자열 자르기로 자격증명을 가리지 않고, `urllib.parse.urlsplit()`로 구조(스킴/호스트/포트)만 뽑아서 확인하고 자격증명이 들어있는 필드는 아예 코드 경로에 노출시키지 않는 방식으로 바꿨다. **교훈: 비밀번호 마스킹은 "그럴듯한 정규식"이 아니라 제대로 된 파서로 해야 한다 — 조금이라도 애매하면 아예 출력하지 않는 쪽을 택할 것.**

이 과정에서 `.env` 작성 시 흔한 함정 두 개도 같이 발견했다(체크리스트에도 기록):
- Supabase 대시보드가 그대로 복사해주는 연결 문자열은 `postgresql://`로 시작하는데, 비동기 드라이버가 필요해서 `postgresql+asyncpg://`로 고쳐야 한다
- Supabase "Connect" 모달의 풀러 포트 6543(Transaction 모드)은 asyncpg의 prepared statement와 호환 안 됨 — 반드시 5432(Session 모드) 사용

## 남은 작업

없음 — B-1 체크리스트 전 항목 완료. 다음은 [02_interview_state_machine_api.md](../../checklists/person_B_frontend_backend/02_interview_state_machine_api.md).
- 02(인터뷰 상태머신) 작업 시 `get_owned_session`을 실제 라우트에 연결
- Railway 배포 시 `ENVIRONMENT=production` 환경변수 추가 잊지 않기
