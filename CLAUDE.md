# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**안 쉬었음 (Annswieteom)** — a web app that helps users turn career gap periods into STAR-structured narrative documents. Users describe their gap year activities through a multi-turn interview, and the system generates cited career narratives backed by their personal records (blog posts, certificates, etc.).

**Critical design principle — Honesty Guardrail ("정직성 가드레일")**: Generated documents may only cite facts the user explicitly confirmed. This is enforced at the data model level via the `confirmed_facts` table. Every generated sentence must reference at least one row in `confirmed_facts` via `evidence_fact_ids`. Never bypass this constraint in code or prompts.

Full implementation spec: [docs/specs/annswieteom_detailed_spec.md](docs/specs/annswieteom_detailed_spec.md)  
Milestone roadmap: [docs/checklists/milestones_overview.md](docs/checklists/milestones_overview.md)

## Architecture

Hybrid cloud + local GPU setup:

- **Frontend**: Next.js 14+ (TypeScript) → deployed on Vercel (`frontend/`)
- **Backend**: FastAPI (Python 3.11+) → deployed on Render (`backend/`)
- **Database**: PostgreSQL + pgvector on Supabase
- **Local LLM**: Ollama on an NVIDIA DGX Spark (GB10 Grace Blackwell, ARM64/aarch64, DGX OS), exposed via Cloudflare Tunnel behind a Cloudflare Access service token (only inference path)
- **Object Storage**: Supabase Storage (images, documents)

Inference and embeddings both run on the local Ollama server only. **There is no fallback provider** — Gemini was removed on 2026-09-09. If the local server is unreachable, every AI path returns `503 llm_unavailable` and the UI shows "AI 서버가 수리 중이예요." Image OCR went away with it (it was Gemini Vision and had no local substitute), so record uploads now accept documents only.

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

### Local LLM (Ollama — DGX Spark inference host, Linux/aarch64)

```bash
# Ollama is already installed on the Spark. Identify HOW before changing anything --
# an NVIDIA forum post says snap, but this machine was not a snap install:
#   systemctl list-unit-files | grep -i ollama ; snap list ollama 2>/dev/null
# Do NOT reinstall via install.sh; that can lose the GB10 (SM121) CUDA setup.
# If localhost:11434 already answers, leave the binding alone -- cloudflared connects
# from the same host, so a 127.0.0.1 bind is fine. OLLAMA_HOST=0.0.0.0 is a
# troubleshooting step, not a setup step.

ollama pull qwen2.5:32b    # inference (LOCAL_LLM_MODEL_NAME)
ollama pull bge-m3         # embeddings — REQUIRED, and not configurable:
                           # the name is hardcoded in services/embedding/local_ollama_embedding.py
                           # and its 1024-dim output is the VECTOR(1024) column type.
                           # Forget it and record/feed embedding fails silently.

# Expose via Cloudflare Tunnel (see docs/checklists/person_A_infra_ai/08_dgx_spark_migration.md)
sudo systemctl status cloudflared              # systemd, not a Windows service
journalctl -u cloudflared -n 50 --no-pager     # "active" alone is not evidence the tunnel is up
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
| `user_attributes` | Person-level profile (age, region, education, desired job…) extracted from conversation; `inferred`/`confirmed`/`user_edited`/`rejected`. Feeds recommendations and interview follow-ups **only** — never document generation |
| `user_consents` | `sensitive_profiling` consent; sensitive attributes (income, special groups, marital) are stored only while granted |

`confirmed_facts.source_type` must be one of: `user_confirmed`, `user_edited`, `record_cited`. Never insert with a synthetic or AI-generated source type.

`user_attributes` values must never reach `generate_document` or the `draft_answer` prompt — an inferred attribute in an AI draft becomes a confirmed fact the moment the user clicks confirm. Spec: [docs/specs/profiling_and_matching.md](docs/specs/profiling_and_matching.md).

## API Structure

All routes under `/api/v1`:
- `GET /health/llm` — operator probe: is the inference server reachable from *this*
  backend? Always 200; status is in the body. Distinct from `GET /health` (outside
  `/api/v1`), which is Render's liveness probe and must stay dependency-free.
- `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me`
- `POST /sessions`, `POST /sessions/{id}/period`, `POST /sessions/{id}/categories`
- `POST /sessions/{id}/interview/ask` → current question (or the pending category review)
- `POST /sessions/{id}/interview/answer` → stores the answer's extracted facts as category **drafts** (`activity_categories.draft_turns`), returns the next question or the category review
- `POST /sessions/{id}/interview/review` → the only path that saves interview facts to `confirmed_facts` (once per category, after the user edits/excludes/adds)
- `POST /sessions/{id}/interview/confirm` → only the "여러 활동 있나요?" split check (routing, not facts)
- `POST /sessions/{id}/records` → async blog/image parsing (poll for status)
- `POST /sessions/{id}/generate` → triggers STAR document generation
- `GET /sessions/{id}/document`, `PATCH /sessions/{id}/document/sentences/{id}`

JWT: Access tokens expire in 30 minutes; refresh tokens in 14 days.

## Environment Variables

```
DATABASE_URL              # Supabase PostgreSQL connection string
LOCAL_LLM_BASE_URL        # Cloudflare Tunnel URL to Ollama
LOCAL_LLM_MODEL_NAME      # e.g., qwen2.5:32b (the embedding model is NOT an env var)
LLM_ACCESS_CLIENT_ID      # Cloudflare Access service token; empty = send no auth headers
LLM_ACCESS_CLIENT_SECRET  # never paste this into a chat log or a commit
JWT_SECRET                # 256-bit hex string
```

## ⚠️ Local Dev Environment Is Intentionally Isolated From Production

`backend/.env` on this laptop points at a **separate `annswieteom-dev` Supabase project** and a **local Ollama instance (`http://localhost:11434`, model `qwen2.5:3b-instruct`)** instead of the production Supabase project and the DGX Spark tunnel (`https://llm.annswieteom.com`, `qwen2.5:32b`). This is deliberate — full rationale and setup steps are in [docs/checklists/00_shared/04_local_dev_environment.md](docs/checklists/00_shared/04_local_dev_environment.md).

`backend/.env` is gitignored, so this never reaches `main` through git. The one thing to actively avoid: **never "sync" these local-only values into `backend/.env.example` or the defaults in `backend/app/core/config.py`** — those files are committed and shared, and changing them to match this laptop's local setup would affect production. If `.env`'s local LLM/DB values ever look wrong for a task (e.g. you need to judge real LLM output quality, not just check that a request flow works), that's expected — the small local model is deliberately weaker than production's; point `.env` at the real tunnel temporarily and switch back after.

## Platform Notes

The dev machines and the inference host run different operating systems — do not apply one's
instructions to the other.

**Dev machines (this laptop, both Person A and B):** Windows

- No Docker or WSL2 required for development
- PowerShell is the primary shell
- Windows Firewall will prompt when a local Ollama or cloudflared first binds a port — allow both
- Disable "suspend on lid close" on laptops during demo week (Sept 16–20, 2026)

**Inference host (DGX Spark):** DGX OS, Linux, ARM64 (aarch64)

- Service management is `systemctl`/`journalctl`, not the Services console or Event Log
- How Ollama is installed varies -- check before configuring it. Under systemd use `systemctl edit ollama` + `Environment="OLLAMA_HOST=..."`; under snap that has no unit to edit and `snap set ollama host=...` is the only path
- cloudflared needs the `linux-arm64` build; x86 binaries will not run
- Suspend/hibernate must be masked, not just disabled in a power profile

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
