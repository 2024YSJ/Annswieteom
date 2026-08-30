# 공용 체크리스트 2 — 데이터베이스 스키마

근거: 명세서 6절
담당: 공용 (B가 주도하되 A도 `record_chunks`, `confirmed_facts` 구조를 이해하고 있어야 함)
선행 조건: [01_repo_and_env_setup.md](01_repo_and_env_setup.md) 완료 (Supabase 프로젝트 + pgvector 확장)
브랜치: `feature/db-schema` (`dev`에서 분기, 완료 후 `dev`로 PR — 자세한 전략은 [01_repo_and_env_setup.md](01_repo_and_env_setup.md) 4절 참고)

> 이 스키마가 확정돼야 8절 상태머신(B), 10~13절 AI/기록물 파이프라인(A) 양쪽 모두 구현을 시작할 수 있다. **먼저 끝내야 하는 작업이다.**

## 1. SQLAlchemy ORM 모델 작성 (`backend/app/models/`)

- [ ] `User` — `users` 테이블 (6-1): id(UUID PK), email(UNIQUE), password_hash, nickname, created_at, updated_at, deleted_at(nullable)
- [ ] `RefreshToken` — `refresh_tokens` (6-2): id, user_id(FK), token_hash, expires_at, revoked_at, created_at
- [ ] `Session` — `sessions` (6-3): id, user_id(FK), status(default 'PERIOD_INPUT'), current_category_id(FK nullable), created_at, updated_at
- [ ] `GapPeriod` — `gap_periods` (6-4): id, session_id(FK UNIQUE), start_date, end_date, CHECK(end_date >= start_date)
- [ ] `ActivityCategory` — `activity_categories` (6-5): id, session_id(FK), category_type(CHECK IN 8종), custom_label(nullable), order_index, status(default 'PENDING')
- [ ] `ConfirmedFact` — `confirmed_facts` (6-6, **정직성 가드레일 핵심 테이블**): id, category_id(FK), fact_type(CHECK IN frequency/task/achievement), content, source_type(CHECK IN user_confirmed/user_edited/record_cited), source_record_chunk_id(FK nullable), ai_draft_text(nullable), created_at
- [ ] `Record` — `records` (6-7): id, session_id(FK), record_type(CHECK), source_url, platform(CHECK), storage_path, raw_text, parse_status(default PENDING), parse_error, created_at
- [ ] `RecordChunk` — `record_chunks` (6-8): id, record_id(FK), chunk_text, chunk_index, published_at, embedding(VECTOR — 차원은 11절 임베딩 모델 확정 후), embedding_model, created_at. ⚠️ `VECTOR`는 컬럼 하나에 고정 차원만 담을 수 있어, 로컬(`bge-m3`)·클라우드(Gemini) 임베딩 폴백 시 차원이 다르면 문제가 생길 수 있다 — 확정 전 [person_A_infra_ai/03_embedding_pipeline.md](../person_A_infra_ai/03_embedding_pipeline.md) 5번 항목을 A와 함께 확인할 것
- [ ] `GeneratedDocument` — `generated_documents` (6-9): id, session_id(FK), tone(default neutral), version(default 1), status(default DRAFT), created_at
- [ ] `GeneratedSentence` — `generated_sentences` (6-10): id, document_id(FK), category_id(FK), order_index, text, evidence_fact_ids(JSONB default []), consistency_check_passed(default true)
- [ ] 모든 FK에 `ON DELETE CASCADE` 설정 (sessions 삭제 시 하위 전체 연쇄 삭제, 6-11)
- [ ] `record_chunks.embedding`에 pgvector 인덱스 추가: `CREATE INDEX ON record_chunks USING ivfflat (embedding vector_cosine_ops);`

## 2. Pydantic 스키마 작성 (`backend/app/schemas/`)

- [ ] 각 ORM 모델에 대응하는 Create/Read/Update 스키마 초안 작성 (9절 API 요청/응답 형태에 맞춰 세부 조정은 각 API 구현 시점에)

## 3. Alembic 마이그레이션

- [ ] `alembic init migrations` (backend/app/db/migrations 위치로 조정)
- [ ] `alembic.ini` 및 `env.py`에 `DATABASE_URL` 연결 (환경변수에서 로드하도록)
- [ ] 모델 작성 후 `alembic revision --autogenerate -m "init schema"`
- [ ] 생성된 마이그레이션 파일을 직접 열어 CHECK 제약조건·CASCADE·인덱스가 누락 없이 반영됐는지 확인 (autogenerate가 CHECK 제약을 못 잡는 경우가 흔함 — 수동 보완 필요)
- [ ] `alembic upgrade head`로 Supabase DB에 적용

## 검증 기준

- [ ] Supabase 대시보드의 Table Editor에서 10개 테이블(6-1~6-10)이 모두 보인다
- [ ] `record_chunks` 테이블에 `embedding` 컬럼이 vector 타입으로 보이고 ivfflat 인덱스가 생성돼 있다
- [ ] 아무 세션 하나를 만들고 하위 데이터(가상의 category, fact)를 넣은 뒤 그 세션을 지웠을 때 하위 row가 모두 같이 사라진다(CASCADE 확인)
- [ ] A, B 둘 다 로컬에서 같은 `DATABASE_URL`로 접속해 동일한 스키마를 본다
