# 공용 — 모노레포 스캐폴딩 devlog

체크리스트: `docs/checklists/00_shared/01_repo_and_env_setup.md`
브랜치: `dev` (직접 커밋)
날짜: 2026-09-01
상태: 완료

## 완료 항목

- [x] `.gitignore` 생성 (`.env`, `node_modules/`, `__pycache__/`, `.venv/`, `.next/` 등)
- [x] 루트 `README.md` (로컬 실행 방법 포함)
- [x] `backend/` 폴더 구조 생성 (5절 구조 그대로)
  - `app/api/`, `app/core/`, `app/models/`, `app/schemas/`, `app/services/llm|embedding|record_pipeline/`, `app/prompts/`, `app/db/`, `tests/`
- [x] `backend/app/main.py` — FastAPI 앱 + CORSMiddleware (`allow_credentials=True` 포함)
- [x] `backend/app/core/config.py` — pydantic-settings 기반 환경변수 로딩
- [x] `backend/app/db/session.py` — SQLAlchemy async 엔진 + 세션 팩토리
- [x] `backend/requirements.txt` 초안
- [x] `backend/.env.example` (10-4절 변수 전체 + Supabase Storage 변수 추가)
- [x] `frontend/` — `npx create-next-app@latest` (TypeScript, App Router, ESLint)
- [x] `frontend/.env.local.example` (`NEXT_PUBLIC_API_BASE_URL`)

## 특이사항

- `frontend/.gitignore`에 `.env*` 패턴이 있어 `.env.local.example`을 `git add -f`로 강제 추가
- Windows PowerShell 환경, Docker/WSL2 없이 모두 정상 동작

## 커밋

- `650a7c1` chore: scaffold monorepo structure (backend + frontend)
