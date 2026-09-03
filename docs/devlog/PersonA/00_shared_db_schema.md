# 공용 — DB 스키마 devlog

체크리스트: `docs/checklists/00_shared/02_database_schema.md`
날짜: 2026-09-01
커밋: `acec53a`, `7951fb8`

---

## ORM 모델 설계

SQLAlchemy 2.x의 Mapped 타입 어노테이션 스타일을 사용했다. `Mapped[str]`, `Mapped[uuid.UUID | None]` 식으로 Python 타입으로 nullable 여부가 드러나기 때문에, 런타임 오류가 아닌 정적 분석 단계에서 타입 실수를 잡을 수 있다.

**CHECK 제약 구현**: `__table_args__`에 `CheckConstraint`를 튜플로 넣었다. 예를 들어 `confirmed_facts`의 `source_type`은 다음처럼 선언했다:

```python
__table_args__ = (
    CheckConstraint(
        "source_type IN ('user_confirmed', 'user_edited', 'record_cited')",
        name='ck_confirmed_facts_source_type'
    ),
)
```

이렇게 하면 DB 레벨에서 허용되지 않은 `source_type` 삽입을 막아준다. 정직성 가드레일이 애플리케이션 코드 실수로 우회되는 것을 방지하는 마지막 안전장치다.

**CASCADE 설정**: 세션을 삭제하면 하위 데이터가 전부 사라지도록 모든 FK에 `ondelete="CASCADE"`를 걸었다. 단, `sessions.current_category_id`와 `confirmed_facts.source_record_chunk_id`처럼 참조 대상이 없어도 row 자체는 유지돼야 하는 경우는 `ondelete="SET NULL"`로 처리했다.

**pgvector 컬럼**: `record_chunks.embedding`은 `pgvector.sqlalchemy.Vector(1024)`로 선언했다. 차원은 bge-m3 모델의 출력 크기인 1024로 고정했다. 나중에 임베딩 모델이 바뀌면 차원이 달라져 기존 인덱스와 호환이 안 되므로, `embedding_model` 컬럼에 어떤 모델로 생성한 벡터인지 항상 기록하도록 설계했다.

## 순환 FK 해결

`sessions`와 `activity_categories`는 서로를 FK로 참조한다 (`sessions.current_category_id → activity_categories.id`, `activity_categories.session_id → sessions.id`). Alembic autogenerate가 이를 감지하고 경고를 냈으며, 생성된 마이그레이션을 그대로 실행하면 "테이블이 아직 없는데 FK를 거는" 오류가 난다.

해결 방법: `activity_categories`를 `session_id` FK 없이 먼저 생성하고, `sessions` 생성 후에 `op.create_foreign_key()`로 FK를 별도로 추가했다:

```python
# 1단계: activity_categories를 FK 없이 생성
op.create_table('activity_categories', ...)  # session_id FK 제외

# 2단계: sessions 생성 (activity_categories FK 포함)
op.create_table('sessions', ...,
    sa.ForeignKeyConstraint(['current_category_id'], ['activity_categories.id'], ...),
)

# 3단계: 뒤늦게 activity_categories → sessions FK 추가
op.create_foreign_key(
    'fk_activity_categories_session_id',
    'activity_categories', 'sessions',
    ['session_id'], ['id'], ondelete='CASCADE',
)
```

## Alembic + 환경변수 URL 인코딩 문제

`.env`에 저장된 `DATABASE_URL`은 asyncpg 드라이버(`postgresql+asyncpg://`)를 사용하는데, Alembic은 동기 드라이버가 필요하다. `env.py`에서 URL을 `psycopg2`로 변환했다:

```python
_sync_url = os.environ.get("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
```

초기에는 `config.set_main_option("sqlalchemy.url", _sync_url)`을 호출했는데, 비밀번호에 `%40`(`@`), `%24`(`$`) 같은 URL 인코딩 문자가 포함돼 있어 configparser가 `%`를 보간 문법으로 해석해 `ValueError`가 발생했다. 이를 해결하기 위해 `set_main_option` 호출을 제거하고 `create_engine(_sync_url)`을 직접 호출하는 방식으로 바꿨다.

## Supabase 연결 URL

Supabase의 Direct connection URL(`db.[ref].supabase.co:5432`)은 신규 프로젝트에서 DNS에 등록되지 않아 접속 불가였다. Session Pooler URL(`aws-0-ap-northeast-2.pooler.supabase.com:5432`)을 사용해야 한다. 비밀번호에 특수문자가 있으면 URL 인코딩이 필수다 (`@` → `%40`, `$` → `%24`).

## ivfflat 인덱스

pgvector의 코사인 유사도 검색을 위해 마이그레이션에 직접 SQL을 삽입했다:

```python
op.execute(
    'CREATE INDEX IF NOT EXISTS ix_record_chunks_embedding '
    'ON record_chunks USING ivfflat (embedding vector_cosine_ops)'
)
```

autogenerate는 이 인덱스를 자동으로 생성하지 못하므로 수동으로 추가했다. `IF NOT EXISTS`를 붙여 재실행 시 오류를 방지했다.

## 트러블슈팅 요약

| 증상 | 원인 | 해결 |
|---|---|---|
| `UnicodeDecodeError: cp949` | `alembic.ini`에 한글 주석 → configparser가 시스템 로케일(cp949)로 읽음 | 주석을 영문으로 교체 |
| `DuplicateOptionError: sqlalchemy.url` | `alembic init`이 기본 생성한 줄과 내가 추가한 줄이 중복 | 원본 기본값 줄 제거 |
| `ValueError: invalid interpolation syntax` | URL의 `%40` 등이 configparser 보간 문법(`%(key)s`)과 충돌 | `set_main_option` 제거, `create_engine` 직접 호출 |
| `Name or service not known` | Direct connection URL이 DNS 미등록 | Session Pooler URL로 교체 |
