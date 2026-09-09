# Gemini 완전 제거 — 폴백 없는 단일 프로바이더로

관련 spec: 없음(16~20과 동일하게 체크리스트 밖 항목)
날짜: 2026-09-09

---

## 배경

사용자 지시: "Gemini 없애자. 폴백하는 경우 그냥 '**AI 서버가 수리 중이예요.**'를 출력하게 하고."

조사해보니 Gemini는 **세 군데**에 있었다. 두 개는 알고 있었고, 하나는 계획 단계에서 놓쳤다가 코드를 지우고 나서 grep으로 발견했다.

1. **LLM 폴백** (`llm/gemini_provider.py` + `llm/fallback.py`) — `LLM_PROVIDER_ORDER="local,gemini"` 순으로 시도.
2. **임베딩 폴백** (`embedding/gemini_embedding.py` + `embedding/fallback.py`) — **이미 죽어 있었다.** `_GEMINI_DIM = 768`인데 `EMBEDDING_DIM = 1024`라 `embed()`가 첫 줄에서 `EmbeddingDimensionMismatchError`를 던지고, `FallbackEmbedding`은 이 예외만은 다음 프로바이더로 넘기지 않고 그대로 re-raise한다. 즉 임베딩은 처음부터 로컬 bge-m3 전용이었고, 폴백은 이름만 폴백이었다.
3. **이미지 OCR** (`record_pipeline/ocr.py`) — `gemini-1.5-flash` Vision으로 자격증/수료증 이미지에서 텍스트와 발급일을 뽑던 경로. 여기는 폴백이 아니라 **유일한 구현**이었다.

## 완료 항목

### 삭제

`llm/gemini_provider.py`, `llm/fallback.py`, `embedding/gemini_embedding.py`, `embedding/fallback.py`, `record_pipeline/ocr.py`, 그리고 테스트 3개(`test_gemini_provider.py`, `test_gemini_embedding.py`, `test_llm_fallback.py`).

설정에서 `gemini_api_key` / `llm_provider_order` 제거, `.env.example`에서 두 줄 제거, `requirements.txt`에서 `google-genai==2.21.0` 제거.

### DI 훅 이동

`get_llm_provider()`가 `services/llm/fallback.py`와 함께 사라질 자리라 `services/llm/__init__.py`로 옮겼다 — `services/embedding/__init__.py`가 `get_embedding_provider()`를 들고 있던 것과 같은 모양이 됐다. **이름과 시그니처를 그대로 뒀기 때문에 라우터 3곳과 테스트 5곳은 import 한 줄만 바뀌고 호출 로직은 하나도 안 바뀌었다.** 훅을 없애고 `LocalOllamaProvider()`를 직접 쓰게 했다면 `dependency_overrides` 기반 테스트를 전부 다시 써야 했다.

### 예외를 하나로

프로바이더가 하나뿐인데 `AllProvidersFailedError`("전부 실패했다")는 거짓말이다.

- `ProviderUnavailableError` + `AllProvidersFailedError` → **`LLMUnavailableError`** 하나로.
- `EmbeddingProviderUnavailableError` + `AllEmbeddingProvidersFailedError` → **`EmbeddingUnavailableError`** 하나로.
- **타임아웃도 여기에 합쳤다.** 예전엔 `_chat`이 `httpx.TimeoutException`을 `TimeoutError`로 바꿔 던지고 폴백 계층이 `(TimeoutError, ProviderUnavailableError)`를 같이 잡았다. 폴백이 사라지면 그 "같이 잡는" 책임이 라우터로 내려오는데, 잡아야 할 예외가 둘이면 어딘가 한 곳에서 반드시 빠뜨린다. 호출부 입장에서 "AI를 못 썼다"는 결과는 동일하므로 하나로 합쳤다.
- `EmbeddingDimensionMismatchError`는 **남겼다.** bge-m3가 아닌 모델을 실수로 걸었을 때 1024 컬럼에 잘못된 차원이 들어가는 걸 막는 유일한 방어다.

라우터의 `detail="llm_unavailable"`은 **그대로 뒀다.** 프론트 매핑과 기존 테스트가 이 문자열에 묶여 있고, 코드값 자체는 여전히 정확하다. 바뀐 건 그 코드가 화면에 그려지는 문구뿐이다.

### 이미지 OCR 제거

대체할 비전 모델이 없다(로컬 Ollama에는 `bge-m3`/`phi3.5`/`llama3.2:3b`/`qwen2.5:3b-instruct`뿐). 사용자에게 "OCR에만 Gemini를 남길지" 물었고 답은 "그냥 없애"였다.

`process_image_record()`와 `_guess_mime_type()`을 지우고, 업로드 엔드포인트에서 이미지 확장자 분기를 걷어냈다. 이제 `.jpg/.png/.webp`는 다른 미지원 형식과 똑같이 `400 unsupported_file_type`으로 거절된다.

**받아두고 조용히 실패시키지 않고 거절하기로 한 이유**: 텍스트를 못 뽑으면 청크도 임베딩도 안 만들어져서 그 기록물은 어떤 문장의 근거도 될 수 없다. 그런데 업로드가 201로 성공하면 사용자는 근거가 쌓였다고 믿는다. 이 서비스에서 그건 단순한 빈 목록이 아니라 정직성 문제에 가깝다.

`models/record.py`의 `RECORD_TYPES`에는 `"image"`를 **남겨뒀다.** 이미 저장된 과거 행이 CHECK 제약에 걸리면 안 되기 때문이고, 새로 만들어지는 경로는 없으므로 마이그레이션도 필요 없다.

### 프론트(문구 3곳)

- `llm_unavailable` → **"AI 서버가 수리 중이예요."**
- `unsupported_image_type`(이제 백엔드가 안 던짐) → `unsupported_file_type`으로 교체.
- `worknet_unavailable` 삭제 — 백엔드 어디서도 던지지 않는 죽은 매핑이었다(grep 0건).
- `RecordsSection.tsx`의 `accept` 속성에서 이미지 MIME 제거 + 안내 문구에서 "이미지" 삭제. 서버가 거절할 파일을 고르게 두는 파일 선택기를 남겨두면 안 된다.

## 핵심 결정 사항과 이유

**폴백 계층 자체를 걷어냈다(프로바이더만 지우지 않고).** 프로바이더 목록이 1개인 폴백 래퍼는 "나중에 뭔가 붙일 자리"라는 인상만 주면서 실제로는 예외를 한 겹 감싸 이름을 헷갈리게 만든다. 로컬 Ollama를 직접 붙이고, 확장이 필요해지면 그때 다시 만드는 쪽을 택했다.

**로컬 `.env`에서 두 키를 지워야 했다.** 계획에는 "gitignore 대상이라 안 건드려도 된다"고 적었는데 **틀렸다.** pydantic-settings는 기본이 `extra="forbid"`라, 지운 필드가 `.env`에 남아 있으면 `Settings()` 생성 자체가 `ValidationError`로 죽는다(테스트 12개 파일이 수집 단계에서 터졌다). `extra="ignore"`로 완화하는 대신 키를 지우는 쪽을 택했다 — 오타 난 환경변수를 조용히 무시하는 것보다 부팅 때 크게 실패하는 게 낫다.

**→ 배포 시 주의: Railway 환경변수에서도 `GEMINI_API_KEY`와 `LLM_PROVIDER_ORDER`를 반드시 지워야 한다.** 안 지우면 같은 이유로 컨테이너가 부팅에 실패한다. 이건 조용한 성능 저하가 아니라 즉시 눈에 띄는 실패이므로, 배포 체크리스트에 한 줄로 충분하다.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `pytest`가 12개 파일에서 수집 단계부터 `ValidationError: gemini_api_key Extra inputs are not permitted` | `config.py`에서 필드를 지웠는데 로컬 `.env`에는 그대로 남아 있었고, pydantic-settings 기본값이 `extra="forbid"` | `.env`에서 해당 두 줄만 제거(다른 값은 그대로) |
| `google-genai`를 지운 뒤에도 테스트 232개가 전부 통과 — 그런데 이미지 OCR은 실제로 깨져 있었음 | `records_client` 픽스처가 `process_image_record`를 가짜로 바꿔치기해서 진짜 OCR 경로가 테스트에서 한 번도 실행되지 않는다 | grep으로 발견. 테스트 초록이 "이 경로가 동작한다"는 증거가 아닌 전형적인 사례 |
| `app.routes`를 세었더니 `/api/v1/*`가 0개로 보임 | 이 FastAPI 버전은 `include_router` 결과를 `_IncludedRouter`로 지연 병합해서 `r.path`가 없다 — 앱이 아니라 확인 방법이 틀렸다 | `app.openapi()['paths']`로 확인(41개 정상) |

## 남은 작업

- **Railway 환경변수 정리**(위 참고) — 배포 전 필수.
- 이 변경으로 마일스톤 5 검증 기준 한 줄이 폐기됐다(`docs/checklists/milestones_overview.md`). 폴백이 없으므로 데모 당일 로컬 추론 서버/터널 점검이 선택이 아니라 필수가 된다.
- 이미지 기록물을 다시 살리려면 로컬 비전 모델(llava/qwen2.5vl 등)을 받아 `ocr.py`를 재작성해야 한다. 한국어 자격증 OCR 품질은 별도 검증이 필요하다.
