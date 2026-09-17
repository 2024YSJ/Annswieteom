# 60. 로컬 GPU 처리 통계 배지 (2026-09-16)

"클라우드 LLM이 아니라 로컬(DGX Spark) GPU로 직접 추론한다"는 이 프로젝트의
차별점을 데모에서 수치로 보여주기 위한 기능.

## 무엇을

- `LLMCallStats` 데이터클래스(`services/llm/base.py`) 신규 — 기존에
  `local_ollama.py`의 `_log_generation_stats`가 로그 한 줄로만 남기던
  label/출력 토큰 수/decode 시간/tokens-per-second를 구조화.
- `LocalOllamaProvider`가 인스턴스 속성 `generation_stats: list[LLMCallStats]`에
  호출마다 누적. **`LLMProvider` Protocol이나 `document_generator` 시그니처는
  전혀 안 건드림** — `document.py`의 handler가 이미 갖고 있는 같은 provider
  인스턴스에서 `getattr(llm, "generation_stats", [])`로 직접 읽기 때문.
  `getattr` 기본값을 쓰는 이유: 테스트용 `FakeLLMProvider`엔 이 속성이 없고,
  그때는 그냥 배지를 안 보여주면 됨(`None`).
- **동시성 안전성은 설계로 보장**: `get_llm_provider()`가 요청마다 캐시 없이
  새 `LocalOllamaProvider`를 만들기 때문에 `self`에 누적해도 요청 간 경합이
  없다 — 이 전제가 깨지면(프로바이더를 캐시/싱글턴으로 바꾸면) 이 리스트를
  `contextvars.ContextVar`로 옮겨야 한다는 점을 양쪽 끝에 주석으로 남김.
- `document.py`의 generate/regenerate 핸들러가 `generate_full_document` 호출
  뒤 `generation_stats`를 합산해 `GpuGenerationStatsRead`로 응답에 첨부.
  카테고리마다 `llm.generate_document`를 순차 호출하므로 한 문서 생성에
  여러 건이 쌓일 수 있어 합쳐서 하나의 tok/s로 노출.
- 프론트 `LocalGpuBadge.tsx` — 톤 슬라이더 옆에 "로컬에서 처리됨, N tok/s"
  작은 배지. generate/regenerate 응답에만 존재(일반 `GET /document` 재조회나
  데모 문서엔 실시간 통계가 없으므로 노출 안 함).

## 검증

- `backend/tests/api/test_gpu_stats.py` 신규(63줄)

## 남은 작업

- [ ] 배포된 사이트에서 실제 문서 생성 시 tok/s 값이 합리적인 범위(9번
      devlog 기준 qwen3.5:35b-a3b는 32b 대비 ~5배 빠름)로 나오는지 확인

## 관련 커밋

- `7a7e04c` feat: surface local-GPU processing stats as a UI badge
