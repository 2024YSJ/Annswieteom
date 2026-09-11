# 공용 체크리스트 4 — 로컬 개발 환경을 프로덕션과 완전히 분리하기

배경: `main`은 Vercel(프론트)·Render(백엔드)·프로덕션 Supabase로 실제 배포되는 브랜치이고, `dev`는 이 노트북에서 직접 `uvicorn`/`next dev`로 돌리며 테스트하는 브랜치다. 예전에는 `dev`로 로컬 작업을 해도 `backend/.env`가 실제 운영 Supabase와 운영 추론 서버(Cloudflare Tunnel)를 그대로 가리키고 있어서, 로컬 테스트가 실수로 운영 데이터를 건드리거나 운영 LLM 서버 자원을 같이 쓰는 상황이 있었다. 이 문서는 그걸 막기 위해 로컬 전용 DB와 로컬 전용 LLM으로 완전히 분리한 설정을 기록한다.

## 왜 이렇게 나눴나

- **DB 분리**: 로컬에서 게스트 계정을 만들거나 마이그레이션 실험을 해도 실제 사용자 데이터에 영향이 없어야 한다.
- **LLM 분리**: 로컬 테스트가 운영 추론 서버(Cloudflare Tunnel 경유, 운영 트래픽과 같은 자원)에 부하를 주지 않아야 하고, 인터넷 연결 없이도(터널이 꺼져 있어도) 기본적인 흐름 테스트가 가능해야 한다.

## 설정 내용 (모두 `backend/.env`에만 있음 — git에 절대 안 올라감)

| 변수 | 운영(main, Render) 값 | 로컬 dev(이 노트북) 값 |
|---|---|---|
| `DATABASE_URL` | 프로덕션 Supabase 프로젝트 | **별도로 새로 만든 `annswieteom-dev` Supabase 프로젝트** |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | 프로덕션 프로젝트 값 | `annswieteom-dev` 프로젝트 값 |
| `LLM_ACCESS_CLIENT_ID` / `LLM_ACCESS_CLIENT_SECRET` | Cloudflare Access 서비스 토큰 (터널이 인증 뒤에 있다) | **비워둔다** — 로컬 Ollama는 Access 뒤에 없고, 비어 있으면 헤더를 붙이지 않는다 |
| `LOCAL_LLM_BASE_URL` | `https://llm.annswieteom.com` (Cloudflare Tunnel → DGX Spark) | `http://localhost:11434` (이 노트북에 설치된 Ollama) |
| `LOCAL_LLM_MODEL_NAME` | `qwen3.5:35b-a3b` (2026-09-11~, 이전 `qwen2.5:32b`) | `qwen2.5:3b-instruct` (이 노트북에 이미 받아둔 작은 모델) |
| `LOCAL_LLM_DISABLE_THINKING` | `true` | 비워 둔다(기본 false) — 로컬 qwen2.5에는 필요 없다 |

## 새 dev용 Supabase 프로젝트를 처음 만들 때 순서

1. [supabase.com/dashboard](https://supabase.com/dashboard) → New Project → 이름 예: `annswieteom-dev`
2. SQL Editor에서 pgvector 확장 활성화: `create extension if not exists vector;`
3. Storage → New bucket → 이름 `records`, **Private**
4. Project Settings → Database → Connection string (URI) 복사 → `backend/.env`의 `DATABASE_URL`에 붙여넣되, 맨 앞을 `postgresql://`가 아니라 **`postgresql+asyncpg://`**로 바꿔야 한다 (SQLAlchemy 비동기 드라이버 표기 — 이 프로젝트 코드가 요구하는 형식)
5. Project Settings → API에서 `Project URL`(`SUPABASE_URL`), `service_role` 키(`SUPABASE_SERVICE_KEY`) 복사해 `.env`에 반영
6. `cd backend && alembic upgrade head`로 스키마 적용 (로컬 전용 DB이므로 별도 승인 없이 바로 실행해도 안전 — 운영 Supabase에 적용할 때만 승인 필요)

## 로컬 Ollama 모델 확인/실행

```bash
ollama serve                      # 이미 실행 중이면 생략
ollama list                       # qwen2.5:3b-instruct 등 설치 확인
```

## ⚠️ 다음 세션(Claude Code 포함)이 반드시 지켜야 할 것

- **`backend/.env`는 `.gitignore`에 있어서 커밋 자체가 불가능하다** — 이 분리는 git 레벨에서 이미 안전하다. 하지만 아래는 사람(또는 AI 세션)이 실수로 깨뜨릴 수 있는 부분이라 명시한다.
- **`backend/.env.example`이나 `backend/app/core/config.py`의 기본값을 이 로컬 dev 값(로컬 Ollama, dev Supabase)으로 "동기화"하지 않는다.** 그 두 파일은 git에 커밋되는 공유 설정이라, 여기를 로컬 값으로 바꾸면 실제로는 운영(main)에 영향을 준다 — `.env.example`은 항상 "누구나 처음 설정할 때 채워야 하는 placeholder" 상태를 유지해야 한다.
- **로컬 dev DB(`annswieteom-dev`)의 스키마/데이터 상태를 운영 DB의 상태라고 착각하지 않는다.** 마이그레이션을 로컬에 적용했다고 운영에도 적용된 게 아니다 — 운영 Supabase에 실제로 적용할 때는 지금까지처럼 실행 직전에 명시적 승인을 받는다.
- **로컬 3b 모델(`qwen2.5:3b-instruct`)은 "연결이 되는지, 흐름이 도는지"를 확인하는 용도지, 실제 답변 품질을 판단하는 용도가 아니다.** 실제로 확인해보니 카테고리 추출 같은 구조화된 JSON 출력 작업에서 빈 배열을 반환하는 등, 운영에서 쓰는 큰 모델보다 품질이 눈에 띄게 떨어진다. 프롬프트나 LLM 응답 품질을 판단해야 하는 작업이라면, 이 노트북의 `.env`를 일시적으로 실제 터널 주소(`https://llm.annswieteom.com`)와 운영 모델 이름으로 바꾸고 **Access 서비스 토큰 두 개도 함께 채운 뒤**(터널이 인증 뒤에 있어서 토큰 없이는 403이다) 확인하고, 끝나면 다시 로컬 값으로 되돌린다(토큰도 다시 비운다). (2026-09-09 Gemini 폴백을 제거해서 대안은 실제 터널뿐이다.)
- **이 문서와 `.env`의 실제 값이 다르면 이 문서가 아니라 `.env`를 신뢰한다** — 설정이 또 바뀌었을 수 있으니, 확신이 필요하면 `.env`를 직접 열어 확인한다(비밀번호 등 민감한 값은 화면에 그대로 출력하지 말고 구조적으로만 확인할 것).
