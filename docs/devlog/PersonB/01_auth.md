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
- 실 Supabase DB로의 최종 확인 — `backend/.env`가 아직 없어서 지금은 임시 SQLite로만 검증함
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
| `frontend/AGENTS.md`가 "이 Next.js는 학습 데이터와 다르다"고 경고 | Next.js 16.3.3은 `PageProps<'/route'>`/`LayoutProps<'/route'>` 같은 새 타입 헬퍼를 자동 생성함(기존 `layout.tsx`가 이미 `LayoutProps<"/">`를 쓰고 있었음) | 코드 작성 전에 `node_modules/next/dist/docs/`를 실제로 읽고 확인. 새 회원가입/로그인 페이지는 라우트 파라미터가 없어 이 타입 헬퍼가 필요 없어서 기존 관례(`app/page.tsx`)와 동일하게 무타입 컴포넌트로 작성 |

## 테스트 전략

DB가 필요한 라우트를 실제 Supabase 없이 검증하기 위해 두 단계로 나눠 확인했다.

1. **자동 테스트 (pytest, 25개)**: `backend/tests/api/conftest.py`가 매 테스트마다 새 in-memory SQLite(StaticPool로 커넥션 하나 유지)를 만들고 `get_db` 의존성을 그걸로 오버라이드한다. `pgvector.Vector` 타입을 쓰는 다른 테이블들은 SQLite가 컴파일 못하므로, `Base.metadata.create_all(tables=[User.__table__, RefreshToken.__table__])`처럼 필요한 테이블만 명시해서 생성했다.
2. **실제 서버 라이브 검증**: pytest의 `TestClient`가 아니라 진짜 `uvicorn`으로 서버를 띄우고 `curl`로 회원가입→로그인→중복가입(409)→틀린 비밀번호(401)→`/me`→`/refresh`→`/logout`→로그아웃 후 refresh 재시도(401) 전체 흐름을 확인했다(체크리스트 "검증 기준" 항목 전부 여기서 통과 확인). 이건 `backend/smoke_test.db`라는 임시 SQLite 파일을 썼고, 확인 후 삭제해서 저장소에는 안 남았다.

프론트는 `next build`/`next lint` 통과, `next dev`로 두 페이지가 실제로 폼을 렌더링하는 것까지 확인했다. 다만 브라우저에서 실제로 버튼을 눌러 백엔드까지 왕복시키는 클릭 테스트는 이 세션에 브라우저 자동화 도구가 없어 수행하지 못했다 — 사람이 한 번 `npm run dev` + 백엔드 로컬 실행해서 눈으로 확인하는 걸 권장.

## 남은 작업

- Supabase `DATABASE_URL`이 팀 채널로 공유되면 `backend/.env` 생성 → `alembic upgrade head` → 실제 DB로 위 시나리오 재확인
- 사람이 브라우저에서 직접 회원가입→로그인 클릭 테스트
- 02(인터뷰 상태머신) 작업 시 `get_owned_session`을 실제 라우트에 연결
- Railway 배포 시 `ENVIRONMENT=production` 환경변수 추가 잊지 않기
