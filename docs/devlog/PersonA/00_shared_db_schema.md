# 공용 — DB 스키마 devlog

체크리스트: `docs/checklists/00_shared/02_database_schema.md`
브랜치: `feature/db-schema` → `dev` PR 대기 중
날짜: 2026-09-01
상태: 코드 완료 / Supabase 적용 완료 / PR 미머지

## 완료 항목

### SQLAlchemy ORM 모델 (10개 테이블)

- [x] `User` — email UNIQUE, bcrypt password_hash, soft delete (deleted_at)
- [x] `RefreshToken` — token_hash UNIQUE, revoked_at
- [x] `Session` — status CHECK 8종, current_category_id FK (nullable)
- [x] `GapPeriod` — session_id UNIQUE, end_date >= start_date CHECK
- [x] `ActivityCategory` — category_type CHECK 8종, status CHECK 3종
- [x] `ConfirmedFact` — **정직성 가드레일 핵심**: fact_type / source_type CHECK 제약
- [x] `Record` — record_type / platform / parse_status CHECK 제약
- [x] `RecordChunk` — `embedding VECTOR(1024)` (pgvector), embedding_model 컬럼
- [x] `GeneratedDocument` — tone / status CHECK 제약
- [x] `GeneratedSentence` — evidence_fact_ids JSONB, consistency_check_passed
- [x] 모든 FK `ON DELETE CASCADE` (또는 SET NULL) 설정

### Pydantic 스키마

- [x] `schemas/user.py` — UserCreate, UserRead, TokenPair
- [x] `schemas/session.py` — SessionCreate, GapPeriodSet, CategorySelect, InterviewConfirm
- [x] `schemas/document.py` — GenerateRequest, DocumentRead, SentenceRead, SentenceUpdate

### Alembic

- [x] `alembic init app/db/migrations` 실행
- [x] `env.py` — `DATABASE_URL` 환경변수 자동 로드, 모든 모델 autogenerate 감지
- [x] `alembic.ini` 중복 `sqlalchemy.url` 제거, ASCII 전용 주석으로 수정
- [x] `alembic revision --autogenerate -m "init schema"` 생성 후 수동 보완
- [x] `alembic upgrade head` → Supabase 적용 완료 (`cf08f92b1e47 head`)

### Supabase 연결

- [x] 프로젝트 생성 (Region: Northeast Asia Seoul)
- [x] pgvector extension 활성화
- [x] Session Pooler URL 사용 (Direct connection URL은 DNS 미등록 상태)

## 트러블슈팅

| 문제 | 원인 | 해결 |
|---|---|---|
| `UnicodeDecodeError: cp949` | `alembic.ini`에 한글 주석 → configparser가 locale 인코딩으로 읽음 | 주석을 영문으로 교체 |
| `DuplicateOptionError: sqlalchemy.url` | `alembic init`이 생성한 기본값 + 내가 추가한 값 중복 | 원본 줄 제거 |
| `ValueError: invalid interpolation syntax` | `%40`, `%24` 등 URL 인코딩 문자가 configparser 보간 문법과 충돌 | `env.py`에서 `set_main_option` 제거, `create_engine` 직접 호출로 변경 |
| `Name or service not known` | Direct connection URL (`db.xxx.supabase.co`) DNS 미등록 | Session Pooler URL(`aws-0-ap-northeast-2.pooler.supabase.com`)로 교체 |
| `sessions ↔ activity_categories` 순환 FK 경고 | 두 테이블이 서로 FK 참조 | `activity_categories`를 FK 없이 먼저 생성 후 `op.create_foreign_key`로 후속 추가 |
| pgvector import 누락 | autogenerate가 `pgvector.sqlalchemy.vector.VECTOR` 경로로 생성했으나 import 없음 | 마이그레이션 파일 상단에 `import pgvector.sqlalchemy` 추가 |

## DATABASE_URL 형식 (최종)

```
# asyncpg (FastAPI 런타임용)
postgresql+asyncpg://postgres.[project-ref]:[pw]@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres

# psycopg2 (Alembic 마이그레이션용 — env.py가 자동 변환)
postgresql+psycopg2://postgres.[project-ref]:[pw]@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres
```

비밀번호에 `@`, `$` 등 특수문자가 있으면 URL 인코딩 필수 (`@` → `%40`, `$` → `%24`).

## 커밋

- `acec53a` feat: add DB schema (ORM models, Alembic, Pydantic schemas)
- `7951fb8` fix: fix migration file for circular FK and pgvector import

## 남은 작업

- [ ] GitHub PR `feature/db-schema` → `dev` 머지 (B가 auth 시작하려면 선행 필요)
- [ ] Supabase 대시보드 Table Editor에서 10개 테이블 직접 확인
- [ ] CASCADE 테스트 (세션 삭제 시 하위 row 연쇄 삭제 확인)
