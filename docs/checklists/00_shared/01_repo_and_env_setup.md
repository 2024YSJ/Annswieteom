# 공용 체크리스트 1 — 리포지토리 & 개발 환경 셋업

근거: 명세서 4절(개발 환경), 5절(리포지토리 구조)
담당: 공용 (둘 중 아무나 시작, 완료 후 A/B 모두 확인)
선행 조건: 없음 — 이 프로젝트의 첫 작업

## 1. 공통 로컬 개발 환경 (A, B 각자 자기 PC에)

- [x] Git 설치 및 `git --version` 확인 (4-1)
- [x] Python 3.11+ 설치, 설치 시 "Add python.exe to PATH" 체크, `python --version` 확인 (4-2)
- [x] Node.js LTS 설치, `node --version` / `npm --version` 확인 (4-3)
- [x] VS Code 등 에디터 준비 (4-4)
- [x] GitHub 저장소 생성 및 A·B 모두 협업자로 등록 (4-5)

## 2. 공용 클라우드 계정 발급 (둘 중 아무나 진행, 값은 공유)

- [x] Supabase 가입, 새 프로젝트 생성, DB 비밀번호를 안전한 곳(예: 팀 비밀번호 관리 도구)에 기록 (4-8)
- [x] Supabase "Project Settings → Database"에서 `DATABASE_URL` 연결 문자열 확인
- [x] Supabase SQL Editor에서 pgvector 확장 활성화:
  ```sql
  create extension if not exists vector;
  ```
- [ ] Google AI Studio에서 Gemini API 키 발급 (4-9) — 로컬 LLM 준비 전 개발용 겸 이후 폴백용 — `GEMINI_API_KEY`가 아직 로컬 `.env`에 비어 있음
- [ ] Supabase Storage에 이미지 기록물 업로드용 버킷 하나를 **비공개(private)**로 생성 (2절 아키텍처의 "오브젝트 스토리지", `records.storage_path`가 가리킬 위치 — 사용자별 접근 격리는 [person_B_frontend_backend/03_records_feature.md](../person_B_frontend_backend/03_records_feature.md) 1-1절 참고) — 아직 안 함, 코드는 준비돼 있음(`app/services/storage.py`)
- [ ] 위에서 얻은 `DATABASE_URL`, `GEMINI_API_KEY`, Supabase Storage 접근 키를 A·B 둘 다 접근 가능한 안전한 채널(예: 팀 전용 비밀 채널)로 공유 — **절대 GitHub 공개 저장소에 커밋하지 않는다**

## 3. 모노레포 폴더 스캐폴딩 (5절 구조 그대로)

- [x] 아래 골격 생성:
  ```
  annswieoteum/
  ├── frontend/            (Next.js + TypeScript)
  ├── backend/             (FastAPI)
  │   └── app/
  │       ├── api/
  │       ├── core/
  │       ├── models/
  │       ├── schemas/
  │       ├── services/
  │       │   ├── llm/
  │       │   ├── embedding/
  │       │   └── record_pipeline/
  │       ├── prompts/
  │       └── db/
  │           └── migrations/
  ├── .gitignore
  └── README.md
  ```
- [x] `frontend/`: `npx create-next-app@latest` (TypeScript, App Router 옵션 선택)
- [x] `backend/`: `requirements.txt` 초안 작성 (fastapi, uvicorn, sqlalchemy, alembic, psycopg2 또는 asyncpg, pydantic, passlib[bcrypt], python-jose[cryptography] 또는 PyJWT, httpx) — 이후 [person_A_infra_ai/04_record_pipeline.md](../person_A_infra_ai/04_record_pipeline.md) 작업 시 HTML 파싱(`beautifulsoup4`, `requests`)과 Gemini SDK(`google-generativeai`) 등이 추가로 필요해지면 그때 추가
- [x] `backend/app/main.py`에 FastAPI 앱 생성 + `CORSMiddleware` 등록, `allow_origins`에 `http://localhost:3000` 추가, **`allow_credentials=True`도 함께 설정**(refresh token 쿠키를 쓰려면 필수 — [person_B_frontend_backend/01_auth.md](../person_B_frontend_backend/01_auth.md) 참고) (17절 트러블슈팅 — 프론트-백엔드 로컬 연동을 실제로 시작하기 전에 미리 해둬야 나중에 헤매지 않는다)
- [x] `backend/app/db/session.py`에 SQLAlchemy 엔진/세션 팩토리 작성 (`DATABASE_URL` 사용)
- [x] `backend/tests/` 빈 폴더만 우선 생성 (5절 구조에 포함 — 이번 3주 범위에서 테스트 작성은 필수는 아니지만 폴더 위치는 맞춰둔다) → 실제로는 69개 테스트까지 채워짐
- [x] `.gitignore`에 `.env`, `node_modules/`, `__pycache__/`, `.venv/` 등 추가
- [x] `backend/.env.example` 생성 (10-4절 환경변수 목록 전체: `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL_NAME`, `GEMINI_API_KEY`, `LLM_PROVIDER_ORDER`, `DATABASE_URL`, `JWT_SECRET`). ⚠️ 10-4절 표에는 없지만 이미지 업로드([person_B_frontend_backend/03_records_feature.md](../person_B_frontend_backend/03_records_feature.md))에 Supabase Storage 접속 정보(`SUPABASE_URL`, `SUPABASE_SERVICE_KEY` 등, Supabase 클라이언트 라이브러리 문서의 정확한 변수명 확인)가 추가로 필요하다 — 여기에 함께 추가
- [x] `frontend/.env.local.example` 생성 (`NEXT_PUBLIC_API_BASE_URL` — [person_B_frontend_backend/05_frontend_routes_components.md](../person_B_frontend_backend/05_frontend_routes_components.md)의 `lib/api-client.ts`가 백엔드 주소를 찾을 때 사용, 로컬 개발 시 `http://localhost:8000`)
- [x] 루트 `README.md`에 프로젝트 한 줄 소개 + 로컬 실행 방법 작성

## 4. Git 협업 규칙 및 브랜치 전략 (5절 확장 — 이 저장소의 실제 구조 기준)

현재 저장소에는 이미 `main`과 `dev` 두 브랜치가 있고, GitHub 기본 브랜치는 `dev`로 설정돼 있다(`origin/HEAD -> origin/dev`). 이 구조를 그대로 살려서 "항상 배포 가능한 `main`"과 "매일 작업이 합쳐지는 `dev`"를 분리한다 — 명세서 5절의 "PR로 main에 머지"를 이 저장소에 맞게 한 단계(`dev`)를 끼워 넣은 버전이라고 보면 된다.

```
main   ●───────────────●───────────●───────────●───── 배포 브랜치 (Railway/Vercel이 추적)
        \  (마일스톤 체크포인트에서만 dev → main 병합)
dev      ●─●─●─●─●─●─●─●─●─●─●─●─●─●─●─●─●─●─●─●───── 통합 브랜치 (기본 브랜치, PR 대상)
          \       \           \         \
           feature/auth  feature/llm-adapter  feature/records-feature ...  (실제 작업은 여기서)
```

- [x] **`main`**: 배포 브랜치. Railway(백엔드)·Vercel(프론트엔드)이 이 브랜치를 추적해 배포하도록 설정한다([00_shared/03_deployment.md](03_deployment.md)). 평소에는 여기에 직접 커밋하거나 `feature/*`를 바로 병합하지 않는다. — 마일스톤 4에서 [PR #4](https://github.com/2024YSJ/Annswieteom/pull/4)로 처음 `dev → main` 승격 완료(2026-09-03)
- [x] **`dev`**: 기본 통합 브랜치. 모든 `feature/*` 브랜치는 여기서 분기하고, 작업이 끝나면 PR로 여기 병합한다. `dev`는 항상 "로컬에서 실행은 되는" 상태를 유지하되(빌드가 깨진 채로 오래 두지 않기), `main`만큼 엄격하게 배포 가능할 필요는 없다.
- [x] **`feature/<이름>`**: 아래 표대로 체크리스트 파일 하나(또는 그 하위 작업)당 브랜치 하나. `dev`에서 분기 → 작업 → PR → `dev` 병합 → 브랜치 삭제.
- [x] **`dev` → `main` 승격 시점**: 각 마일스톤([milestones_overview.md](../milestones_overview.md))의 "검증 기준"을 실제로 통과했을 때, A·B가 함께 확인한 뒤 `dev → main` PR을 만들어 병합한다. 즉 커밋마다 배포되는 게 아니라 "마일스톤 단위 배포"다. 마일스톤 5(배포) 직전에는 이 승격이 필수다.
- [x] 폴더 분담(5절)과 브랜치 분담을 일치시켜 충돌을 줄인다:
  - A: `backend/app/services/llm`, `backend/app/services/embedding`, `backend/app/services/record_pipeline`
  - B: `frontend/` 전체, `backend/app/api`, `backend/app/services/interview_orchestrator`, `backend/app/services/document_generator`
- [x] 커밋 메시지 접두어 합의: `feat:`, `fix:`, `chore:`

### 체크리스트 ↔ 브랜치 매핑표

각 체크리스트 파일 상단에도 "브랜치:" 항목으로 아래와 동일한 이름을 표시해뒀다 — 해당 파일을 열면 바로 어떤 브랜치에서 작업할지 알 수 있다.

| 담당 | 체크리스트 | 브랜치 | 비고 |
|---|---|---|---|
| 공용 | [00_shared/01_repo_and_env_setup.md](01_repo_and_env_setup.md) (이 문서) | 브랜치 없이 `dev`에 직접 | 아직 나뉠 코드가 없는 최초 스캐폴딩 |
| 공용 | [00_shared/02_database_schema.md](02_database_schema.md) | `feature/db-schema` | A·B 모두의 후속 작업 전제 조건 — 가장 먼저 `dev`에 병합 |
| A | [person_A_infra_ai/01_local_llm_setup.md](../person_A_infra_ai/01_local_llm_setup.md) | 브랜치 없음 | 로컬 설치·모델 다운로드일 뿐 저장소에 반영될 코드 없음 |
| A | [person_A_infra_ai/02_llm_adapter_layer.md](../person_A_infra_ai/02_llm_adapter_layer.md) | `feature/llm-adapter` | |
| A | [person_A_infra_ai/03_embedding_pipeline.md](../person_A_infra_ai/03_embedding_pipeline.md) | `feature/embedding-pipeline` | |
| A | [person_A_infra_ai/04_record_pipeline.md](../person_A_infra_ai/04_record_pipeline.md) | `feature/record-pipeline` | |
| A | [person_A_infra_ai/05_cloudflare_tunnel.md](../person_A_infra_ai/05_cloudflare_tunnel.md) | 브랜치 없음(또는 `chore/cloudflare-tunnel`) | 코드 변경은 거의 없고 `.env` 값 교체 위주 |
| A | [person_A_infra_ai/06_consistency_check.md](../person_A_infra_ai/06_consistency_check.md) | `feature/consistency-check` | |
| A | [person_A_infra_ai/07_server_ops_checklist.md](../person_A_infra_ai/07_server_ops_checklist.md) | 브랜치 없음 | 운영 점검 체크리스트, 코드 변경 아님 |
| B | [person_B_frontend_backend/01_auth.md](../person_B_frontend_backend/01_auth.md) | `feature/auth` | |
| B | [person_B_frontend_backend/02_interview_state_machine_api.md](../person_B_frontend_backend/02_interview_state_machine_api.md) | `feature/interview-flow` | |
| B | [person_B_frontend_backend/03_records_feature.md](../person_B_frontend_backend/03_records_feature.md) | `feature/records-feature` | |
| B | [person_B_frontend_backend/04_document_generation.md](../person_B_frontend_backend/04_document_generation.md) | `feature/document-generation` | |
| B | [person_B_frontend_backend/05_frontend_routes_components.md](../person_B_frontend_backend/05_frontend_routes_components.md) | `feature/frontend-shell` | 공통 라우팅·레이아웃·API 클라이언트 골격만 여기서. 기능별 화면(로그인 폼, 기록물 업로드, 결과 화면 등)은 위 해당 기능 브랜치에서 함께 작업 |
| 공용 | [00_shared/03_deployment.md](03_deployment.md) | `chore/deploy-setup` + 마일스톤별 `dev → main` 승격 PR | |

## 검증 기준

- [x] `frontend/`에서 `npm run dev` 실행 시 기본 Next.js 페이지가 `localhost:3000`에서 뜬다
- [x] `backend/`에서 가상환경 생성 후 `pip install -r requirements.txt`, `uvicorn app.main:app --reload` (main.py는 최소 "hello world" 라우트만 있어도 됨) 실행 시 `localhost:8000/docs`에 Swagger UI가 뜬다
- [x] A, B 모두 저장소를 각자 PC에 clone하고 위 두 가지를 각자 실행해볼 수 있다
