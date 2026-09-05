# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**안 쉬었음 (Annswieteom)** — a web app that helps users turn career gap periods into STAR-structured narrative documents. Users describe their gap year activities through a multi-turn interview, and the system generates cited career narratives backed by their personal records (blog posts, certificates, etc.).

**Critical design principle — Honesty Guardrail ("정직성 가드레일")**: Generated documents may only cite facts the user explicitly confirmed. This is enforced at the data model level via the `confirmed_facts` table. Every generated sentence must reference at least one row in `confirmed_facts` via `evidence_fact_ids`. Never bypass this constraint in code or prompts.

Full implementation spec: [docs/specs/annswieoteum_detailed_spec.md](docs/specs/annswieoteum_detailed_spec.md)  
Milestone roadmap: [docs/checklists/milestones_overview.md](docs/checklists/milestones_overview.md)

## Architecture

Hybrid cloud + local GPU setup:

- **Frontend**: Next.js 14+ (TypeScript) → deployed on Vercel (`frontend/`)
- **Backend**: FastAPI (Python 3.11+) → deployed on Railway (`backend/`)
- **Database**: PostgreSQL + pgvector on Supabase
- **Local LLM**: Ollama on RTX 4090 PC, exposed via Cloudflare Tunnel (primary inference)
- **LLM Fallback**: Google Gemini API (auto-activated when local server is unreachable)
- **Object Storage**: Supabase Storage (images, documents)

The backend selects the LLM provider based on `LLM_PROVIDER_ORDER` env var (e.g., `"local,gemini"`). No manual switching needed.

## Commands

### Backend (FastAPI)

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows PowerShell
pip install -r requirements.txt

# Database migrations (Alembic)
alembic upgrade head
alembic revision --autogenerate -m "description"

# Run dev server
uvicorn app.main:app --reload --port 8000

# Run tests
pytest
pytest tests/path/to/test_file.py::test_name   # single test
```

### Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev       # dev server on port 3000
npm run build
npm run lint
```

### Local LLM (Ollama — Person A's machine)

```bash
ollama serve
ollama pull exaone3.5:7.8b    # or qwen2.5:14b
# Expose via Cloudflare Tunnel (see docs/checklists/person_A_infra_ai/)
cloudflared tunnel run annswieteom
```

## Key Database Tables

| Table | Purpose |
|-------|---------|
| `users` | Accounts with bcrypt password hash |
| `sessions` | Interview state machine (8 states) |
| `activity_categories` | Gap period activity types per session |
| **`confirmed_facts`** | **Core honesty guardrail** — only user-confirmed facts |
| `records` | User-submitted blog URLs, images, pasted text |
| `record_chunks` | Parsed text segments with `VECTOR(1024)` embeddings |
| `generated_documents` | Final output with tone/version metadata |
| `generated_sentences` | Individual sentences with `evidence_fact_ids[]` |
| `refresh_tokens` | SHA-256 hashed refresh tokens |

`confirmed_facts.source_type` must be one of: `user_confirmed`, `user_edited`, `record_cited`. Never insert with a synthetic or AI-generated source type.

## API Structure

All routes under `/api/v1`:
- `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me`
- `POST /sessions`, `POST /sessions/{id}/period`, `POST /sessions/{id}/categories`
- `GET /sessions/{id}/interview/next` → returns AI draft + context
- `POST /sessions/{id}/interview/confirm` → saves to `confirmed_facts`
- `POST /sessions/{id}/records` → async blog/image parsing (poll for status)
- `POST /sessions/{id}/generate` → triggers STAR document generation
- `GET /sessions/{id}/document`, `PATCH /sessions/{id}/document/sentences/{id}`

JWT: Access tokens expire in 30 minutes; refresh tokens in 14 days.

## Environment Variables

```
DATABASE_URL              # Supabase PostgreSQL connection string
LOCAL_LLM_BASE_URL        # Cloudflare Tunnel URL to Ollama
LOCAL_LLM_MODEL_NAME      # e.g., exaone3.5:7.8b
GEMINI_API_KEY
JWT_SECRET                # 256-bit hex string
LLM_PROVIDER_ORDER        # e.g., local,gemini
```

## ⚠️ Local Dev Environment Is Intentionally Isolated From Production

`backend/.env` on this laptop points at a **separate `annswieteom-dev` Supabase project** and a **local Ollama instance (`http://localhost:11434`, model `qwen2.5:3b-instruct`)** instead of the production Supabase project and the RTX 4090 tunnel (`https://llm.annswieteom.com`, `qwen2.5:14b`). This is deliberate — full rationale and setup steps are in [docs/checklists/00_shared/04_local_dev_environment.md](docs/checklists/00_shared/04_local_dev_environment.md).

`backend/.env` is gitignored, so this never reaches `main` through git. The one thing to actively avoid: **never "sync" these local-only values into `backend/.env.example` or the defaults in `backend/app/core/config.py`** — those files are committed and shared, and changing them to match this laptop's local setup would affect production. If `.env`'s local LLM/DB values ever look wrong for a task (e.g. you need to judge real LLM output quality, not just check that a request flow works), that's expected — the small local model is deliberately weaker than production's; point `.env` at the real tunnel/Gemini temporarily and switch back after.

## Windows-Specific Notes

- No Docker or WSL2 required for development
- PowerShell is the primary shell
- Windows Firewall will prompt when Ollama or cloudflared first bind ports — allow both
- Disable "suspend on lid close" on laptops during demo week (Sept 16–20, 2026)

## Role Split

- **Person A** (infra/AI): Ollama setup, Cloudflare Tunnel, embedding pipeline, vector search — see [docs/checklists/person_A_infra_ai/](docs/checklists/person_A_infra_ai/)
- **Person B** (frontend/backend): Auth, interview state machine, document generation, frontend — see [docs/checklists/person_B_frontend_backend/](docs/checklists/person_B_frontend_backend/)

Shared tasks (Supabase setup, DB schema, deployment config): [docs/checklists/00_shared/](docs/checklists/00_shared/)

## Git Workflow

- `main` — production; merged from `dev` at each milestone completion
- `dev` — staging; default working branch
- `feature/*` — individual feature work; PR into `dev`
- Commit prefixes: `feat:`, `fix:`, `chore:`, `docs:`

## Devlog

작업이 끝날 때마다 `docs/devlog/` 아래에 기록을 남긴다. 체크리스트 파일과 1:1로 대응하는 파일명을 사용한다.

```
docs/devlog/
├── PersonA/
│   ├── 00_shared_scaffolding.md
│   ├── 00_shared_db_schema.md
│   ├── 01_local_llm_setup.md
│   ├── 02_llm_adapter_layer.md
│   └── ...
└── PersonB/
    └── ...
```

각 devlog 파일에 포함할 내용:
- 완료/미완 체크리스트 항목
- 핵심 결정 사항과 이유 (왜 이 방식을 선택했는가)
- 트러블슈팅 (문제 → 원인 → 해결)
- 관련 커밋 해시
- 남은 작업
