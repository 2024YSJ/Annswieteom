# 아키텍처 문서

이 문서는 백엔드/프론트엔드 코드 구조를 파일·함수 단위로 정리한다. 명세는 [docs/specs/annswieteom_detailed_spec.md](specs/annswieteom_detailed_spec.md), 마일스톤 진행 상황은 [docs/checklists/](checklists/), 작업 기록은 [docs/devlog/](devlog/)를 참고. 이 문서는 "지금 구조가 어떻게 생겼고 새 코드를 어디에 둬야 하는가"에 집중한다.

## 1. 개요

- **프론트엔드**: Next.js 14+ (TypeScript, App Router) — `frontend/`
- **백엔드**: FastAPI (Python 3.11+) — `backend/`
- **DB**: PostgreSQL + pgvector (Supabase)
- **LLM**: 로컬 Ollama 전용 — **폴백 없음**(2026-09-09 Gemini 제거). 추론도 임베딩도 이 서버 하나에 달려 있고, 닿지 않으면 AI 경로는 전부 503 `llm_unavailable`로 끝난다
- **핵심 제약(정직성 가드레일)**: 생성된 모든 문장은 `confirmed_facts` 테이블의 행을 최소 1개 이상 인용해야 한다. 이 제약은 특정 함수 하나가 아니라 여러 계층에 걸쳐 강제된다 — 자세한 내용은 6절.

백엔드는 `api/ → schemas/ + services/ → models/ → db` 방향으로 의존한다:

```mermaid
graph TD
  API["api/ — FastAPI 라우터<br/>(HTTP 계약)"]
  SCHEMAS["schemas/ — Pydantic 요청/응답 모델"]
  SERVICES["services/ — 비즈니스 로직<br/>(llm/, embedding/, record_pipeline/)"]
  MODELS["models/ — SQLAlchemy ORM"]
  CORE["core/ — config, security, deps"]
  DB[("PostgreSQL (Supabase)")]

  API --> SCHEMAS
  API --> SERVICES
  API --> CORE
  SERVICES --> MODELS
  API --> MODELS
  MODELS --> DB
```

라우터는 스키마로 입출력을, 서비스로 로직을, models로 영속성을 위임한다. 서비스가 라우터를 import하는 방향은 없다(있었다면 그게 2-1/2-2에서 고친 문제였다 — 7절 참고).

## 2. DB 모델 클래스 다이어그램

```mermaid
classDiagram
  class User {
    +UUID id
    +string? email
    +string? password_hash
    +string nickname
    +bool is_guest
    +datetime? deleted_at
  }
  class RefreshToken {
    +UUID id
    +UUID user_id
    +string token_hash
    +datetime expires_at
    +datetime? revoked_at
  }
  class Session {
    +UUID id
    +UUID user_id
    +string? title
    +string status
    +UUID? current_category_id
    +json? pending_draft
  }
  class GapPeriod {
    +UUID id
    +UUID session_id
    +date start_date
    +date end_date
  }
  class ActivityCategory {
    +UUID id
    +UUID session_id
    +string category_type
    +string? custom_label
    +int order_index
    +string status
    +label() string
  }
  class ConfirmedFact {
    +UUID id
    +UUID category_id
    +string fact_type
    +string content
    +string source_type
    +UUID? source_record_chunk_id
    +string? ai_draft_text
  }
  class Record {
    +UUID id
    +UUID session_id
    +string record_type
    +string? source_url
    +string platform
    +string? storage_path
    +string? raw_text
    +string parse_status
    +string? parse_error
  }
  class RecordChunk {
    +UUID id
    +UUID record_id
    +string chunk_text
    +int chunk_index
    +date? published_at
    +vector(1024)? embedding
    +string? embedding_model
  }
  class GeneratedDocument {
    +UUID id
    +UUID session_id
    +string tone
    +int version
    +string status
  }
  class GeneratedSentence {
    +UUID id
    +UUID document_id
    +UUID category_id
    +int order_index
    +string text
    +json evidence_fact_ids
    +bool consistency_check_passed
  }

  User "1" --> "*" Session : cascade delete
  User "1" --> "*" RefreshToken : cascade delete
  Session "1" --> "0..1" GapPeriod : cascade delete
  Session "1" --> "*" ActivityCategory : cascade delete
  Session "1" --> "*" Record : cascade delete
  Session "1" --> "*" GeneratedDocument : cascade delete
  ActivityCategory "1" --> "*" ConfirmedFact : cascade delete
  ActivityCategory "1" --> "*" GeneratedSentence : cascade delete
  Record "1" --> "*" RecordChunk : cascade delete
  ConfirmedFact "0..1" --> "1" RecordChunk : 근거 인용 (SET NULL)
  GeneratedDocument "1" --> "*" GeneratedSentence : cascade delete
```

모든 상태값(`status`, `record_type`, `source_type` 등)은 `CheckConstraint`로 DB 레벨에서도 강제된다 — 각 모델 파일 상단의 튜플 상수(`SESSION_STATUSES`, `CATEGORY_TYPES`, `FACT_TYPES`, `SOURCE_TYPES` 등)가 그 값 목록의 단일 출처다.

## 3. 백엔드 파일별 상세

### `api/` — 라우터. 소유권/인증 방식이 세 갈래다(`core/deps.py`).

- **세션 스코프**(`sessions`/`interview`/`records`/`document`/`job_search`/`coverage`): `Depends(get_owned_session)`으로 소유권 검증을 공유한다.
- **계정 스코프**(`auth`의 일부, `profile`): `Depends(get_current_user)`.
- **익명 허용**(`feed`): `Depends(get_current_user_optional)` — 메인 화면 피드는 로그아웃 방문자에게도 떠야 한다. 단 `feed/jobs/recommended`만 `get_current_user`.

| 파일 | 책임 | 주요 엔드포인트 |
|---|---|---|
| `auth.py` | 회원가입/로그인/게스트/토큰 재발급/로그아웃 | `POST /register`, `/login`, `/guest`, `/refresh`, `/logout`, `GET /me` |
| `sessions.py` | 세션 CRUD (생성/목록/상세/이름변경/삭제) | `POST /sessions`, `GET /sessions`, `GET /sessions/{id}`, `PATCH /sessions/{id}`, `DELETE /sessions/{id}` |
| `interview.py` | 상태머신 진행: 기간→카테고리→기록물스킵→인터뷰(초안/확인) | `POST .../period`, `.../period/extract`, `.../categories`, `.../categories/extract`, `.../records/skip`, `GET .../interview/next`, `POST .../interview/confirm` |
| `records.py` | 기록물(블로그 URL/텍스트/이미지) 업로드·조회·삭제, 백그라운드 파싱 트리거 | `POST .../records`, `.../records/text`, `.../records/upload`, `GET/.DELETE .../records/{id}` |
| `feed.py` | 메인 화면 피드 — 청년 지원 정책(최신 등록순)/공고(최신순)/맞춤 공고(코사인) + 소스 진단 | `GET /feed/policies`, `GET /feed/jobs`, `GET /feed/jobs/recommended`, `GET /feed/sources` |
| `document.py` | 문서 생성/재생성/문장 수정·재생성/확정/내보내기 | `POST .../generate`, `GET .../document`, `POST .../document/regenerate`, `PATCH .../document/sentences/{id}`, `POST .../document/sentences/{id}/regenerate`, `.../document/finalize`, `GET .../export` |

### `schemas/` — Pydantic 요청/응답 모델. `api/X.py` ↔ `schemas/X.py` 1:1 대응.

| 파일 | 대응 라우터 | 주요 클래스 |
|---|---|---|
| `user.py` | `auth.py` | `UserCreate`, `LoginRequest`, `UserRead`, `TokenPair`, `RegisterResponse` |
| `session.py` | `sessions.py` | `SessionCreate`, `SessionRead`(`title` 포함), `SessionRename`, `SessionContextRead`, `ActivityCategoryRead`, `ConfirmedFactRead`, `RecordChunkExcerptRead` |
| `interview.py` | `interview.py` | `GapPeriodSet/Read`, `PeriodExtractRequest/Read`, `CategoryInput`, `CategorySelect`, `CategoryExtractRequest/Read`, `StatusRead`, `RecordsSkipRead`, `BasedOnRead`, `InterviewNextRead`, `InterviewConfirm`, `InterviewConfirmRead` |
| `record.py` | `records.py` | `BlogRecordCreate`, `TextRecordCreate`, `RecordRead` |
| `feed.py` | `feed.py` | `FeedItemRead`, `FeedRead` |
| `document.py` | `document.py` | `GenerateRequest`, `CitationRead`, `EvidenceRead`, `SentenceRead`, `SentenceUpdate`, `DocumentRead` |

### `models/` — SQLAlchemy ORM (2절 다이어그램 참고)

| 파일 | 테이블 | 비고 |
|---|---|---|
| `user.py` | `users` | `is_guest`, `deleted_at`(소프트 삭제) |
| `refresh_token.py` | `refresh_tokens` | `token_hash`만 저장(SHA-256), raw 토큰은 저장 안 함 |
| `session.py` | `sessions` | `SESSION_STATUSES` 8-2절 상태머신표, `pending_draft`(JSON, 임시 초안 캐시) |
| `gap_period.py` | `gap_periods` | 세션당 1개(unique FK) |
| `activity_category.py` | `activity_categories` | `CATEGORY_TYPES`, `CATEGORY_STATUSES`, `label` property(`custom_label or category_type`) |
| `confirmed_fact.py` | `confirmed_facts` | **정직성 가드레일 핵심 테이블** — `SOURCE_TYPES`가 `user_confirmed`/`user_edited`/`record_cited`로 제한됨 |
| `record.py` | `records` | `RECORD_TYPES`, `PLATFORMS`, `PARSE_STATUSES` |
| `record_chunk.py` | `record_chunks` | `embedding: Vector(1024)` (pgvector, bge-m3 차원) |
| `generated_document.py` | `generated_documents` | `TONES`, `DOC_STATUSES` |
| `feed_item.py` | `feed_items` | 외부 API 캐시(전 사용자 공용). `FEED_SOURCES`/`FEED_KINDS`/`FEED_KIND_BY_CATEGORY` |
| `feed_item_embedding.py` | `feed_item_embeddings` | 항목 벡터(1:1 곁테이블). **본체와 분리한 이유는 6절 참고** |
| `user_profile_embedding.py` | `user_profile_embeddings` | 사용자 프로필 벡터(우리 소유의 파생 캐시) |
| `feed_refresh_state.py` | `feed_refresh_states` | 소스별 갱신 상태 + 시간 기반 동시 갱신 락 |
| `generated_sentence.py` | `generated_sentences` | `evidence_fact_ids`(JSON 배열), `consistency_check_passed` |

### `services/` — 비즈니스 로직

| 파일 | 책임 | 핵심 함수/클래스 |
|---|---|---|
| `interview_orchestrator.py` | 상태머신 전이 규칙(순수 함수, DB 접근 없음) | `require_simple_transition`, `require_status`, `require_draft_step`, `require_confirm_step`, `resolve_after_achievement_confirm`, `next_category` |
| `document_generator.py` | 카테고리별 LLM 호출 → 문장 생성 → 일관성 검사 → 저장 | `generate_full_document()`, `regenerate_sentence()` |
| `consistency_check.py` | 생성 문장과 인용 근거 간 코사인 유사도로 사후 검증(정직성 가드레일 마지막 방어선) | `check_sentence_consistency()`, `max_cosine_similarity()` |
| `feed/sources/{base,worknet_source,youthcenter_source}.py` | 피드 소스 어댑터. 워크넷은 `job_info_client`를 재사용만 한다 | `FeedItemData`, `WorknetFeedSource`, `YouthCenterFeedSource` |
| `feed/sources/__init__.py` | 소스 레지스트리 — 키 없는 소스는 조용히 스킵 | `configured_sources()`, `source_keys_for()` |
| `feed/dedup.py` | 안정 id 우선, 없으면 내용 해시 | `compute_dedup_key()`, `build_embed_text()` |
| `feed/ingest.py` | 백그라운드 수집(락/upsert/임베딩 backfill/정리) | `refresh_feed()`, `stale_source_keys()`, `get_feed_refresher()` |
| `feed/profile_adapter.py` | `interview_answers`를 읽는 **유일한 지점**(계약은 파일 상단) | `read_profile_signal()`, `refresh_profile_embedding()`, `get_profile_embedder()` |
| `feed/ranking.py` | 코사인 정렬, 실패 시 최신순 | `rank_feed_items()`, `get_feed_ranker()` |
| `storage.py` | Supabase Storage(비공개 버킷) 래퍼 | `SupabaseStorage`(upload/download/delete/create_signed_url), `get_storage()` |
| `llm/base.py` | LLM 프로바이더 계약 + 샘플링 모드 상수 | `LLMProvider`(Protocol), `InterviewContext`, `Suggestion`, `DraftDocument` 등 dataclass, `JobInfoQueryParams`, `LLMUnavailableError`, `TEMPERATURE_DETERMINISTIC`/`TEMPERATURE_CREATIVE` |
| `llm/local_ollama.py` | 로컬 Ollama 어댑터(유일한 프로바이더) | `LocalOllamaProvider`, `_NUM_CTX` |
| `llm/__init__.py` | DI 훅 | `get_llm_provider()` |
| `embedding/base.py` | 임베딩 프로바이더 계약 | `EmbeddingProvider`(Protocol) |
| `embedding/local_ollama_embedding.py` | bge-m3 임베딩 어댑터 | `LocalOllamaEmbedding` |
| `embedding/__init__.py` | DI 훅 | `get_embedding_provider()` |
| `record_pipeline/pipeline.py` | 기록물 파싱→청킹→임베딩 파이프라인(백그라운드 태스크) | `process_record()`, `process_image_record()` |
| `record_pipeline/parsers/{naver_blog,tistory,generic}.py` | 플랫폼별 본문 추출 | 각 `parse(url)` |
| `record_pipeline/platform_detector.py` | URL로 플랫폼 판별 | `detect_platform()` |
| `record_pipeline/chunker.py` | 텍스트 청크 분할 | `chunk_text()` |
| `record_pipeline/citation.py` | 근거 인용 정보(출처 URL/발행일) 조회 | `resolve_fact_citation()`, `get_fact_citation()`(DI 훅) |
| `record_pipeline/search.py` | 카테고리 라벨로 의미 검색 | `search_relevant_chunks()`, `get_chunk_search()`(DI 훅) |
| `job_pipeline/job_info_client.py` | 워크넷/고용24 6개 카테고리 조회 + 조건별 호출 분할·병합 | `JobInfoClient.search()`, `search_training_courses()`, `WorknetApiError`, `get_job_info_client()`(DI 훅) |
| `job_pipeline/regions.py` | 지역명 → 워크넷 지역 코드(실호출로 검증한 표) | `RegionFilter`, `resolve_region_filters()`, `KNOWN_REGION_NAMES` |

### `core/`

| 파일 | 책임 |
|---|---|
| `config.py` | `pydantic-settings` 기반 `Settings` — `.env`에서 전체 환경변수 로드 |
| `security.py` | 비밀번호 해싱(bcrypt), JWT 발급/검증, refresh 토큰 해싱 |
| `deps.py` | `get_current_user`, `get_current_user_optional`, `get_owned_session` — 모든 라우터가 공유하는 인증/소유권 의존성 |

## 4. 프론트엔드 구조

### 라우트 (`app/`)

| 경로 | 역할 |
|---|---|
| `app/page.tsx` | 랜딩 — 로그인/게스트 시작 |
| `app/login/page.tsx`, `app/register/page.tsx` | 인증 폼 |
| `app/sessions/layout.tsx` | 세션 사이드바(목록, 이름변경, 삭제) — 모든 `/sessions/*` 하위에 적용 |
| `app/sessions/[id]/page.tsx` | 세션 진행 화면 전체(기간→카테고리→기록물→인터뷰→결과가 한 화면에 채팅형으로 쌓임) |

### 컴포넌트 (`components/`, 13개, 평평한 구조 — 각자 책임이 이름에서 바로 드러나 하위 폴더 분리 근거가 아직 없음)

| 파일 | 책임 |
|---|---|
| `AuthHeader.tsx` | 상단 고정 로그인 상태 표시 |
| `ChatBubble.tsx` | 좌/우 말풍선 공용 프리미티브(라이트/다크 대응 CSS 변수 사용) |
| `ChatComposer.tsx` | 화면 유일의 입력창(순수 입력 캡처, API 호출 없음) |
| `LoadingNotice.tsx` | 로딩 4초 초과 시 콜드스타트 안내 문구 추가 |
| `PeriodSection.tsx` | 공백기 기간 자유 텍스트 입력→AI 파싱→확인 |
| `CategorySection.tsx` | 활동 자유 텍스트→AI 카테고리 추출→확인 |
| `RecordsSection.tsx` | 텍스트/블로그 URL/이미지 기록물 등록 |
| `RecordStatusRow.tsx` | 기록물 파싱 상태 폴링 표시 |
| `InterviewSection.tsx` | 인터뷰 draft/confirm 상태머신과 API 연동 |
| `InterviewChatThread.tsx` | 카테고리별 확인된 사실 + 진행 중 초안 렌더링, 근거 배지 표시 |
| `ResultSection.tsx` | 문서 생성/톤 변경/문장 수정·재생성/확정/내보내기 |
| `EvidenceTag.tsx` | 문장별 근거 태그(클릭 시 출처 상세) |
| `TypingDots.tsx` | 채팅 대기 공용 말줄임표(애니메이션은 `globals.css`의 `.typing-dots`) |
| `ToneSlider.tsx` | 담백/일반/적극 톤 선택 |

### `lib/`

| 파일 | 책임 |
|---|---|
| `api-client.ts` | **배럴** — `api/` 하위 5개 모듈을 `export *`로 재노출. 기존 `import { sessionApi } from "@/lib/api-client"` 호출부는 그대로 동작 |
| `api/client.ts` | 전송 계층 — `ApiError`, `request`/`requestText`/`requestForm`, 401→refresh→재시도(`withAuthRetry`) |
| `api/auth.ts` | `authApi` + 인증 타입 |
| `api/sessions.ts` | `sessionApi`(세션/기간/카테고리/인터뷰) + 관련 타입 |
| `api/records.ts` | `recordsApi` + 타입 |
| `api/document.ts` | `documentApi` + 타입 |
| `auth-context.tsx` | `AuthProvider`/`useAuth` — 액세스 토큰은 메모리에만 보관, 새로고침 시 refresh 쿠키로 복원 |
| `query-provider.tsx`, `query-keys.ts` | React Query 클라이언트, 쿼리 키 컨벤션 |
| `use-session-context.ts`, `use-sessions-list.ts` | 세션 상세/목록 조회 훅 |
| `session-routes.ts` | 상태→라벨 매핑, 인터뷰/결과 상태 집합 |
| `error-messages.ts` | 백엔드 에러 코드 → 한국어 메시지 매핑 |

## 5. 요청 흐름 예시 (인터뷰 초안 1건)

```mermaid
graph LR
  UI["InterviewSection.tsx<br/>(GET .../interview/next)"]
  API["api/interview.py<br/>interview_next()"]
  ORCH["interview_orchestrator<br/>require_draft_step()"]
  SEARCH["record_pipeline/search.py<br/>search_relevant_chunks()"]
  LLM["llm/local_ollama.py<br/>LocalOllamaProvider.draft_suggestion()"]
  DB[(sessions / confirmed_facts / record_chunks)]

  UI --> API --> ORCH
  API --> SEARCH --> DB
  API --> LLM
  API --> DB
```

## 6. 설계 원칙 (다음에 코드 추가할 때 참고)

- **정직성 가드레일**: 생성 문서의 모든 문장은 `confirmed_facts`를 인용해야 한다. 이건 한 함수의 책임이 아니라 세 겹으로 강제된다 — (1) `document_generator.generate_full_document`가 LLM에 ORM 객체가 아니라 `confirmed_facts`의 내용만 넘김, (2) `interview.py`의 `interview_confirm`이 `source_type`을 클라이언트가 지정 못하게 서버가 캐시해둔 `pending_draft`에서만 도출, (3) `consistency_check.check_sentence_consistency`가 생성된 문장과 인용된 근거의 의미적 유사도를 사후 검증. 새 생성 경로를 추가한다면 이 세 겹을 다 거쳐야 한다.
- **DI 훅은 자기 서비스 파일에 둔다**: FastAPI 라우터가 교체 가능한 의존성이 필요하면(테스트에서 가짜로 바꿔치기하기 위해), `get_X()` 함수를 그 X를 구현하는 서비스 모듈 안에 정의한다 — `get_storage()`(`services/storage.py`), `get_chunk_search()`(`services/record_pipeline/search.py`), `get_embedding_provider()`(`services/embedding/__init__.py`), `get_llm_provider()`(`services/llm/__init__.py`)가 전부 이 규칙을 따른다. 라우터 파일에 두면 다른 라우터가 그걸 가져다 쓰려 할 때 라우터끼리 직접 의존하게 된다 (7절 참고).
- **외부 소스는 등록제이고, 인증키가 없으면 조용히 빠진다**: 워크넷/온통청년 키는 담당자 심사를 거쳐 카테고리마다 따로 발급된다. 미발급은 오류가 아니라 설정 상태다 — 예외로 다루면 승인될 때까지 메인 화면에 배너가 계속 뜬다(`services/feed/sources/__init__.py`).
- **임베딩 실패는 데이터 손실이 아니라 정렬 품질 저하로만 나타나야 한다**: Gemini를 제거한 뒤 임베딩 경로는 로컬 bge-m3 하나뿐이라 터널이 끊기면 100% 실패한다. 그래서 벡터 컬럼은 nullable이고, 항목은 임베딩 전에 커밋되며, 다음 수집이 빈 벡터를 backfill한다. 조회는 벡터가 없으면 최신순으로 내려간다.
- **`Vector` 컬럼은 1:1 곁테이블에 둔다**: pgvector는 SQLite 컴파일러가 없어서, 벡터를 본체 테이블에 얹으면 그 테이블을 쓰는 API를 `tests/api/conftest.py`에서 아예 생성할 수 없다. `feed_items`/`feed_item_embeddings`가 이 규칙을 따르고, `record_chunks`가 테스트하기 까다로운 이유도 같다. 대가는 조인 하나와 코사인 정렬 자체가 CI 미검증으로 남는 것이다.
- **목록 페이지네이션은 `limit`/`offset` + `Query(ge=, le=)`**: `api/profile.py`가 세운 선례를 `api/feed.py`가 따른다. 커서 방식을 새로 만들지 않는다. 정렬에는 항상 결정적 2차 키(`id`)를 붙인다 — 한 수집 배치는 타임스탬프가 같아서 없으면 페이지가 겹치고 새어나간다.
- **fan-out은 싼 계층에서만 한다**: 워크넷 조회는 순수 HTTP라 동시에 던져도 카테고리당 0.2~1.2초에 끝나지만, 로컬 Ollama는 요청을 직렬 처리하므로 LLM 호출을 동시에 던지면 뒤쪽 호출이 큐에서 자기 타임아웃을 다 쓰고 죽는다(6개 중 5개 실패를 실측, devlog 20). 그래서 조회는 `asyncio.gather`로, LLM 판단은 순차 + 전체 시간 예산으로 돌린다. 새로 LLM 호출을 카테고리/항목마다 추가하려 한다면 먼저 호출 수가 상수인지 확인한다.
- **조건은 사후 필터링이 아니라 조회 질의로 넘긴다**: 워크넷 API는 지역/키워드 필터를 지원하므로, 전국 목록을 받아 LLM에게 걸러내게 하지 않고 질문에서 뽑은 조건을 API에 실어 보낸다. 같은 파라미터에 값을 여러 개 넣는 건 불가능하고(콤마는 0건, 반복 파라미터는 첫 값만 적용), 잘못된 코드도 에러가 아니라 조용한 0건이라 코드 변환은 `regions.py`의 검증된 표만 쓴다.
- **LLM 프로바이더 메서드는 샘플링 모드를 명시한다**: 프로바이더에 새 메서드를 추가하면 `_generate`/`_call`에 `TEMPERATURE_DETERMINISTIC`(분류·추출·판단) 또는 `TEMPERATURE_CREATIVE`(초안·문서 생성) 중 하나를 반드시 넘겨야 한다 — 기본값을 두지 않은 건 그 결정을 강제하려는 의도다. 지정하지 않으면 모델 기본값(~0.7)이 걸려 같은 입력에 회차마다 다른 답이 나온다(devlog 19에서 실측).
- **LLM에게 "다양하게 하라"고 시키지 말고 선택을 코드로 가져온다**: 카테고리 되묻기에서 모델에게 갈래를 고르게 했더니 프롬프트를 손볼 때마다 쏠리는 갈래만 바뀌었다(아르바이트 → 운동/건강, 14b 실측). 서버가 `PROBE_FOCUSES`에서 고르고 LLM은 문장만 만들게 하니 다양성이 보장되고 테스트도 가능해졌다.
- **`api/X.py` ↔ `schemas/X.py` 1:1**: 새 라우터를 추가하면 그 스키마도 같은 이름의 새 파일에 둔다. 기존 파일에 끼워 넣지 않는다.
- **라우터 간 직접 import 금지**: 두 라우터가 같은 헬퍼가 필요하면 그 헬퍼는 `models/`나 `services/`로 옮긴다(모델에 대한 순수 함수라면 그 모델의 property/method로).

## 7. 이번 모듈성 정리에서 옮긴 것

세션 이름변경/삭제 기능을 추가하면서 구조를 점검했고, 아래 4가지를 동작 변화 없이 재배치했다:

1. `get_llm_provider()`: `api/interview.py` → `services/llm/fallback.py` (DI 훅 컨벤션 통일)
2. `category_label()`: `api/sessions.py`의 함수 → `ActivityCategory.label` property (라우터 간 import 제거)
3. `schemas/session.py`(4개 도메인 158줄) → `schemas/session.py` + `schemas/interview.py`로 분리
4. `frontend/lib/api-client.ts`(481줄, 전 도메인 단일 파일) → `lib/api/{client,auth,sessions,records,document}.ts`로 분리, 기존 파일은 배럴로 유지
