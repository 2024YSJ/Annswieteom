# B-4. 문서 생성/조회/수정 API devlog

체크리스트: `docs/checklists/person_B_frontend_backend/04_document_generation.md`
날짜: 2026-09-03
브랜치: `feature/document-generation` (`dev`에서 분기)

---

## 완료 항목

- `app/services/document_generator.py`: `generate_full_document(session_id, tone, db, llm)` — 세션의 `activity_categories`를 순회하며 카테고리별로 `LLMProvider.generate_document(facts, tone)`를 한 번씩 호출, 반환된 `fact_indices`를 실제 `confirmed_facts.id`로 매핑해 `generated_sentences.evidence_fact_ids`에 저장, 문장마다 A의 `check_sentence_consistency()` 호출
- `regenerate_sentence(sentence, tone, db, llm)`: 단건 재생성 — 그 문장이 원래 인용했던 facts만 다시 넘겨 근거 범위를 벗어나지 않게 함
- `app/api/document.py`: 9-5절 7개 엔드포인트 전부(`generate`, `GET document`, `regenerate`, `PATCH sentences/{id}`, `sentences/{id}/regenerate`, `finalize`, `export`)
- `orchestrator.SIMPLE_TRANSITIONS`에 `"generate": ("RESULT_GENERATE", "RESULT_REVIEW")` 추가
- `record_pipeline/citation.py`에 `get_fact_citation()` DI 훅 추가 (`get_chunk_search`와 동일 패턴)
- `schemas/document.py`에 `EvidenceRead`/`CitationRead` 추가 — `GET /document`가 `evidence_fact_ids`(UUID 배열)를 그대로 안 내려주고 `content`/`source_type`/`citation`까지 확장해서 응답
- 테스트 12개 추가 (`tests/api/test_document.py`) — 전체 스위트 69개 통과

## 핵심 결정 사항과 이유

**정직성 가드레일 경계를 `generate_full_document` 안에 그대로 코드로 박음**: `LLMProvider.generate_document()`에는 `[LLMConfirmedFact(id, content, source_type, fact_type), ...]`와 `tone` 문자열만 넘긴다 — `Session`이나 `ActivityCategory` ORM 객체를 통째로 넘기지 않는다. 체크리스트 1절이 요구한 그대로다. `evidence_fact_ids`는 LLM이 반환한 `fact_indices`(그 호출에 넘긴 facts 리스트 안에서의 인덱스)를 실제 `ConfirmedFact.id`로 역매핑해서 채운다 — 범위를 벗어난 인덱스는 조용히 무시(`0 <= i < len(facts)`)해서 LLM이 이상한 인덱스를 반환해도 서버가 죽지 않는다.

**단건 문장 재생성은 "그 문장이 인용한 facts만" 다시 넘긴다**: `LLMProvider.generate_document()`는 카테고리 전체를 받아 여러 문장을 한 번에 만드는 저수준 API라 "문장 하나만" 만드는 기능이 원래 없다. 카테고리 전체를 다시 넘기면 관계없는 다른 문장까지 새로 만들어질 위험이 있어서, 대신 이 문장의 기존 `evidence_fact_ids`가 가리키는 facts만 추려 그걸로 새 초안을 받고 첫 문장을 채택한다 — 여전히 "이 문장이 원래 근거로 삼던 사실 밖의 내용은 섞이지 않는다"는 보장은 유지된다.

**`GeneratedSentence.evidence_fact_ids`를 `JSONB`에서 제네릭 `JSON`으로 교정**: 실제로 이 테이블에 처음 쓰기/읽기를 구현해보니 SQLite(테스트 DB)가 `JSONB`를 컴파일 못 해서 막혔다 — B-2가 `sessions.pending_draft`에서 이미 겪고 고쳤던 것과 완전히 같은 문제인데, `generated_sentence.py`는 그 교훈이 반영되기 전에 미리 스캐폴딩된 모델이라 놓쳐 있었다. 이 컬럼도 내용으로 쿼리/인덱싱할 일이 없어서(그냥 통째로 쓰고 통째로 읽음) `JSONB`의 이점이 애초에 필요 없다. 모델을 고치고 마이그레이션(`416fb65dbf6f`, `90edf5d28f6a` 위에 얹음)을 새로 추가했다 — 기존 마이그레이션 파일은 이미 실 Supabase에 적용됐을 수 있으니 건드리지 않고 `ALTER COLUMN ... USING evidence_fact_ids::json`으로 처리.

**PATCH로 문장을 직접 수정하면 `consistency_check_passed`를 강제로 `True`로**: 체크리스트가 "재검증 불필요 — 사용자가 직접 쓴 것이므로 이미 확인됨"이라고 명시했다. 재검증을 안 하는 것과 별개로, 기존에 `false`였던 문장을 사용자가 고쳐 썼는데 화면에 여전히 "확인 필요"로 표시되면 혼란스러우므로 명시적으로 `True`로 바꿔준다. `evidence_fact_ids`는 그대로 둔다 — 사용자가 문장 표현만 바꾼 것이지 근거 자체가 바뀐 게 아니기 때문.

**`embedding_provider`를 API 레이어까지 DI로 관통시킴**: `document_generator.py`가 내부적으로 A-6의 `check_sentence_consistency()`를 호출하는데, 이게 기본값으로 진짜 `FallbackEmbedding()`을 쓰면 테스트가 실제 Ollama/Gemini 네트워크를 필요로 하게 된다. `app/services/embedding/__init__.py`에 `get_embedding_provider()` DI 훅을 새로 추가하고, `api/document.py`의 모든 관련 라우트가 이걸 `Depends()`로 받아 `document_generator` 함수들에 전달하도록 했다 — `get_llm_provider`/`get_chunk_search`/`get_storage`와 같은 패턴을 한 겹 더 늘린 것.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `tests/api/test_document.py`의 테이블 생성이 `CompileError: can't render element of type JSONB`로 실패 | `GeneratedSentence.evidence_fact_ids`가 `sqlalchemy.dialects.postgresql.JSONB` — SQLite 방언에 타입 컴파일러가 없음 | 모델을 제네릭 `sqlalchemy.JSON`으로 변경 + 새 마이그레이션 `416fb65dbf6f` 추가 (위 "핵심 결정 사항" 참고) |

## 테스트 전략

`tests/api/conftest.py`에 `document_client` 픽스처 추가 — `generated_documents`/`generated_sentences` 테이블까지 포함하고, `FakeLLMProvider.generate_document()`(기본: fact당 문장 하나, `[{tone}] {fact.content}` 형태)와 `FakeEmbeddingProvider`(기본: 모든 텍스트가 같은 벡터 → 코사인 유사도 1.0 → 항상 통과, 특정 문장에만 다른 벡터를 등록해 `consistency_check_passed=False` 케이스도 검증 가능)를 오버라이드한다. `resolve_fact_citation`도 항상 `None`을 반환하는 페이크로 교체했다(레코드 인용이 없는 `user_confirmed` 사실만 다루므로).

12개 테스트로 생성→상태 전이, 카테고리별로 그 카테고리 facts만 LLM에 전달되는지, 최신 버전 조회, 재생성 시 새 버전 생성, 문장 직접 수정, 단건 재생성(자신의 근거만 사용), 확정 후 텍스트 내보내기(확정 전엔 409), 지원 안 하는 export 포맷 400, 근거와 무관한 문장이 삭제되지 않고 `consistency_check_passed=false`로만 표시되는지, 타인 세션 403/타 세션 문장 ID 404까지 확인.

## 남은 작업

- 프론트 결과 화면(`frontend/app/sessions/[id]/result/page.tsx`) — [03_records_feature.md 데블로그](03_records_feature.md)에서와 같은 이유로 미룸: 세션 플로우 페이지가 아직 하나도 없어서 마일스톤 5(전체 라우트)에서 한 번에 잡는 게 낫다
- 실제 Ollama/Gemini + 실 Supabase로 전체 흐름 재검증 (지금까지는 `FakeLLMProvider`/`FakeEmbeddingProvider` + SQLite)
- 새 마이그레이션(`416fb65dbf6f`)을 실 Supabase에 아직 적용 안 함 — `alembic upgrade head` 필요
- A-6의 `consistency_threshold` 실측 튜닝 — 이제 실제 생성 문장이 나오기 시작했으니 다음 차례
