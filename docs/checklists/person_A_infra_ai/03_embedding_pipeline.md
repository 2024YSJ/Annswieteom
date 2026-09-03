# A-3. 임베딩 파이프라인

근거: 명세서 11절
선행 조건: [01_local_llm_setup.md](01_local_llm_setup.md)에서 `bge-m3` 다운로드 완료
폴더: `backend/app/services/embedding/`
브랜치: `feature/embedding-pipeline` (`dev`에서 분기, 완료 후 `dev`로 PR)
시점: 2주차 (기록물 파이프라인과 병행)

> **개념**: 임베딩은 텍스트를 숫자 벡터로 바꿔, "의미가 비슷한 문장끼리 가까운 벡터가 되게" 만드는 것이다. 이걸 이용해 "이 블로그 글이 '알바' 카테고리와 관련 있는지"를 키워드 매칭이 아니라 의미 기반으로 검색할 수 있다.

## 1. 공통 인터페이스 (`base.py`)

- [x] `EmbeddingProvider` Protocol 정의: `async def embed(self, texts: list[str]) -> list[list[float]]`

## 2. `LocalOllamaEmbedding` (`local_ollama_embedding.py`)

- [x] Ollama의 `bge-m3` 모델로 임베딩 API(`/api/embed`, 배치 지원 — Ollama 0.3+) 호출
- [x] 반환된 벡터 차원 확인 후 `record_chunks.embedding` 컬럼의 `VECTOR(N)` 차원을 실제 차원에 맞춰 조정 → `VECTOR(1024)`로 확정(`EMBEDDING_DIM` 상수), 불일치 시 `EmbeddingDimensionMismatchError`

## 3. `CloudEmbedding` (`cloud_embedding.py`)

- [x] Gemini Embedding API 연동 (`GeminiEmbedding`) — ⚠️ **의도적 스텁**: `text-embedding-004`는 768차원 고정이라 `VECTOR(1024)`와 안 맞아서 호출 시 항상 `EmbeddingDimensionMismatchError`를 던지도록 구현돼 있다. 실제 폴백 동작은 아래 5번 항목이 해결돼야 완성된다

## 4. 모델 불일치 처리 (11절 핵심 주의사항)

- [x] 저장 시 사용한 임베딩 모델명을 반드시 `record_chunks.embedding_model`에 기록
- [x] 검색(질의) 시에도 저장 시점과 동일한 모델로 질의 벡터를 생성하도록 강제 — 로컬/클라우드 벡터를 절대 같은 유사도 비교에 섞지 않는다
- [x] 두 임베딩 모델을 오갈 가능성이 있으므로, 검색 함수는 "이 세션/기록물의 chunk들이 어떤 embedding_model로 저장됐는지" 먼저 확인하고 그에 맞는 provider로 질의 임베딩을 생성하는 구조로 작성

## 5. ⚠️ pgvector 컬럼 차원 고정 문제 (스키마와 맞물린 주의사항)

`record_chunks.embedding`은 Postgres 컬럼이라 **하나의 고정된 차원**(`VECTOR(N)`)만 가질 수 있다. `bge-m3`(1차 선택, 1024차원)와 Gemini Embedding API(폴백)가 서로 다른 차원의 벡터를 낸다면, 폴백이 실제로 발동했을 때 INSERT 자체가 차원 불일치로 실패한다 — "검색 시 같은 모델로 질의"만으로는 이 문제가 해결되지 않는다(저장이 아예 안 되는 문제이기 때문).

- [ ] Gemini Embedding API 호출 시 `output_dimensionality` 등 차원 지정 옵션을 확인해 **`bge-m3`와 동일한 차원(1024)으로 맞춰서 호출**하거나, 그것이 불가능한 모델이면 `record_chunks.embedding`을 가변 차원(`vector` without 고정 길이, ivfflat 인덱스 제약 영향 확인 필요) 또는 임베딩 모델별로 별도 컬럼/테이블을 두는 방식 중 하나를 B([00_shared/02_database_schema.md](../00_shared/02_database_schema.md) 담당)와 상의해서 결정 — **아직 미결정, 코드에는 옵션 A/B/C만 문서화돼 있음**(`gemini_embedding.py` 모듈 docstring)
- [ ] 결정된 방식을 실제로 기록물 임베딩 폴백 테스트(로컬 임베딩 서버를 꺼둔 채 블로그 URL 등록)로 검증 — 위가 미결정이라 아직 불가


## 검증 기준

- [x] 임의의 한국어 문장 3~5개를 임베딩해서 실제로 벡터(숫자 배열)가 반환된다 — B-5 실 브라우저 테스트에서 텍스트 기록물 등록 시 `bge-m3`로 실제 청킹·임베딩 성공 확인
- [ ] 의미가 비슷한 문장 2개와 전혀 다른 문장 1개를 넣었을 때, 비슷한 문장끼리의 코사인 유사도가 더 높게 나온다 (간단한 스크립트로 확인) — A-6 일관성 검증 로직이 이 성질에 의존하지만, `bge-m3` 실제 벡터로 별도 검증 스크립트를 돌려본 적은 없음
- [ ] `bge-m3`가 응답하지 않을 때 `CloudEmbedding`으로 자동 전환된다 — **현재 코드상 불가능**: `FallbackEmbedding`은 `EmbeddingDimensionMismatchError`를 재시도하지 않고 즉시 올려버리는데, `GeminiEmbedding`이 항상 이 에러를 던지므로 로컬이 죽으면 폴백이 아니라 완전 실패로 이어진다 (위 5번 항목 미해결과 직결)
