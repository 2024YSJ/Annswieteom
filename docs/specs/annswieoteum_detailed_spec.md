# "안 쉬었음" — Claude Code 구현 명세서 (최종본)

작성일: 2026-08-30
기반 문서: `annswieoteum_implementation_plan.md` (최종본)
대상 독자: 이 문서를 읽고 실제 코드를 작성할 **Claude Code(AI 코딩 에이전트)**, 그리고 이를 함께 사용할 **컴퓨터공학과 학부생 2인(초심자, 이 중 한 명은 서버를 직접 운영해본 경험이 전혀 없음)**
목적: 원티드 AI Championship 2026 제출용 서비스를 3주 안에 실제로 완성하기 위한, 코드 작성에 바로 들어갈 수 있는 수준의 구현 명세서 겸 개발 계획서.

## 0. 이 문서를 읽는 방법

**Claude Code에게**: 이 문서는 위에서 아래로 순서대로 구현하면 되도록 설계되어 있다. 각 절의 산출물은 이후 절의 전제 조건이다(예: 3절 환경 셋업이 끝나야 5절 리포지토리 구조를 만들 수 있고, 6절 DB 스키마가 있어야 8절 상태머신을 구현할 수 있다). 사용자가 별도로 지시하지 않는 한, **16절의 마일스톤 순서**를 그대로 따라 작업을 작은 단위로 쪼개어 진행하고, 각 단위 작업이 끝날 때마다 실제로 실행되는지 확인한 뒤 다음으로 넘어가라. 이 프로젝트에는 "정직성 가드레일"(1-2절)이라는 절대 원칙이 있으니, 문서 생성과 관련된 어떤 코드를 작성하든 이 원칙을 절대 깨지 않아야 한다. **특히 2-1절과 13-3절, 19절은 서버를 한 번도 운영해본 적 없는 팀원(A)을 위한 절이니, A가 맡을 작업을 안내할 때는 반드시 이 절들의 설명 수준을 유지하거나 더 쉽게 풀어써라 — "당연히 알겠지"라고 생략하지 마라.**

**두 학부생에게**: 이 문서는 여러분이 처음 접할 수 있는 개념(REST API, JWT, 상태머신, 임베딩, 벡터DB, 그리고 "서버"라는 개념 자체)이 나올 때마다 짧게 설명을 붙여뒀다. 모르는 용어가 나오면 당황하지 말고 해당 설명을 먼저 읽으면 된다. 이 문서만 있으면 Claude Code(또는 다른 AI 코딩 도구)에게 "이 문서대로 구현해줘"라고 맡길 수 있도록 작성했다. **특히 4090 PC를 담당하는 분(서버 운영 경험 없음)은 2-1절을 가장 먼저 읽는 것을 권장한다** — 이 프로젝트에서 "서버를 운영한다"는 게 실제로 무엇을 뜻하는지, 무엇을 조심해야 하는지 처음부터 차근차근 설명해뒀다.

**이전 문서 대비 변경점**: 계획서 확정 이후, (1) **채용공고 파싱 기능을 완전히 제거**했다 — 이 서비스의 목적은 특정 회사 지원용 자소서가 아니라 **CV(경력기술서)에 들어갈 공백기 항목 자체를 작성하는 것**이므로, 최종 생성물은 특정 직무·회사에 종속되지 않는 범용 경력기술서 문장이다. (2) **인증 방식을 카카오/구글 소셜 로그인에서 이메일+비밀번호 자체 회원가입으로 단순화**했다 — 초심자 2인이 3주 안에 구현하기에 외부 OAuth 앱 등록 없이 가는 편이 훨씬 안전하다. (3) 개발 환경은 **Windows 기준**으로, Docker 없이 곧바로 개발할 수 있도록 단순화했다(이유는 3절 참고).

---

## 1. 프로젝트 개요

### 1-1. 한 줄 정의

사용자가 구직 공백기 동안의 활동을 다회차 대화형 인터뷰와 개인 기록물(블로그·자격증 등)로 입력하면, **직무·회사와 무관하게** STAR 구조의 경력기술서 문장을 근거와 함께 생성해주는 웹 서비스. 사용자는 생성된 문장을 자신의 이력서/경력기술서에 그대로 가져다 쓸 수 있다.

### 1-2. 절대 원칙 — 정직성 가드레일

이 서비스에서 가장 중요한 규칙이다: **사용자가 명시적으로 확인/작성하지 않은 내용, 또는 사용자의 개인 기록물에 실제로 존재하지 않는 내용은 최종 생성물에 절대 포함되면 안 된다.** 이는 프롬프트 지시 수준이 아니라 **데이터 흐름 수준**에서 강제한다 — 최종 문서 생성 함수는 오직 `confirmed_facts` 테이블(6-6절)에 저장된, 사용자가 확인한 사실만을 입력으로 받을 수 있게 코드 구조 자체를 설계한다. LLM이 이 규칙을 어겼는지 재검증하는 후처리 단계(12-4절)도 반드시 구현한다.

### 1-3. 핵심 UX 원칙 — Recognition over Recall

사용자에게 "공백기에 뭘 하셨나요?" 같은 백지 질문을 던지지 않는다. 대신 AI가 업계 통념(또는 사용자가 첨부한 실제 기록물)을 근거로 그럴듯한 초안을 먼저 제시하고, 사용자는 "맞아요" 또는 "아니요, 이렇게 고칠게요"로 확인/정정만 하면 된다. 이는 특히 스스로 "내세울 게 없다"고 느끼는 사용자의 답변 장벽을 크게 낮추기 위한 설계다.

### 1-4. 핵심 사용자 흐름

1. 회원가입/로그인
2. 공백기 기간 입력
3. 활동 카테고리 선택(알바/프리랜서/자격증/돌봄/봉사/자기계발/구직활동 등, 복수 선택)
4. (선택) 관련 기록물 첨부 — 블로그 URL, 이미지(자격증·수료증), 텍스트 붙여넣기
5. 카테고리별로 AI가 초안(빈도·업무·성과)을 먼저 제시 → 사용자가 확인/정정
6. 확정된 사실을 바탕으로 카테고리별 경력기술서 문장 생성, 각 문장에 근거 하이라이트 표시
7. 톤 조절·재생성·직접 수정 후 확정, 텍스트 복사 또는 내보내기

표기 규칙: 문서 설명은 한국어, 코드·식별자·API 경로·JSON 필드명·주석은 영어로 작성한다.

---

## 2. 시스템 아키텍처

```
[브라우저 (Next.js SPA)]
        │  HTTPS / REST
        ▼
[백엔드 (FastAPI, Python) — Railway 등 클라우드에 배포]
        │
        ├── 인증 서비스 (이메일+비밀번호, JWT 발급)
        ├── 인터뷰 오케스트레이터 (대화 상태머신)
        ├── AI 어댑터 레이어 (LLM Provider 추상화)
        │        │
        │        ├─▶ [LocalOllamaProvider] ──HTTPS(Cloudflare Tunnel)──▶ [RTX 4090 PC: Ollama 추론 서버] (1순위)
        │        └─▶ [GeminiProvider] ──▶ [Google Gemini API] (로컬 서버 장애·과부하 시 대체)
        │
        ├── 기록물 수집 파이프라인 (URL 파서 → 청킹 → 임베딩)
        ├── 문서 생성·근거매핑 모듈
        │
        ▼
[PostgreSQL + pgvector (Supabase, 클라우드 관리형)]   [오브젝트 스토리지(Supabase Storage 또는 S3)]
```

v1 계획서 대비 **채용공고 파싱 모듈이 완전히 제거**됐다. 이로써 외부 사이트 크롤링 실패·JS 렌더링 대응 같은, 초심자에게 특히 까다로운 문제 하나를 통째로 없앨 수 있었다 — 이번 범위 축소가 일정상 실질적인 이득이 된다.

**왜 로컬 GPU + 클라우드 하이브리드인가**: 웹앱 본체(프론트·백엔드·DB)는 클라우드에 올려 항상 접속 가능하게 유지하고, 부하가 큰 LLM 추론만 팀원의 4090 PC로 보낸다. 4090 PC는 집/사무실 네트워크 안에 있어 외부에서 바로 접근할 수 없으므로, Cloudflare Tunnel로 고정된 HTTPS 주소를 하나 발급받아 그 주소를 백엔드가 호출한다. 이렇게 분리해두면 데모 당일 4090 PC나 집 네트워크에 문제가 생겨도 웹앱 자체는 죽지 않고, "AI 생성만 일시적으로 Gemini로 대체"되는 정도로 그친다.

### 2-1. "서버를 운영한다"는 게 정확히 무엇인가 — 처음 해보는 사람을 위한 설명

이 절은 4090 PC를 담당하지만 서버를 운영해본 적 없는 팀원(이하 A)을 위한 것이다. Claude Code는 A와 관련된 작업을 안내할 때 이 절의 눈높이를 유지해야 한다.

**"서버"란 그냥 "항상 켜져서 요청을 기다리는 프로그램"이다.** 평소 쓰는 프로그램(메모장, 게임 등)은 내가 실행하고 조작해야 뭔가 일어나지만, 서버는 반대다 — 실행해두면 조용히 대기하고 있다가, 누군가(이 경우 우리 백엔드)가 인터넷을 통해 "요청"을 보내면 그때 응답을 돌려준다. 이 프로젝트에서 A의 PC 위에 떠 있는 서버는 정확히 하나, **Ollama**뿐이다. Ollama는 설치하면 자동으로 "AI 모델에게 질문을 보내면 답을 준다"는 역할을 하는 서버로 백그라운드에서 계속 켜져 있는다.

**"로컬 서버를 클라우드에 노출한다"는 게 위험하지 않은가?** 합리적인 걱정이다. 여기서 쓰는 Cloudflare Tunnel은 A의 PC 전체를 인터넷에 공개하는 게 아니라, **딱 하나의 문(포트 11434, Ollama가 응답을 기다리는 곳)만** 정해진 안전한 통로로 열어준다. 비유하자면, 집 전체 출입문을 열어두는 게 아니라 "배달 음식만 주고받을 수 있는 우편함 구멍 하나"를 뚫어주는 것과 비슷하다. 원격 데스크톱처럼 PC 화면을 직접 조작당하거나 다른 파일에 접근당할 위험은 없다.

**A가 실제로 해야 할 일은 결국 세 가지뿐이다**:
1. Ollama를 설치하고 켜둔다(설치하면 자동으로 켜진 채 유지된다 — 매번 실행할 필요 없음).
2. Cloudflare Tunnel을 한 번 설정해두면, 이후에는 PC를 켤 때마다 자동으로 같이 켜지도록 등록해둔다(13-3절에서 그 방법을 안내한다).
3. 데모·투표 기간 동안 PC가 꺼지거나 잠들지 않게 전원 설정만 신경 쓴다.

**뭔가 잘못됐을 때 어떻게 확인하나?** "서버가 잘 켜져 있다"는 걸 코드를 몰라도 확인할 수 있는 가장 쉬운 방법은, 브라우저 주소창에 `http://localhost:11434`를 입력해보는 것이다 — "Ollama is running"이라는 문구가 뜨면 정상이다. 이 확인법은 19절 체크리스트에서 다시 안내한다.

---

## 3. 기술 스택 및 초심자를 위한 선택 이유

| 영역 | 선택 | 왜 이 선택인가 (초심자 관점) |
|---|---|---|
| 프론트엔드 | Next.js(React) + TypeScript | React 기반 중 배포(Vercel)가 가장 간단하고 자료가 압도적으로 많아 막혔을 때 검색으로 해결하기 쉽다 |
| 백엔드 | Python + FastAPI | 문법이 간결하고, 자동으로 API 문서(Swagger UI, `/docs`)가 생성돼 프론트-백엔드 협업 시 "이 API가 뭘 받고 뭘 주는지"를 눈으로 바로 확인할 수 있다 |
| DB | PostgreSQL + pgvector, **Supabase**(관리형 클라우드) | **로컬에 Postgres를 직접 설치하지 않는다.** Supabase에 무료로 프로젝트 하나를 만들면 개발용·배포용 DB를 동일하게 하나로 쓸 수 있어 "로컬 DB와 배포 DB가 다르다"는 초심자 흔한 함정을 피할 수 있다 |
| 백엔드 배포 | Railway | 저장소를 연결하면 Dockerfile 없이도 Python 프로젝트를 자동 인식해 배포해준다 |
| 프론트 배포 | Vercel | Next.js 제작사가 만든 배포 서비스라 설정이 거의 필요 없다 |
| 로컬 LLM 서빙 | Ollama | Windows 설치 파일 하나로 끝나고, 모델 다운로드·실행이 명령어 한 줄(`ollama run 모델명`)로 된다 |
| 로컬 → 외부 노출 | Cloudflare Tunnel | 공유기 포트포워딩 설정 없이(초심자에게 어렵고 보안 위험도 있음) 안전하게 HTTPS 주소를 받을 수 있다 |
| 컨테이너화(Docker) | **이번 범위에서는 사용하지 않음** | Docker는 유용하지만 Windows에서 WSL2 설정까지 포함하면 초심자에게 새로운 학습 곡선이 하나 더 생긴다. 3주짜리 프로젝트에서는 각자 PC에 Python·Node를 직접 설치해 실행하는 편이 훨씬 빠르게 시작할 수 있다. (이후 여유가 되면 배포 단계에서만 선택적으로 고려) |

---

## 4. 개발 환경 셋업 가이드 (Windows 기준, 두 사람 공통)

두 사람 모두 아래를 설치한다. 이미 설치돼 있다면 건너뛰어도 된다.

1. **Git**: [git-scm.com](https://git-scm.com/download/win)에서 설치. 설치 후 터미널(PowerShell)에서 `git --version`으로 확인.
2. **Python 3.11 이상**: [python.org](https://www.python.org/downloads/)에서 설치할 때 **"Add python.exe to PATH"에 반드시 체크**한다(초심자가 가장 자주 놓치는 부분). 설치 후 `python --version` 확인.
3. **Node.js LTS 버전**: [nodejs.org](https://nodejs.org/)에서 설치. 설치 후 `node --version`, `npm --version` 확인.
4. **코드 에디터**: VS Code 권장.
5. **GitHub 계정 및 저장소 접근 권한**: 두 사람 모두 하나의 GitHub 저장소에 협업자로 등록한다.

**4090 PC를 가진 팀원만 추가로 설치**:

6. **Ollama**: [ollama.com/download/windows](https://ollama.com/download/windows)에서 설치 파일을 받아 실행하면 끝난다. 설치가 끝나면 자동으로 백그라운드에서 Ollama 서버가 실행된다(작업 표시줄에 아이콘이 뜬다). 터미널에서 아래로 확인한다.
   ```
   ollama --version
   ollama pull exaone3.5:7.8b
   ollama run exaone3.5:7.8b
   ```
   (모델명은 10-3절에서 다시 확정한다. 다운로드는 모델 크기에 따라 몇 분~수십 분 걸릴 수 있다.)
7. **Cloudflare Tunnel(cloudflared)**: [발급 가이드](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)에서 Windows용 `cloudflared.exe`를 받는다. 자세한 설정 절차는 13-3절에 별도로 정리했다 — 이 단계는 로컬 LLM 서버가 어느 정도 완성된 뒤(2주차)에 진행해도 된다.

**공용 계정 발급(둘 중 아무나 진행 가능)**:

8. **Supabase 계정**: [supabase.com](https://supabase.com)에서 가입 후 새 프로젝트를 하나 생성한다. 프로젝트 생성 시 나오는 DB 비밀번호를 안전한 곳에 기록해둔다. 생성 후 "Project Settings → Database"에서 연결 문자열(`DATABASE_URL`)을 확인할 수 있다. SQL Editor에서 아래 한 줄을 실행해 pgvector 확장을 켠다.
   ```sql
   create extension if not exists vector;
   ```
9. **Google AI Studio(Gemini API 키)**: [aistudio.google.com](https://aistudio.google.com/)에서 구글 계정으로 로그인 후 API 키를 발급받는다(무료 티어로 충분히 개발 가능). 이 키는 로컬 서버가 준비되기 전까지 개발용 LLM으로도 쓰고, 이후에는 장애 대응용 폴백으로 쓴다.

---

## 5. 리포지토리 구조 (모노레포)

```
annswieoteum/
├── frontend/                      # Next.js (TypeScript)
│   ├── app/
│   ├── components/
│   ├── lib/
│   │   ├── api-client.ts
│   │   └── query-keys.ts
│   ├── package.json
│   └── .env.local.example
│
├── backend/                       # FastAPI (Python)
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── auth.py
│   │   │   ├── sessions.py
│   │   │   ├── interview.py
│   │   │   ├── records.py
│   │   │   └── document.py
│   │   ├── core/
│   │   │   ├── config.py          # 환경변수 로딩
│   │   │   ├── security.py        # 비밀번호 해싱, JWT
│   │   │   └── deps.py            # FastAPI 의존성 주입(로그인 확인 등)
│   │   ├── models/                 # SQLAlchemy ORM 모델
│   │   ├── schemas/                 # Pydantic 요청/응답 스키마
│   │   ├── services/
│   │   │   ├── interview_orchestrator.py
│   │   │   ├── llm/
│   │   │   │   ├── base.py
│   │   │   │   ├── local_ollama.py
│   │   │   │   ├── gemini_provider.py
│   │   │   │   └── fallback.py
│   │   │   ├── embedding/
│   │   │   │   ├── base.py
│   │   │   │   ├── local_ollama_embedding.py
│   │   │   │   └── cloud_embedding.py
│   │   │   ├── record_pipeline/
│   │   │   │   ├── platform_detector.py
│   │   │   │   ├── parsers/
│   │   │   │   │   ├── naver_blog.py
│   │   │   │   │   ├── tistory.py
│   │   │   │   │   └── generic.py
│   │   │   │   ├── ocr.py
│   │   │   │   └── chunker.py
│   │   │   └── document_generator.py
│   │   ├── prompts/                # 프롬프트 템플릿 파일들(.txt 또는 .jinja)
│   │   └── db/
│   │       ├── session.py
│   │       └── migrations/         # Alembic
│   ├── tests/
│   ├── requirements.txt
│   └── .env.example
│
├── .gitignore
└── README.md
```

**Git 협업 규칙** (브랜치·PR 경험이 있는 두 사람 기준, 간단히만 정한다):
- `main` 브랜치는 항상 실행 가능한 상태를 유지한다.
- 기능 단위로 `feature/<기능명>` 브랜치를 따서 작업하고(예: `feature/auth`, `feature/interview-flow`), PR로 `main`에 머지한다.
- 4090 PC를 가진 팀원은 주로 `backend/app/services/llm`, `services/embedding`, `services/record_pipeline` 쪽을, 다른 팀원은 `frontend` 전체와 `backend/app/api`, `services/interview_orchestrator`, `document_generator` 쪽을 맡는 방식으로 자연스럽게 폴더가 겹치지 않게 분담하면 충돌이 적다.
- 커밋 메시지는 `feat: `, `fix: `, `chore: ` 같은 접두어만 붙이는 정도로 충분하다(Conventional Commits 전체 규칙까지는 이 프로젝트 규모에서 불필요).

---

## 6. 데이터베이스 스키마

> **용어 설명 (초심자용)**: 아래 표는 각 "테이블"(엑셀 시트라고 생각해도 된다)이 어떤 "컬럼"(열)을 가지는지 정의한 것이다. `FK`는 Foreign Key(외래키)의 줄임말로, 다른 테이블의 행을 가리키는 값이다. `PK`는 Primary Key(기본키)로 그 테이블에서 각 행을 구분하는 고유값이다.

### 6-1. `users`

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | UUID | PK | |
| email | TEXT | UNIQUE, NOT NULL | 로그인 아이디로 사용 |
| password_hash | TEXT | NOT NULL | 평문 비밀번호는 절대 저장하지 않는다. bcrypt로 해싱(7-1절) |
| nickname | TEXT | NOT NULL | |
| created_at | TIMESTAMPTZ | NOT NULL, default now() | |
| updated_at | TIMESTAMPTZ | NOT NULL, default now() | |
| deleted_at | TIMESTAMPTZ | NULLABLE | 회원 탈퇴 시 soft delete |

### 6-2. `refresh_tokens`

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK → users.id | |
| token_hash | TEXT | NOT NULL | 원문이 아닌 SHA-256 해시로 저장 |
| expires_at | TIMESTAMPTZ | NOT NULL | |
| revoked_at | TIMESTAMPTZ | NULLABLE | |
| created_at | TIMESTAMPTZ | NOT NULL, default now() | |

### 6-3. `sessions` (인터뷰 세션)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK → users.id, NOT NULL | |
| status | TEXT | NOT NULL, default 'PERIOD_INPUT' | 8절 상태머신 값 |
| current_category_id | UUID | FK → activity_categories.id, NULLABLE | 카테고리 반복 진행 중 현재 위치 |
| created_at | TIMESTAMPTZ | NOT NULL, default now() | |
| updated_at | TIMESTAMPTZ | NOT NULL, default now() | |

### 6-4. `gap_periods`

| 컬럼 | 타입 | 제약 |
|---|---|---|
| id | UUID | PK |
| session_id | UUID | FK → sessions.id, UNIQUE, NOT NULL |
| start_date | DATE | NOT NULL |
| end_date | DATE | NOT NULL, CHECK (end_date >= start_date) |
| created_at | TIMESTAMPTZ | NOT NULL, default now() |

### 6-5. `activity_categories`

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | UUID | PK | |
| session_id | UUID | FK → sessions.id, NOT NULL | |
| category_type | TEXT | NOT NULL, CHECK IN ('part_time','freelance','certificate','caregiving','volunteer','self_study','job_search','other') | |
| custom_label | TEXT | NULLABLE | category_type='other'일 때 사용자 입력 라벨 |
| order_index | INT | NOT NULL | |
| status | TEXT | NOT NULL, default 'PENDING', CHECK IN ('PENDING','IN_PROGRESS','DONE') | |

### 6-6. `confirmed_facts`

정직성 가드레일(1-2절)의 핵심 테이블. **문서 생성 단계는 이 테이블의 내용만 입력으로 사용할 수 있다.**

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | UUID | PK | |
| category_id | UUID | FK → activity_categories.id, NOT NULL | |
| fact_type | TEXT | NOT NULL, CHECK IN ('frequency','task','achievement') | |
| content | TEXT | NOT NULL | 확정된 사실 문장 |
| source_type | TEXT | NOT NULL, CHECK IN ('user_confirmed','user_edited','record_cited') | |
| source_record_chunk_id | UUID | FK → record_chunks.id, NULLABLE | source_type='record_cited'일 때만 |
| ai_draft_text | TEXT | NULLABLE | 확정 전 AI가 제시했던 초안(참고용 보관) |
| created_at | TIMESTAMPTZ | NOT NULL, default now() | |

### 6-7. `records`

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | UUID | PK | |
| session_id | UUID | FK → sessions.id, NOT NULL | |
| record_type | TEXT | NOT NULL, CHECK IN ('blog_url','image','pasted_text') | |
| source_url | TEXT | NULLABLE | |
| platform | TEXT | NULLABLE, CHECK IN ('naver_blog','tistory','velog','brunch','generic') | |
| storage_path | TEXT | NULLABLE | 이미지 업로드 시 Supabase Storage 경로 |
| raw_text | TEXT | NULLABLE | 파싱/OCR 완료 후 채워짐 |
| parse_status | TEXT | NOT NULL, default 'PENDING', CHECK IN ('PENDING','PARSING','DONE','FAILED') | |
| parse_error | TEXT | NULLABLE | |
| created_at | TIMESTAMPTZ | NOT NULL, default now() | |

### 6-8. `record_chunks`

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | UUID | PK | |
| record_id | UUID | FK → records.id, NOT NULL | |
| chunk_text | TEXT | NOT NULL | |
| chunk_index | INT | NOT NULL | |
| published_at | DATE | NULLABLE | 원 게시물 작성일 |
| embedding | VECTOR(1024) | NULLABLE | 사용 임베딩 모델의 차원에 맞춰 조정(11절) |
| embedding_model | TEXT | NULLABLE | |
| created_at | TIMESTAMPTZ | NOT NULL, default now() | |

인덱스: `CREATE INDEX ON record_chunks USING ivfflat (embedding vector_cosine_ops);`

### 6-9. `generated_documents`

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | UUID | PK | |
| session_id | UUID | FK → sessions.id, NOT NULL | |
| tone | TEXT | NOT NULL, default 'neutral', CHECK IN ('plain','neutral','assertive') | |
| version | INT | NOT NULL, default 1 | |
| status | TEXT | NOT NULL, default 'DRAFT', CHECK IN ('DRAFT','FINALIZED') | |
| created_at | TIMESTAMPTZ | NOT NULL, default now() | |

### 6-10. `generated_sentences`

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | UUID | PK | |
| document_id | UUID | FK → generated_documents.id, NOT NULL | |
| category_id | UUID | FK → activity_categories.id, NOT NULL | 이 문장이 어느 카테고리에서 나왔는지 |
| order_index | INT | NOT NULL | |
| text | TEXT | NOT NULL | |
| evidence_fact_ids | JSONB | NOT NULL, default '[]' | 근거로 쓰인 confirmed_facts.id 배열 |
| consistency_check_passed | BOOLEAN | NOT NULL, default true | |

### 6-11. 관계 요약

```
users ──1:N── sessions ──1:1── gap_periods
sessions ──1:N── activity_categories ──1:N── confirmed_facts
sessions ──1:N── records ──1:N── record_chunks
record_chunks ──1:N── confirmed_facts (source_record_chunk_id, nullable)
sessions ──1:N── generated_documents ──1:N── generated_sentences
```

삭제 정책: `sessions` 삭제 시 하위 전체가 `ON DELETE CASCADE`로 연쇄 삭제된다.

**마이그레이션 도구**: Alembic을 사용한다(`alembic init migrations`, 모델 변경 후 `alembic revision --autogenerate`, `alembic upgrade head`). Claude Code는 6절 스키마를 SQLAlchemy 모델로 먼저 작성하고, Alembic 마이그레이션 파일을 생성한 뒤 Supabase DB에 적용하는 순서로 진행한다.

---

## 7. 인증 설계 (이메일 + 비밀번호)

> **용어 설명**: JWT(JSON Web Token)는 로그인한 사용자를 식별하기 위해 서버가 발급하는, 위조 방지 서명이 붙은 문자열이다. 브라우저는 이 토큰을 API 요청마다 함께 보내고, 서버는 서명을 검증해 "이 요청은 진짜 이 사용자가 보낸 것"임을 확인한다.

### 7-1. 회원가입/로그인 흐름

1. 회원가입: 이메일·비밀번호·닉네임을 받아, 비밀번호는 `passlib`의 `bcrypt` 알고리즘으로 해싱해 저장한다. 이메일 중복 확인 후 `users` row 생성.
2. 로그인: 이메일로 사용자를 찾고, 입력된 비밀번호를 해시와 대조(`passlib.verify`)한다.
3. 성공 시 **Access Token**(JWT, 만료 30분)과 **Refresh Token**(만료 14일)을 발급한다. Access Token은 응답 바디로 내려주고 프론트는 메모리(React state)에만 보관한다. Refresh Token은 `httpOnly + Secure + SameSite=Lax` 쿠키로 내려준다(자바스크립트에서 직접 접근 불가 — 탈취 위험을 줄인다).
4. Access Token 만료 시 프론트는 `POST /api/v1/auth/refresh`를 호출해 쿠키의 Refresh Token으로 새 Access Token을 받는다.

### 7-2. 비밀번호 요구사항

최소 8자 이상만 강제한다(해커톤 규모에 맞춘 최소 검증). 프론트·백엔드 양쪽에서 검증한다.

### 7-3. 라이브러리

- 비밀번호 해싱: `passlib[bcrypt]`
- JWT 발급/검증: `python-jose[cryptography]` 또는 `PyJWT`

---

## 8. 인터뷰 상태 머신

```
PERIOD_INPUT → CATEGORY_SELECT → RECORD_UPLOAD(선택)
  → [CATEGORY별 반복: FREQ_DRAFT → FREQ_CONFIRM → TASK_DRAFT → TASK_CONFIRM → ACHIEVEMENT_DRAFT → ACHIEVEMENT_CONFIRM]
  → RESULT_GENERATE → RESULT_REVIEW
```

> **용어 설명**: "상태 머신"이란 시스템이 가질 수 있는 상태들의 목록과, 어떤 조건에서 한 상태에서 다른 상태로 넘어가는지를 명시적으로 정의한 것이다. 이렇게 관리하면 "지금 사용자가 인터뷰의 어느 단계에 있는지"를 코드 곳곳에 흩어진 if문 대신 한 곳(예: `sessions.status` 컬럼)에서 명확히 관리할 수 있다.

이전 계획서에 있던 `JD_INPUT` 상태는 채용공고 파싱 제거에 따라 삭제됐다. `ACHIEVEMENT_CONFIRM`이 끝나고 다음 카테고리가 없으면 곧바로 `RESULT_GENERATE`로 넘어간다.

### 8-1. 세션 컨텍스트 데이터 스키마

```python
class InterviewContext(BaseModel):
    session_id: UUID
    status: str
    gap_period: GapPeriod | None
    categories: list[ActivityCategory]
    current_category: ActivityCategory | None
    confirmed_facts: list[ConfirmedFact]
    available_record_chunks: list[RecordChunk]   # 현재 카테고리와 관련성 높은 기록물 조각 (11절)
```

### 8-2. 전이 표

| 현재 상태 | 트리거 | 다음 상태 | 부수 효과 |
|---|---|---|---|
| PERIOD_INPUT | `POST /sessions/{id}/period` | CATEGORY_SELECT | gap_periods insert |
| CATEGORY_SELECT | `POST /sessions/{id}/categories` | RECORD_UPLOAD | activity_categories bulk insert |
| RECORD_UPLOAD | `POST /sessions/{id}/records` (반복 가능) | RECORD_UPLOAD (유지) | records insert, 비동기 파싱 시작 |
| RECORD_UPLOAD | `POST /sessions/{id}/records/skip` | FREQ_DRAFT(첫 카테고리) | current_category_id 설정 |
| FREQ_DRAFT | `GET /sessions/{id}/interview/next` | FREQ_CONFIRM | AI 초안 반환(미저장) |
| FREQ_CONFIRM | `POST /sessions/{id}/interview/confirm` | TASK_DRAFT | confirmed_facts insert |
| TASK_DRAFT→TASK_CONFIRM→ACHIEVEMENT_DRAFT→ACHIEVEMENT_CONFIRM | 동일 패턴 반복 | | fact_type 순서대로 insert |
| ACHIEVEMENT_CONFIRM (마지막 카테고리) | `POST /sessions/{id}/interview/confirm` | RESULT_GENERATE | category.status='DONE' |
| ACHIEVEMENT_CONFIRM (다음 카테고리 존재) | 〃 | FREQ_DRAFT(다음 카테고리) | current_category_id 갱신 |

---

## 9. REST API 명세

베이스 경로 `/api/v1`. 🔒는 로그인(Access Token) 필요.

### 9-1. 인증

| 메서드/경로 | 요청 | 응답 |
|---|---|---|
| POST `/auth/register` | `{ "email": str, "password": str, "nickname": str }` | `{ "user_id": UUID }` |
| POST `/auth/login` | `{ "email": str, "password": str }` | `{ "access_token": str, "expires_in": 1800 }` + Set-Cookie(refresh_token) |
| POST `/auth/refresh` | (쿠키 사용) | `{ "access_token": str, "expires_in": 1800 }` |
| POST `/auth/logout` 🔒 | - | 204 |
| GET `/auth/me` 🔒 | - | `{ "id": UUID, "email": str, "nickname": str }` |

에러: 이메일 중복 `409 email_already_exists`, 로그인 실패 `401 invalid_credentials`.

### 9-2. 세션

| 메서드/경로 | 설명 | 응답 |
|---|---|---|
| POST `/sessions` 🔒 | 새 인터뷰 세션 생성 | `{ "session_id": UUID, "status": "PERIOD_INPUT" }` |
| GET `/sessions/{id}` 🔒 | 현재 상태 조회 | `InterviewContext` |
| DELETE `/sessions/{id}` 🔒 | 세션 및 하위 데이터 삭제 | 204 |

### 9-3. 인터뷰 진행

| 메서드/경로 | 요청 | 응답 |
|---|---|---|
| POST `/sessions/{id}/period` 🔒 | `{ "start_date": "2025-01-01", "end_date": "2025-08-31" }` | `{ "status": "CATEGORY_SELECT" }` |
| POST `/sessions/{id}/categories` 🔒 | `{ "categories": [{ "category_type": "part_time" }] }` | `{ "status": "RECORD_UPLOAD" }` |
| POST `/sessions/{id}/records/skip` 🔒 | - | `{ "status": "FREQ_DRAFT", "current_category_id": UUID }` |
| GET `/sessions/{id}/interview/next` 🔒 | - | `{ "step": "FREQ_DRAFT", "category_id": UUID, "ai_draft": str, "based_on": [...] }` |
| POST `/sessions/{id}/interview/confirm` 🔒 | `{ "step": "FREQ_CONFIRM", "final_text": str, "was_edited": bool }` | 다음 스텝 정보 |

### 9-4. 기록물

| 메서드/경로 | 설명 |
|---|---|
| POST `/sessions/{id}/records` 🔒 | 블로그 URL 등록: `{ "record_type": "blog_url", "source_url": str }` |
| POST `/sessions/{id}/records/upload` 🔒 (multipart) | 이미지 업로드 |
| POST `/sessions/{id}/records/text` 🔒 | 텍스트 직접 붙여넣기 |
| GET `/sessions/{id}/records/{record_id}` 🔒 | 파싱 상태 폴링 |
| DELETE `/sessions/{id}/records/{record_id}` 🔒 | 삭제 |

### 9-5. 문서 생성/조회/수정

| 메서드/경로 | 설명 | 요청 |
|---|---|---|
| POST `/sessions/{id}/generate` 🔒 | 최종 생성 트리거 | `{ "tone": "neutral" }` |
| GET `/sessions/{id}/document` 🔒 | 최신 생성 문서 조회 | - |
| POST `/sessions/{id}/document/regenerate` 🔒 | 톤 변경 등 전체 재생성 | `{ "tone": "assertive" }` |
| PATCH `/sessions/{id}/document/sentences/{sentence_id}` 🔒 | 문장 직접 수정 | `{ "text": str }` |
| POST `/sessions/{id}/document/sentences/{sentence_id}/regenerate` 🔒 | 문장 단위 재생성 | - |
| POST `/sessions/{id}/document/finalize` 🔒 | 최종 확정 | - |
| GET `/sessions/{id}/export?format=txt` 🔒 | 텍스트 내보내기 | - |

### 9-6. 공통 에러 포맷

```json
{ "error": "error_code_snake_case", "message": "사용자에게 보여줄 한국어 설명" }
```

401(인증 만료), 403(타인 세션 접근), 404(리소스 없음), 409(상태머신 위반), 422(입력 검증 실패), 503(AI 어댑터 전체 장애).

---

## 10. AI 어댑터 레이어

### 10-1. 인터페이스

```python
class LLMProvider(Protocol):
    async def draft_suggestion(self, context: InterviewContext, step: str) -> Suggestion: ...
    async def generate_document(self, facts: list[ConfirmedFact], tone: str) -> DraftDocument: ...
    async def health_check(self) -> bool: ...
```

(v1 계획서와 달리 `generate_document`에서 `jd: JobDescription` 파라미터가 제거됐다 — 이제 카테고리별 확정 사실과 톤만으로 생성한다.)

### 10-2. 구현체

- `LocalOllamaProvider`: Cloudflare Tunnel로 노출된 Ollama HTTP API를 호출. 타임아웃 20초(생성), 5초(health_check).
- `GeminiProvider`: Google Gemini API. 폴백.
- `FallbackProvider`: 두 provider를 우선순위 리스트로 감싸 순차 시도.

```python
class FallbackProvider:
    def __init__(self, providers: list[LLMProvider]):
        self.providers = providers  # [LocalOllamaProvider(), GeminiProvider()]

    async def draft_suggestion(self, context, step):
        for provider in self.providers:
            try:
                return await provider.draft_suggestion(context, step)
            except (TimeoutError, ProviderUnavailableError):
                continue
        raise AllProvidersFailedError()
```

### 10-3. 로컬 모델 선택

EXAONE 3.5 7.8B-Instruct와 Qwen2.5 14B-Instruct를 4비트 양자화(GGUF Q4_K_M)로 Ollama에 받아 실제 인터뷰 답변 샘플로 비교 후 확정한다(1주차 작업). 서빙 프레임워크는 Ollama.

### 10-4. 환경변수

| 변수명 | 설명 |
|---|---|
| `LOCAL_LLM_BASE_URL` | Cloudflare Tunnel로 노출된 Ollama 엔드포인트 |
| `LOCAL_LLM_MODEL_NAME` | 예: `exaone3.5:7.8b` |
| `GEMINI_API_KEY` | |
| `LLM_PROVIDER_ORDER` | 예: `local,gemini` |
| `DATABASE_URL` | Supabase 연결 문자열 |
| `JWT_SECRET` | 임의의 긴 랜덤 문자열(`openssl rand -hex 32`로 생성 가능) |

`backend/.env.example` 파일로 관리하고, 실제 `.env`는 `.gitignore`에 포함해 저장소에 올리지 않는다.

---

## 11. 임베딩 파이프라인

- **로컬**: Ollama로 서빙 가능한 임베딩 모델 `bge-m3`를 1순위로 사용(`ollama pull bge-m3`).
- **클라우드 폴백**: 로컬이 응답하지 않을 때 Gemini Embedding API 사용.
- 두 모델은 벡터 차원이 다르므로, `record_chunks.embedding_model`에 실제 사용된 모델을 기록해두고, 검색 시 질의 임베딩도 저장 시점과 같은 모델로 생성해 동일 공간에서 비교한다.

---

## 12. 프롬프트 템플릿

`backend/app/prompts/`에 파일로 분리 관리한다(코드에 하드코딩 금지).

### 12-1. 카테고리별 초안 프롬프트 (FREQ/TASK/ACHIEVEMENT 공통 구조)

```
[SYSTEM]
너는 구직 공백기 경력 재구성을 돕는 어시스턴트다.
사용자가 아직 확인하지 않은 내용은 "추측"임을 명확히 하고, 반드시 사용자 확인을 받아야 하는 초안으로만 제시해라.
{% if record_excerpts %}
아래 [근거 자료]에 있는 내용이 있으면 그것을 최우선으로 반영해 초안을 작성해라. 근거 자료에 없는 부분만 일반적인 패턴으로 추측해라.
[근거 자료]
{% for excerpt in record_excerpts %}
- ({{ excerpt.published_at }}) {{ excerpt.text }}
{% endfor %}
{% endif %}

[USER]
활동 카테고리: {{ category_label }}
공백 기간: {{ gap_period.start_date }} ~ {{ gap_period.end_date }}
이미 확인된 사실:
{% for fact in confirmed_facts_so_far %}
- {{ fact.content }}
{% endfor %}
다음 항목에 대한 초안을 한 문장으로 제시해라: {{ step_label }}

[출력 형식]
{ "draft_text": str, "based_on": "record" | "generic_pattern" }
```

### 12-2. 최종 문서 생성 프롬프트 (직무 무관 버전 — 정직성 가드레일 핵심)

```
[SYSTEM]
너는 사용자의 구직 공백기 경력을 STAR 구조(상황-과제-행동-결과)로 서술하는 어시스턴트다.
이 문장은 특정 회사나 직무를 겨냥한 것이 아니라, 사용자가 자신의 경력기술서/이력서에 그대로 넣을 수 있는 범용 문장이다.

절대 규칙: 아래 [확정된 사실 목록]에 없는 내용은 어떤 형태로도 추가하지 마라. 목록에 없는 수치, 고유명사, 성과를 지어내면 안 된다.
문장마다 사용한 사실의 번호를 함께 표시해라.
톤: {{ tone }} (plain=담백하게 사실 위주, neutral=일반적인 경력기술서 톤, assertive=성과를 적극적으로 어필)

[확정된 사실 목록 — 카테고리: {{ category_label }}]
{% for fact in confirmed_facts %}
[{{ loop.index }}] ({{ fact.source_type }}) {{ fact.content }}
{% endfor %}

[USER]
위 사실 목록만 근거로, 이 활동 카테고리에 대한 STAR 구조의 경력기술서 문장을 생성해라.

[출력 형식]
{ "sentences": [ { "text": str, "fact_indices": [int] } ] }
```

카테고리마다 이 프롬프트를 한 번씩 호출해 `generated_sentences`에 카테고리별로 저장한다.

### 12-3. JD 관련 프롬프트 삭제 안내

v1 명세에 있던 "JD 구조화 프롬프트"는 채용공고 파싱 제거에 따라 완전히 삭제됐다. Claude Code는 이 프롬프트를 구현하지 않는다.

### 12-4. 후처리 일관성 검증

```python
async def check_sentence_consistency(
    sentence: str, cited_facts: list[ConfirmedFact]
) -> bool:
    if not cited_facts:
        return False
    similarity = await max_cosine_similarity(sentence, [f.content for f in cited_facts])
    return similarity >= CONSISTENCY_THRESHOLD  # 초기값 0.55, 개발 중 튜닝
```

검증에 실패한 문장은 `generated_sentences.consistency_check_passed=false`로 저장하고, 프론트엔드에서 "확인이 더 필요한 문장"으로 별도 표시한다(자동 삭제하지 않음).

---

## 13. 기록물 수집 파이프라인

### 13-1. 처리 순서

1. **URL 식별**: 도메인으로 플랫폼 판별(네이버블로그/티스토리/velog/brunch/기타)
2. **플랫폼별 파서**: 네이버블로그는 본문이 iframe 안에 있어 별도 처리 필요. 비공개 블로그는 접근 불가를 사용자에게 안내.
3. **날짜 필터링**: 공백기 범위 밖의 게시물은 건너뛴다.
4. **청킹**: 문단 단위로 분리, 500자 초과 시 문장 경계에서 추가 분할, 50자 미만은 제외.
5. **임베딩 및 저장**: 11절 참고.
6. **의미 검색**: 카테고리 라벨을 쿼리로 관련 조각 top-N 검색 → 초안 생성 프롬프트에 투입.
7. **인용 표시**: 최종 문장의 근거가 기록물 조각이면 URL·날짜를 함께 반환.

### 13-2. 이미지 기록물(OCR)

Gemini의 비전 기능으로 이미지 텍스트를 추출한다(별도 OCR API 계정을 새로 만들지 않아도 되는 이점). 자격증 발급일 등 날짜가 있으면 `published_at`으로 파싱해 채운다.

### 13-3. Cloudflare Tunnel 설정 (Windows, 4090 PC 담당자용 — 서버 운영 처음이어도 괜찮다)

> **먼저 개념부터**: "터널"은 A의 PC 안에서만 열려 있는 `http://localhost:11434`(Ollama)를, 인터넷 어디서나 접속 가능한 `https://무언가.trycloudflare.com` 같은 진짜 주소로 바꿔주는 통로다. 이 주소를 클라우드에 있는 우리 백엔드가 호출하는 것이다. 2-1절에서 설명했듯 이 통로로는 Ollama의 응답만 오갈 뿐, PC의 다른 부분에는 전혀 접근할 수 없다.

1. `cloudflared.exe`를 다운로드한 폴더에서 PowerShell을 열고 로그인: `cloudflared.exe tunnel login` (브라우저가 열리며 Cloudflare 계정 인증 화면이 뜬다. 계정이 없으면 무료로 하나 만들면 된다.)
2. 터널 생성: `cloudflared.exe tunnel create annswieoteum-llm` (성공하면 터널 ID와 `.json` 인증 파일 경로가 화면에 출력된다 — 이 경로를 기록해둔다.)
3. 홈 디렉터리의 `.cloudflared` 폴더에 생성된 설정 파일에 아래 내용을 작성(`config.yml`, 파일이 없으면 메모장으로 새로 만들어도 된다):
   ```yaml
   tunnel: annswieoteum-llm
   credentials-file: C:\Users\<사용자명>\.cloudflared\<터널ID>.json
   ingress:
     - hostname: <원하는 서브도메인>.<보유 도메인 또는 Cloudflare 제공 도메인>
       service: http://localhost:11434
     - service: http_status:404
   ```
   (도메인이 따로 없다면 Cloudflare 계정에 무료 도메인을 하나 연결하거나, Cloudflare 무료 Zero Trust 대시보드에서 안내하는 방식을 그대로 따라가면 된다. Claude Code는 이 단계에서 A가 도메인을 갖고 있는지 먼저 확인하고, 없다면 임시 방편으로 `cloudflared tunnel --url http://localhost:11434` 형태의 **Quick Tunnel**(로그인·도메인 등록 없이 즉석에서 임시 주소를 발급해주는 방식)로 먼저 개발을 진행하도록 안내해도 된다 — 다만 Quick Tunnel 주소는 실행할 때마다 바뀌므로 데모 당일에는 위 방식대로 고정 주소를 쓰는 것이 안전하다.)
4. 실행: `cloudflared.exe tunnel run annswieoteum-llm`
5. **확인**: 다른 기기(예: 휴대폰 데이터로 연결한 스마트폰 브라우저)에서 3번에서 설정한 `https://<주소>`로 접속해봤을 때 Ollama 응답이 온다면 성공이다. PC 안에서 `http://localhost:11434`만 확인하는 것과는 다르게, 이 단계에서는 반드시 **PC 밖에서** 접속해봐야 진짜로 인터넷에 노출됐는지 확인할 수 있다.
6. PC가 재부팅돼도 자동 실행되도록 Windows 서비스로 등록: `cloudflared.exe service install` (관리자 권한 PowerShell에서 실행 — PowerShell 아이콘을 우클릭해 "관리자 권한으로 실행"을 선택하면 된다)
7. 발급된 주소를 백엔드 `.env`의 `LOCAL_LLM_BASE_URL`에 넣는다.

이 작업은 2주차에 로컬 LLM 연동이 어느 정도 되고 나서 진행해도 무방하다. **막히면 조급해하지 않아도 된다** — 최악의 경우 이 터널 없이도 서비스는 10-4절의 `GeminiProvider`만으로 동작하니, 터널 설정에 며칠 걸리더라도 서비스 전체가 멈추지는 않는다.

---

## 14. 프론트엔드 설계

### 14-1. 라우트 구조 (Next.js App Router)

```
app/
├── page.tsx                    # 랜딩
├── register/page.tsx
├── login/page.tsx
└── sessions/[id]/
    ├── period/page.tsx
    ├── categories/page.tsx
    ├── records/page.tsx
    ├── interview/page.tsx      # 채팅형 UI
    └── result/page.tsx
```

(v1 명세에 있던 `job-description/page.tsx`는 삭제됐다.)

### 14-2. 핵심 컴포넌트

- `InterviewChatThread`: AI 말풍선(초안 제시) + 사용자 응답(빠른 확인 버튼 + 자유 텍스트)
- `RecordUploadPanel`: URL 입력 + 파싱 상태 폴링 + 이미지 드래그앤드롭
- `EvidenceTag`: 문장별 근거 배지, 클릭 시 원문 인용 표시
- `ToneSlider`: 담백~적극적 3단계

### 14-3. 상태 관리

React Query로 서버 상태를 관리한다. 예: `['session', sessionId]`, `['session', sessionId, 'interview', 'next']`, `['session', sessionId, 'document']`. Access Token은 React Context에 메모리로만 보관하고, 새로고침 시 `/auth/refresh`로 재발급받는다.

---

## 15. 배포

- 프론트엔드: Vercel (GitHub 저장소 연결만 하면 자동 배포)
- 백엔드: Railway (GitHub 저장소 연결, `requirements.txt`와 시작 명령어 `uvicorn app.main:app --host 0.0.0.0 --port $PORT`만 설정하면 됨, Dockerfile 불필요)
- DB/스토리지: Supabase (4절에서 이미 생성한 프로젝트를 개발·배포 공통으로 사용)
- 로컬 LLM 서버: 4090 PC에서 Ollama 상시 구동 + Cloudflare Tunnel(13-3절)
- 모니터링: 최소한으로, Railway 자체 로그 확인 정도로 충분(Sentry 등 별도 도구는 이번 범위에서 생략 — 초심자에게 추가 학습 곡선이 되므로)

---

## 16. 개발 마일스톤 (Claude Code가 세부 작업으로 쪼갤 기준선)

아래는 "무엇을, 어떤 순서로" 만들지에 대한 큰 틀이다. Claude Code는 각 마일스톤을 실제 커밋 단위의 작은 작업으로 더 잘게 나누어 진행하면 된다. **A = 4090 PC 보유 팀원(인프라·AI 담당, 서버 운영 경험 없음 — 2-1절·13-3절·19절 참고), B = 다른 팀원(프론트·백엔드 로직 담당)**. 마감은 9월 20일이다. A의 작업은 대부분 "설치하고 명령어 한 줄 실행"에 가깝게 잘게 쪼개져 있으니, Claude Code는 A에게 작업을 배정할 때 한 번에 여러 단계를 뭉쳐서 주지 말고 하나씩 확인해가며 진행하도록 안내하라.

**마일스톤 1 — 기반 다지기 (1주차)**
- 저장소 생성, 5절 구조로 폴더 스캐폴딩
- Supabase 프로젝트 생성, 6절 스키마를 SQLAlchemy 모델 + Alembic 마이그레이션으로 작성 및 적용
- (B) 회원가입/로그인 API(7절) + 최소한의 프론트 로그인 화면
- (A) Ollama 설치, 로컬 모델 후보 비교, `LLMProvider`/`GeminiProvider`/`FallbackProvider` 골격(10절) — 이 시점에는 Cloudflare Tunnel 없이 로컬(같은 PC 안)에서만 테스트해도 된다
- 검증 기준: 회원가입 → 로그인 → 토큰으로 인증된 API 호출이 실제로 동작

**마일스톤 2 — 인터뷰 흐름 (1~2주차)**
- (B) 8절 상태머신 구현: `PERIOD_INPUT` → `CATEGORY_SELECT` → 카테고리 반복 루프까지, 이 시점에는 기록물·AI 연동 없이 더미 텍스트로 진행
- (A) 로컬 LLM 연동 완성, `draft_suggestion` 실제 동작 확인
- 두 작업을 합쳐 "로그인 → 기간 입력 → 카테고리 선택 → AI 초안 확인/정정"까지 실제로 돌아가게 만든다
- 검증 기준: 카테고리 하나를 끝까지(빈도→업무→성과) 확인/정정해서 `confirmed_facts`에 실제로 저장되는지 확인

**마일스톤 3 — 기록물 연동 (2주차)**
- (A) 13절 기록물 파이프라인(URL 파싱 → 청킹 → 임베딩 → 의미 검색), Cloudflare Tunnel 설정
- (B) 기록물 첨부 화면, 파싱 상태 폴링 UI
- 검증 기준: 블로그 URL을 넣으면 해당 기간 게시물이 초안 생성 시 근거로 실제 반영되는지 확인

**마일스톤 4 — 문서 생성 (2~3주차)**
- (B) 12절 문서 생성 프롬프트 연동, 근거 하이라이트 UI, 톤 슬라이더, 문장별 재생성/수정
- (A) 12-4절 일관성 검증 로직
- 검증 기준: 카테고리 여러 개를 끝까지 진행했을 때, 근거 없는 문장이 섞이지 않고 각 문장에 출처가 표시되는지 확인

**마일스톤 5 — 배포 및 안정화 (3주차)**
- 15절대로 배포, 폴백 전환 테스트(로컬 서버를 일부러 꺼서 Gemini로 자동 전환되는지 확인)
- 가상 시나리오 2~3개로 전체 흐름 리허설
- 9/16 이후 신규 기능 동결, 이후는 버그 수정과 발표 준비만 진행

---

## 17. 트러블슈팅 (초심자가 자주 마주치는 문제)

- **`python`이 인식되지 않음**: Python 설치 시 PATH 체크를 놓친 경우다. Python을 재설치하거나, 시스템 환경 변수에 Python 설치 경로를 수동으로 추가한다.
- **Ollama가 응답하지 않음**: 작업 표시줄에 Ollama 아이콘이 있는지 확인. 없다면 Ollama 앱을 다시 실행한다. `ollama list`로 모델이 실제로 받아져 있는지 확인한다.
- **Supabase 연결 실패**: `DATABASE_URL`에 비밀번호의 특수문자가 URL 인코딩되지 않은 경우가 흔하다(예: `@`는 `%40`으로).
- **CORS 에러(프론트에서 백엔드 호출 실패)**: FastAPI에서 `CORSMiddleware`에 프론트엔드 주소(`http://localhost:3000` 등)를 허용 목록에 추가했는지 확인한다.
- **Cloudflare Tunnel 주소가 백엔드에서 안 열림**: 4090 PC의 Ollama가 `0.0.0.0`이 아니라 `127.0.0.1`에만 바인딩돼 있으면 터널을 통해서도 접근이 안 될 수 있다 — Ollama 기본 설정으로는 보통 문제없지만, 안 되면 `OLLAMA_HOST=0.0.0.0` 환경변수를 설정하고 재시작해본다.
- **(서버 처음 운영하는 분을 위한 항목) PC를 재부팅했더니 서버가 죽은 것 같다**: 당황하지 않아도 된다. `http://localhost:11434`가 안 열리면 Ollama가 꺼진 것이니 Ollama 앱을 다시 켜면 되고, 외부에서 접속이 안 되면 터널이 꺼진 것이니 PowerShell에서 `cloudflared.exe tunnel run annswieoteum-llm`을 다시 실행하면 된다. 13-3절 6번처럼 서비스로 등록해두면 이 문제 자체가 거의 발생하지 않는다.
- **(서버 처음 운영하는 분을 위한 항목) Windows 방화벽이 "액세스를 허용하시겠습니까?" 경고를 띄운다**: Ollama나 cloudflared를 처음 실행할 때 Windows 방화벽이 뜨는 것은 정상이다. "액세스 허용"을 눌러주면 된다 — 이는 해당 프로그램이 네트워크를 쓰겠다는 표준적인 확인 절차이지, 문제가 생겼다는 신호가 아니다.
- **(서버 처음 운영하는 분을 위한 항목) 노트북 화면을 덮었더니(절전모드) 서버가 멈췄다**: 데스크톱이 아니라 노트북으로 4090을 운용하는 경우, Windows 설정 → 시스템 → 전원에서 "덮개를 닫았을 때 절전 모드로 전환"을 "아무 것도 안 함"으로 바꿔야 한다. 데모·투표 기간에는 이 설정을 반드시 미리 확인해둔다(19절 체크리스트 참고).
- **자꾸 뭔가 막힐 때의 기본 원칙**: 이 프로젝트에서 로컬 서버 관련 문제는 최악의 경우에도 서비스 전체를 멈추게 하지 않는다(10절 `FallbackProvider`가 자동으로 Gemini로 넘어간다). 그러니 A는 서버 쪽에서 막히더라도 서비스 전체가 죽었다고 걱정하지 말고, 시간을 넉넉히 두고 하나씩 확인하면 된다.

---

## 18. Claude Code에게 주는 마지막 지침

이 문서 전체를 근거 소스로 삼아 구현하되, 특히 다음을 지켜라.

1. 마일스톤 1부터 순서대로 진행하고, 각 마일스톤의 "검증 기준"이 실제로 통과하는지 확인한 뒤 다음으로 넘어가라.
2. 정직성 가드레일(1-2절)은 어떤 리팩터링을 하더라도 절대 깨지 않는다 — `confirmed_facts`에 없는 내용이 생성 결과에 들어갈 수 있는 코드 경로를 만들지 마라.
3. 이 문서에 없는 세부 구현 방식(변수명, 폴더 내부 파일 분리 방식 등)은 자유롭게 판단해도 되지만, 데이터 모델(6절)과 API 계약(9절)은 임의로 바꾸지 말고, 바꿔야 할 이유가 생기면 사용자에게 먼저 물어봐라.
4. 두 학부생이 초심자라는 점을 감안해, 각 마일스톤 완료 시 무엇을 어떻게 확인하면 되는지(예: 어떤 명령어를 실행하고 어떤 화면이 보여야 하는지) 함께 안내해줘라.
5. A(서버 담당)에게 작업을 안내할 때는 2-1절·13-3절·19절에서 쓴 것과 같은 수준의 설명(개념 먼저, 명령어는 그다음, 확인 방법까지 포함)을 유지해라. "서버를 띄운다"류의 표현을 설명 없이 던지지 마라.

---

## 19. 서버 운영 체크리스트 (A 전용 — 서버를 처음 운영하는 사람을 위한 요약판)

이 절은 지금까지 나온 서버 관련 내용(2-1절, 13-3절, 17절)을 실제 운영 시점에 그대로 따라 하기만 하면 되도록 순서대로 정리한 것이다. 코드를 몰라도 이 체크리스트만으로 확인할 수 있다.

**처음 설정할 때 (1회, 2주차쯤)**:
- [ ] Ollama 설치 완료, `ollama list`에 사용할 모델이 보인다
- [ ] `http://localhost:11434`를 PC 안에서 브라우저로 열면 "Ollama is running"이 뜬다
- [ ] Cloudflare Tunnel 설정 완료, `cloudflared.exe service install`로 자동 실행 등록까지 했다
- [ ] **PC가 아닌 다른 기기(휴대폰 등)**에서 터널 주소로 접속했을 때도 응답이 온다
- [ ] Windows 전원 설정에서 "절전 모드로 전환 안 함"으로 바꿔뒀다(노트북이면 덮개 닫을 때 설정도 함께)
- [ ] 터널 주소를 B에게 전달해서 백엔드 `.env`의 `LOCAL_LLM_BASE_URL`에 반영했다

**매일 개발 시작 전 (2~3주차 동안 습관처럼)**:
- [ ] PC가 켜져 있고 인터넷에 연결돼 있다
- [ ] `http://localhost:11434` 정상 응답 확인
- [ ] (선택) 팀 채팅방에 "서버 켜짐" 정도만 짧게 공유해두면 B가 매번 직접 확인할 필요가 없다

**데모·투표 기간 시작 전날 (9/20 저녁, 매우 중요)**:
- [ ] PC 전원 케이블 연결 확인, 절전 설정 재확인
- [ ] Ollama, cloudflared 둘 다 서비스로 등록되어 재부팅해도 자동으로 켜지는지 실제로 한 번 재부팅해서 테스트
- [ ] 터널을 일부러 잠깐 꺼서 웹앱이 정말 Gemini로 자동 전환되는지 확인(10절 폴백 테스트) — 이건 A 혼자 판단하지 말고 B와 함께 확인한다
- [ ] 데모 당일 PC 근처에 있을 수 없는 시간대가 있다면 미리 팀에 공유해둔다

이 체크리스트를 통과하면, A는 서버 운영 경험이 없어도 이 프로젝트가 요구하는 서버 운영을 충분히 해낸 것이다.
