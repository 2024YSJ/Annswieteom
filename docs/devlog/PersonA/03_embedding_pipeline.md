# A-3. 임베딩 파이프라인 devlog

체크리스트: `docs/checklists/person_A_infra_ai/03_embedding_pipeline.md`
날짜: 2026-09-01
커밋: `60a1c52`

---

## EmbeddingProvider Protocol

LLM 어댑터(A-2)와 동일한 패턴으로 `EmbeddingProvider`를 `typing.Protocol`로 선언했다. `model_name` 프로퍼티를 인터페이스에 포함시킨 이유는, 검색 시 저장 당시와 동일한 모델로 쿼리 벡터를 만들어야 하기 때문이다 — `model_name`을 `RecordChunk.embedding_model`에 기록하고, 검색 함수에서 그 값으로 필터링한다.

## LocalOllamaEmbedding

Ollama의 `bge-m3` 모델을 `/api/embed` 배치 엔드포인트로 호출한다. 구버전 Ollama가 쓰는 `/api/embeddings`는 `prompt`(단일 문자열)만 받지만, `/api/embed`는 `input`에 리스트를 넣어 한 번에 여러 텍스트를 벡터화할 수 있다. `bge-m3`의 출력 차원은 1024로, `record_chunks.embedding VECTOR(1024)` 컬럼과 일치한다. 응답에서 차원을 직접 검증해 불일치 시 `EmbeddingDimensionMismatchError`를 낸다.

```python
resp = await client.post(f"{base_url}/api/embed", json={"model": "bge-m3", "input": texts})
vectors = resp.json()["embeddings"]  # list[list[float]]
```

검증 결과 (scripts/verify_embedding.py):
- 차원 1024 ✓
- 편의점/카페 알바 유사도 0.71 > 편의점/ML개발 유사도 0.50 ✓

## GeminiEmbedding — 차원 불일치 문제

`text-embedding-004`는 최대 768차원으로, DB의 VECTOR(1024)와 맞지 않는다. 잘못된 차원의 벡터를 조용히 저장하면 코사인 유사도 검색 자체가 의미 없어지므로, 호출 즉시 `EmbeddingDimensionMismatchError`를 발생시키도록 구현했다. 해결 옵션 3가지(1024차원 지원 Gemini 모델 탐색, DB를 VECTOR(768)로 마이그레이션, 재시도 큐)를 모듈 docstring에 남겼다.

## FallbackEmbedding

LLM의 `FallbackProvider`와 달리, `EmbeddingDimensionMismatchError`는 다음 provider로 넘기지 않는다 — 차원 불일치는 provider를 바꿔도 해결되지 않는 스키마 문제이기 때문이다. `TimeoutError`와 `EmbeddingProviderUnavailableError`만 폴백 대상이다.

## SDK 마이그레이션

`google-generativeai` 패키지가 deprecated 경고를 냈다. 신규 SDK인 `google-genai`로 교체했다. API 변화:
- 구: `genai.configure(api_key=...)` + `genai.GenerativeModel("...")`
- 신: `genai.Client(api_key=...)` + `client.aio.models.generate_content(...)`

비동기 호출은 `client.aio.models.*` 네임스페이스를 쓴다. `gemini_provider.py`(LLM)도 함께 업데이트했다.
