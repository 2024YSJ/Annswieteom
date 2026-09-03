# 공용 — 모노레포 스캐폴딩 devlog

체크리스트: `docs/checklists/00_shared/01_repo_and_env_setup.md`
날짜: 2026-09-01
커밋: `650a7c1`

---

## 폴더 구조 생성

명세서 5절의 디렉터리 레이아웃을 그대로 따랐다. `backend/app/` 아래는 `api/`, `core/`, `models/`, `schemas/`, `services/llm|embedding|record_pipeline/`, `prompts/`, `db/` 로 나뉘고, 각 디렉터리에 `__init__.py`를 배치해 Python 패키지로 인식시켰다.

프론트엔드는 `npx create-next-app@latest frontend --typescript --eslint --app --no-tailwind --no-src-dir --use-npm` 으로 생성했다. `--app` 플래그가 Next.js 14의 App Router를 활성화하고, `--no-src-dir`로 `app/` 디렉터리가 루트에 바로 위치하게 했다.

## 백엔드 핵심 파일

**`app/core/config.py`**: `pydantic-settings`의 `BaseSettings`를 상속해 환경변수를 타입 안전하게 로딩한다. `class Config: env_file = ".env"`를 선언해 `.env` 파일을 자동으로 읽는다. 이렇게 하면 FastAPI 앱 어디서든 `from app.core.config import settings`로 설정값에 접근할 수 있다.

**`app/db/session.py`**: SQLAlchemy의 `create_async_engine`과 `async_sessionmaker`로 비동기 DB 연결 풀을 구성했다. `get_db()`는 async generator로, FastAPI의 `Depends(get_db)` 의존성 주입 패턴에서 사용한다. `Base = DeclarativeBase()`는 모든 ORM 모델의 공통 부모 클래스다.

**`app/main.py`**: `CORSMiddleware`에 `allow_credentials=True`를 명시했다. Refresh token을 HttpOnly 쿠키로 주고받으려면 credentials 포함 요청을 허용해야 하는데, 이 설정 없이는 프론트엔드에서 쿠키가 전달되지 않는다 (명세서 17절 트러블슈팅 선제 적용).

## `.env.example` 구성

10-4절의 LLM 관련 변수에 더해, 명세서 3절 아키텍처에서 언급된 Supabase Storage 접근 변수(`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`)를 추가했다. 이 변수들은 10-4절 표에는 없지만 이미지 업로드 기능([`03_records_feature.md`](../../checklists/person_B_frontend_backend/03_records_feature.md))에서 B가 필요로 한다.

## 특이사항

`frontend/.gitignore`에 `.env*` 패턴이 있어서 `.env.local.example`이 자동으로 ignore 대상이 됐다. example 파일은 커밋에 포함돼야 하므로 `git add -f`로 강제 추가했다.
