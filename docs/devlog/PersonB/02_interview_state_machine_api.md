# B-2. 인터뷰 상태머신 및 세션/인터뷰 API devlog

체크리스트: `docs/checklists/person_B_frontend_backend/02_interview_state_machine_api.md`
날짜: 2026-09-02
브랜치: `feature/interview-flow` (`feature/auth` 위에서 분기)

---

## 완료 항목

- 상태 전이 로직 (`app/services/interview_orchestrator.py`): 8-2절 전이표를 딕셔너리 3개(`SIMPLE_TRANSITIONS`, `NEXT_STEP_AFTER_DRAFT`, `NEXT_STEP_AFTER_CONFIRM`)와 `resolve_after_achievement_confirm()`로 그대로 옮김. HTTP와 무관한 순수 함수라 FastAPI 없이도 단위 테스트 가능.
- `POST /sessions`, `GET /sessions/{id}`, `DELETE /sessions/{id}` (`app/api/sessions.py`)
- `POST /sessions/{id}/period`, `/categories`, `/records/skip`, `GET .../interview/next`, `POST .../interview/confirm` (`app/api/interview.py`)
- `pending_draft` 컬럼과 그걸 쓰는 초안 임시 보관/조회 로직
- source_type을 서버가 도출하는 로직 (클라이언트가 지정 불가)
- 테스트 50개 추가 (`tests/services/test_interview_orchestrator.py` 8개, `tests/api/test_interview.py` 12개) — 기존 25개 포함 총 42개 전체 통과

## 핵심 결정 사항과 이유

**`Session.status`의 CHECK 제약을 통째로 교정**: 구현을 시작하면서 `app/models/session.py`를 열어보니 `SESSION_STATUSES`가 이 체크리스트의 상태값(`FREQ_DRAFT` 등)과 하나도 안 맞고 완전히 다른 옛날 이름 세트(`INTERVIEW_FREQ` 등)로 들어있었다. DB 스키마 마이그레이션(`cf08f92b1e47`)에도 이미 이 잘못된 값으로 CHECK 제약이 박혀 있었다 — B-1까지는 `sessions.status`를 실제로 바꾸는 코드가 없어서 발견이 안 됐던 것. 8-2절 값으로 교정하고 새 마이그레이션(`90edf5d28f6a`)을 추가했다. **아직 실제 Supabase DB에는 적용 안 함** — 체크리스트 "남은 작업" 참고.

**초안 임시 저장을 인메모리 캐시가 아니라 DB 컬럼(`pending_draft` JSON)으로**: 체크리스트가 두 옵션(인메모리 캐시 / DB 컬럼)을 다 허용했는데, Railway 배포 시 워커 프로세스가 여러 개일 수 있다는 이유로 DB 컬럼을 택했다. `GET interview/next`와 `POST interview/confirm`이 같은 워커에서 처리된다는 보장이 없으면 인메모리 캐시는 조용히 깨진다. 컬럼 타입은 `pgvector.JSONB`가 아니라 SQLAlchemy의 제네릭 `JSON`을 썼다 — SQLite(테스트용)와 Postgres 양쪽에서 다 컴파일되는 타입이 필요했고, 이 컬럼은 구조적으로 쿼리할 일이 없어 JSONB의 인덱싱 이점이 필요 없었다.

**`interview/confirm`의 `source_type`을 요청 바디에서 완전히 제거**: 원래 `schemas/session.py`에 있던 `InterviewConfirm` 스키마는 `fact_type/content/source_type/ai_draft_text/source_record_chunk_id`를 클라이언트가 그대로 보내는 형태였는데, 이러면 클라이언트가 아무 텍스트나 `"source_type": "record_cited"`라고 주장해도 서버가 그대로 믿고 저장하게 된다 — 정직성 가드레일이 API 계약 수준에서 뚫리는 구멍이었다. 명세서 9-3절이 실제로 정의하는 요청 바디(`{step, final_text, was_edited}`)로 스키마를 다시 쓰고, `source_type`은 서버가 `pending_draft`에 캐시해둔 `based_on`/`was_edited`로부터만 도출하도록 바꿨다.

**`search_relevant_chunks`를 `Depends()`로 감싸기**: A의 `search_relevant_chunks()`는 `get_db` 의존성을 안 쓰고 함수 내부에서 직접 `AsyncSessionLocal()`을 새로 연다. 그대로 두면 테스트에서 `get_db`를 오버라이드해도 이 함수는 여전히 진짜 `DATABASE_URL`(설정 파일에 있는 실 Supabase 커넥션)에 접속을 시도하게 된다. `app/services/record_pipeline/search.py`에 `get_chunk_search()` DI 훅을 추가하고 라우터가 그걸 통해서만 호출하도록 해서, 테스트에서는 빈 리스트를 반환하는 가짜로 바꿔치기했다.

**`feature/auth` 위에서 브랜치**: 체크리스트엔 `dev`에서 분기하라고 되어 있지만, `feature/auth`(B-1)가 아직 `dev`에 머지되지 않은 상태라 `get_owned_session`, `User` 모델 등 B-1 코드가 `dev`엔 없다. `dev`에서 새로 시작하면 이 코드를 다시 만들어야 해서, 대신 `feature/auth` 위에 `feature/interview-flow`를 얹었다. `feature/auth`가 먼저 머지되면 이 브랜치도 그에 맞춰 정리해야 한다.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| 테스트 중 `ModuleNotFoundError: trafilatura` / `bs4` / `jinja2` | `backend/venv`의 Python 3.14가 최신이라 이전에 설치 안 해뒀던 패키지들이 `app/api/__init__.py` → `app/api/sessions.py` → A의 `record_pipeline`/`llm` 모듈 임포트 체인을 타고 새로 필요해짐. [[project-b1-auth]]에서 겪은 것과 같은 종류의 문제(패키지가 없는 게 아니라 이 세션의 테스트 venv에 아직 안 깔려 있었을 뿐) | `pip install trafilatura beautifulsoup4 jinja2 google-genai` (requirements.txt엔 이미 다 핀 되어 있었음, venv에만 안 깔려 있었음) |
| `DELETE /sessions/{id}` 테스트가 `sqlite3.OperationalError: no such table: records` | `Session.records`/`Session.documents` 관계가 `cascade="all, delete-orphan"`이라, 세션을 지우면 SQLAlchemy가 실제로 지울 게 있는지 확인하려고 두 관계를 lazy-load한다 — 테스트 DB에 `records`/`generated_documents` 테이블 자체를 안 만들어놨어서 터짐 | `tests/api/conftest.py`의 `session_client` 픽스처가 만드는 테이블 목록에 `Record.__table__`, `GeneratedDocument.__table__`을 추가(둘 다 pgvector/JSONB 없는 평범한 테이블이라 SQLite에서 문제없음, 그냥 빈 테이블로 존재하기만 하면 됨) |
| `record_cited` 케이스 테스트에서 읽어온 `source_record_chunk_id`가 `AttributeError: 'float' object has no attribute 'replace'`로 깨짐 | 테스트에서 임의로 만든 chunk_id가 `"11111111-1111-1111-1111-111111111111"`(숫자 1과 대시만 있음)였는데, `postgresql.UUID` DDL 타입 이름이 SQLite의 타입 어피니티 키워드(INT/CHAR/TEXT/BLOB/REAL 등) 중 아무것도 안 맞아서 기본값인 NUMERIC 어피니티로 떨어지고, SQLite가 이 문자열을 통째로 숫자로 오인해서 REAL로 저장해버림. 실제 Postgres에서는 UUID 네이티브 타입이라 이 문제 자체가 없다 — 순수 테스트 데이터 선택의 문제 | 테스트의 chunk_id를 진짜 `uuid.uuid4()`(영문자 포함)로 바꿔서 숫자로 오인될 여지를 없앰 |

## 테스트 전략

- `tests/services/test_interview_orchestrator.py`: FastAPI/DB 없이 상태 전이 함수만 단위 테스트 (8개)
- `tests/api/test_interview.py`: `conftest.py`의 `session_client` 픽스처 — in-memory SQLite에 세션 관련 테이블만 생성하고, `get_llm_provider`/`get_chunk_search`를 `FakeLLMProvider`/빈 리스트 반환 함수로 오버라이드해서 실제 Ollama/Gemini/pgvector 없이 전체 API 플로우(회원가입→세션 생성→기간→카테고리→기록물 스킵→인터뷰 3라운드→다음 카테고리 또는 RESULT_GENERATE)를 검증 (12개)

## 남은 작업

- **실제 Supabase DB에 마이그레이션 `90edf5d28f6a` 적용** (`alembic upgrade head`) — 지금 실제 DB의 `sessions.status` CHECK 제약은 옛날 값 그대로라, 이 상태에서 실제 DB로 상태머신을 돌리면 CHECK 위반으로 깨진다. 사용자 확인 후 진행 예정.
- 실제 LLM(Ollama/Gemini)과 실제 DB로 전체 플로우 재검증 (지금까지는 `FakeLLMProvider` + SQLite로만 확인)
- `feature/auth`가 `dev`에 머지되면 `feature/interview-flow`도 그 기준으로 정리
- 다음은 [03_records_feature.md](../../checklists/person_B_frontend_backend/03_records_feature.md) — `POST /sessions/{id}/records`를 구현할 때 상태 전이는 이미 여기서 검토 완료(전이 없음, `RECORD_UPLOAD` 유지)
