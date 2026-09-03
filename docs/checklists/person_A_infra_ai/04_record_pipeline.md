# A-4. 기록물 수집 파이프라인

근거: 명세서 13-1절, 13-2절
선행 조건: [03_embedding_pipeline.md](03_embedding_pipeline.md), [00_shared/02_database_schema.md](../00_shared/02_database_schema.md)의 `records`/`record_chunks` 테이블
폴더: `backend/app/services/record_pipeline/`
브랜치: `feature/record-pipeline` (`dev`에서 분기, 완료 후 `dev`로 PR)
시점: 2주차

이 파이프라인은 B가 만드는 `POST /sessions/{id}/records` API(9-4절)에서 호출된다. 아래처럼 단일 진입점 함수 2개를 `record_pipeline/__init__.py`(또는 `pipeline.py`)에 노출해, B의 `BackgroundTasks`가 이 함수만 호출하면 되도록 만든다 — B가 1~8번 내부 단계를 직접 조립하지 않아도 되게 하는 것이 목적이다.

- [x] `async def process_record(record_id: UUID) -> None`: `record_type`이 `blog_url`/`pasted_text`인 레코드를 대상으로 1(플랫폼 판별, `pasted_text`면 건너뜀)→2(파싱, `pasted_text`면 건너뜀)→3(날짜 필터링)→4(청킹)→5(임베딩·저장)를 순서대로 실행하고, 끝나면 `records.parse_status`를 `DONE`/`FAILED`로 갱신까지 이 함수 안에서 처리한다(B가 별도로 상태를 갱신하지 않아도 됨) — ⚠️ B-3에서 실제 연동해보며 발견: 실제 DB 제약은 `pasted_text`가 아니라 `text`였고 코드도 그렇게 수정함(devlog [03_records_feature.md](../../devlog/PersonB/03_records_feature.md) 참고)
- [x] `async def process_image_record(record_id: UUID) -> None`: `record_type='image'` 레코드를 대상으로 7(OCR)→4(청킹)→5(임베딩·저장)를 실행하고 동일하게 `parse_status`를 갱신한다
- [x] 두 함수 모두 예외 발생 시 잡아서 `records.parse_status='FAILED'`, `parse_error`에 사용자용 메시지를 채우고 종료(예외를 그대로 올려 background task를 죽이지 않는다)

## 1. 플랫폼 판별 (`platform_detector.py`)

- [x] URL의 도메인을 보고 `naver_blog` / `tistory` / `velog` / `brunch` / `generic` 중 하나로 분류하는 함수 작성 (6-7절 `platform` 컬럼 CHECK 값과 일치시킬 것)

## 2. 플랫폼별 파서 (`parsers/`)

- [x] `naver_blog.py`: 네이버 블로그는 본문이 iframe 안에 있으므로, 실제 본문이 담긴 내부 URL(`PostView.naver` 등 패턴)을 찾아 그 페이지를 다시 요청하는 방식으로 구현
- [x] `tistory.py`: 일반적인 HTML 파싱(본문 컨테이너 선택자 기반)
- [x] `generic.py`: 알려지지 않은 플랫폼용 범용 파서(`trafilatura` 사용)
- [x] velog, brunch는 `generic.py` 로직으로 우선 처리하고 실패율이 높으면 전용 파서 추가 검토
- [x] 비공개 블로그(접근 불가)일 경우 `records.parse_status='FAILED'`, `parse_error`에 사용자에게 보여줄 메시지 기록 (예: "비공개 게시물은 가져올 수 없어요")

## 3. 날짜 필터링

- [x] 파싱된 게시물의 작성일을 추출해 `gap_periods.start_date`~`end_date` 범위 밖이면 청킹 단계로 넘기지 않고 건너뛰는 로직 작성

## 4. 청킹 (`chunker.py`)

- [x] 문단 단위로 1차 분리
- [x] 500자 초과 문단은 문장 경계 기준으로 추가 분할
- [x] 50자 미만 조각은 제외
- [x] 각 청크에 `chunk_index`(순서), `published_at`(원 게시물 작성일 상속) 부여

## 5. 임베딩 및 저장

- [x] 각 청크를 03번 임베딩 파이프라인으로 벡터화, `record_chunks`에 `embedding`, `embedding_model`과 함께 저장

## 6. 의미 검색

- [x] `record_pipeline`에서 노출할 진입점: `async def search_relevant_chunks(session_id: UUID, category_label: str, top_k: int = 5) -> list[RecordChunkExcerpt]` (`RecordChunkExcerpt`는 `chunk_id`, `text`, `published_at` 필드를 가진 간단한 모델 — `chunk_id`는 B가 `confirmed_facts.source_record_chunk_id`를 채우는 데 필요하다) — B의 [02_interview_state_machine_api.md](../person_B_frontend_backend/02_interview_state_machine_api.md)가 `InterviewContext.available_record_chunks`를 채울 때 이 함수를 그대로 호출한다
- [x] 내부적으로 활동 카테고리 라벨(예: "프리랜서")을 쿼리로 임베딩해 해당 세션의 `record_chunks`에서 코사인 유사도 top-N 검색 (pgvector `<=>` 연산자 또는 ORM의 벡터 검색 헬퍼 사용) — 다른 세션의 청크가 섞이지 않도록 `session_id`로 반드시 필터링
- [x] 반환 형태(`published_at`, `text`)는 12-1절 프롬프트의 `record_excerpts`에 그대로 대입 가능해야 한다

## 7. 이미지 기록물 (OCR, 13-2절)

- [x] Gemini 비전 기능으로 이미지에서 텍스트 추출하는 함수 작성 (`ocr.py`)
- [x] 자격증 발급일 등 날짜 패턴이 있으면 파싱해 `record_chunks.published_at`에 채움
- [x] OCR 결과도 4~6번과 동일하게 청킹·임베딩 파이프라인을 태움

## 8. 인용 표시 지원

- [x] `async def resolve_fact_citation(fact_id: UUID) -> Citation | None`: `confirmed_facts.source_record_chunk_id`가 있으면 `record_chunks` → `records`를 조인해 `{source_url, published_at}`을 반환하고, 없으면(`user_confirmed`/`user_edited`) `None` 반환 — B의 [04_document_generation.md](../person_B_frontend_backend/04_document_generation.md) `GET /sessions/{id}/document`가 이 함수로 각 문장의 근거를 채운다

## 검증 기준

- [ ] 실제 네이버 블로그 URL, 티스토리 URL 각각 하나씩 등록했을 때 본문이 정상적으로 `records.raw_text`에 채워진다 — 코드 구현 및 유닛 레벨 확인은 됐으나, 실제 공개 블로그 URL로 등록해 눈으로 확인한 적은 아직 없음
- [ ] 공백기 범위 밖 게시물은 청크로 저장되지 않는다 — 코드로는 구현됨, 실제 데이터로 눈으로 확인 안 함
- [ ] 카테고리 라벨로 검색했을 때 관련성 높은 청크가 상위로 나온다 (직접 눈으로 확인) — B-5 실 브라우저 테스트에서는 등록한 텍스트가 카테고리와 느슨하게만 연관돼 있어 매번 "AI의 일반적인 추측"(`generic_pattern`)으로만 뜸 — 실제로 근거로 채택되는 사례는 아직 못 봄
- [ ] 이미지 자격증 파일을 업로드했을 때 텍스트와 발급일이 추출된다 — `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` 미설정으로 이미지 업로드 자체를 아직 테스트 못 함
