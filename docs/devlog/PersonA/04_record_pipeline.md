# A-4. 기록물 수집 파이프라인 devlog

체크리스트: `docs/checklists/person_A_infra_ai/04_record_pipeline.md`
날짜: 2026-09-01
커밋: `23773d2`

---

## 진입점 설계

B의 `POST /sessions/{id}/records` API가 FastAPI `BackgroundTasks`로 이 파이프라인을 호출한다. 두 진입점이 있다:

- `process_record(record_id)`: `blog_url` 또는 `pasted_text` 처리
- `process_image_record(record_id)`: 이미지 OCR 처리

두 함수 모두 예외를 잡아서 `records.parse_status = "FAILED"`, `parse_error = 사용자용 메시지`로 저장하고 종료한다. 예외를 재발생시키지 않아 background task가 크래시되지 않는다.

## 플랫폼 판별 (`platform_detector.py`)

URL의 netloc만 보고 정규식으로 판별한다. 네이버 블로그는 `blog.naver.com`과 모바일 `m.blog.naver.com` 두 패턴을 모두 처리한다.

## 네이버 블로그 파서

네이버 블로그 URL에 접속하면 실제 본문이 `<iframe id="mainFrame">` 안에 있다. iframe의 `src`는 `/PostView.naver?blogId=...&logNo=...` 형태의 상대 경로다. `https://blog.naver.com`을 붙여 절대 URL로 만든 뒤 다시 요청해야 실제 본문을 얻을 수 있다.

본문 컨테이너는 스마트 에디터 3(`.se-main-container`)과 구 에디터(`#postViewArea`) 두 가지를 순서대로 시도한다. 비공개 게시물이면 iframe 자체가 없으므로 `ValueError`가 발생하고, 파이프라인이 "비공개 게시물은 가져올 수 없어요"로 사용자에게 안내한다.

## 티스토리 파서

`.contents_style`, `.article-view` 등 알려진 선택자를 순서대로 시도하다가 모두 실패하면 generic 파서로 위임한다. 날짜는 `<time>` 태그 또는 `date` 클래스명을 가진 요소에서 정규식으로 추출한다.

## Generic 파서

`trafilatura.extract()`를 사용한다. `include_comments=False`, `include_tables=False` 옵션으로 댓글과 테이블은 제외한다. 날짜는 `trafilatura.extract_metadata().date`에서 가져오며 ISO 형식(`YYYY-MM-DD`)의 앞 10글자만 파싱한다.

## 날짜 필터링

`gap_periods` 테이블에서 해당 세션의 공백기 범위를 조회하고, 포스트의 `published_at`이 범위 밖이면 청킹 없이 `parse_status = "DONE"`으로 조용히 종료한다. `gap_period`가 없는 세션은 `date.min ~ date.max`로 처리해 모든 날짜를 허용한다.

## 청킹 (`chunker.py`)

빈 줄(`\n{2,}`)로 1차 분리한 뒤, 500자를 넘는 문단은 마침표/느낌표/물음표 뒤 공백 기준으로 추가 분할한다. 50자 미만 조각은 필터링한다. 각 청크에 `chunk_index`(문단 순서)와 `published_at`(원 포스트 날짜 상속)을 부여한다.

## 임베딩 저장

`_embed_and_store()`에서 청크 텍스트 전체를 `FallbackEmbedding.embed()`에 한꺼번에 넘긴다 (배치). `embedding_model` 컬럼에 실제 사용된 모델명을 기록해, 나중에 `search_relevant_chunks`가 동일 모델로만 필터링할 수 있게 한다.

## OCR (`ocr.py`)

Gemini 1.5 Flash의 멀티모달 기능을 사용한다. 이미지 바이트를 `types.Part.from_bytes()`로 감싸서 텍스트 프롬프트와 함께 전달한다. 발급일 파싱은 두 단계:

1. 응답에서 `DATE: YYYY-MM-DD` 패턴을 먼저 찾는다 (Gemini가 명시적으로 출력한 경우)
2. 없으면 본문에서 `YYYY-년-월-일` 형태 정규식으로 재시도한다

## 의미 검색 (`search.py`)

카테고리 라벨(예: "프리랜서")을 `FallbackEmbedding`으로 임베딩하고, 해당 세션의 `record_chunks`에서 pgvector `cosine_distance` 기준 top-k를 반환한다.

```python
.order_by(RecordChunk.embedding.cosine_distance(query_vector))
```

다른 세션 청크가 섞이지 않도록 `Record.session_id == session_id` 서브쿼리로 필터링한다. 임베딩 모델이 다른 청크는 `RecordChunk.embedding_model == provider.model_name`으로 제외한다.

## 인용 조회 (`citation.py`)

`confirmed_facts.source_record_chunk_id`가 있으면 `RecordChunk → Record` 조인으로 `source_url`과 `published_at`을 반환한다. 없으면 (`user_confirmed`/`user_edited` 사실) `None`을 반환한다. B의 `GET /sessions/{id}/document`가 이를 호출해 각 문장의 출처를 채운다.
