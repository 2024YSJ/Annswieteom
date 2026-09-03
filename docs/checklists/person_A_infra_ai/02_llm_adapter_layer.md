# A-2. AI 어댑터 레이어 (LLM Provider)

근거: 명세서 10절
선행 조건: [01_local_llm_setup.md](01_local_llm_setup.md) 완료, [00_shared/02_database_schema.md](../00_shared/02_database_schema.md)의 `InterviewContext`/`ConfirmedFact` 구조 이해
폴더: `backend/app/services/llm/`
브랜치: `feature/llm-adapter` (`dev`에서 분기, 완료 후 `dev`로 PR)
시점: 1~2주차

## 0. 프롬프트 템플릿 파일 작성 (12절 — 코드 하드코딩 금지)

- [ ] `backend/app/prompts/draft_suggestion.jinja` (또는 `.txt`)에 12-1절 프롬프트를 그대로 옮겨 파일로 관리
- [ ] `backend/app/prompts/final_document.jinja`에 12-2절 프롬프트를 그대로 옮겨 파일로 관리
- [ ] 두 파일 모두 코드에 문자열로 하드코딩하지 않고, provider가 파일을 읽어 Jinja(또는 동급 템플릿 엔진)로 렌더링하도록 로더 함수 작성
- [ ] v1에 있던 "JD 구조화 프롬프트"는 채용공고 파싱 제거로 만들지 않는다 (12-3절)

## 1. 공통 인터페이스 정의 (`base.py`)

- [ ] `LLMProvider` Protocol 정의 (10-1):
  ```python
  class LLMProvider(Protocol):
      async def draft_suggestion(self, context: InterviewContext, step: str) -> Suggestion: ...
      async def generate_document(self, facts: list[ConfirmedFact], tone: str) -> DraftDocument: ...
      async def health_check(self) -> bool: ...
  ```
  **주의**: `generate_document`는 카테고리 하나 분량의 `facts`를 받아 **한 번의 호출로 그 카테고리에 대한 문장들을 생성**한다. 여러 카테고리를 순회하며 이 함수를 반복 호출하는 것은 이 provider의 책임이 아니라 B의 `document_generator.py` 쪽 책임이다([person_B_frontend_backend/04_document_generation.md](../person_B_frontend_backend/04_document_generation.md) 참고) — provider 내부에서 카테고리를 순회하지 않도록 주의
- [ ] `Suggestion`, `DraftDocument` 데이터 클래스/Pydantic 모델 정의 (12절 프롬프트 출력 형식과 일치시킬 것: `draft_text`, `based_on`, `sentences: list[{text, fact_indices}]`). `based_on`의 정확한 구조는 B의 [02_interview_state_machine_api.md](../person_B_frontend_backend/02_interview_state_machine_api.md) 4절 "통일안"(`{"type": "record", "excerpts": [{"chunk_id", "text", "published_at"}]}` / `{"type": "generic_pattern"}`)을 그대로 따른다 — 여기서 임의로 다른 형태를 쓰지 않는다
- [ ] `ProviderUnavailableError`, `AllProvidersFailedError` 예외 클래스 정의

## 2. `LocalOllamaProvider` (`local_ollama.py`)

- [ ] Ollama HTTP API(`/api/generate` 또는 `/api/chat`) 호출 구현
- [ ] `draft_suggestion`: 0번에서 만든 `draft_suggestion` 템플릿을 렌더링해 호출, JSON 파싱해 `Suggestion`으로 반환
- [ ] `generate_document`: 0번에서 만든 `final_document` 템플릿을 인자로 받은 `facts`(단일 카테고리분)로 렌더링해 **한 번만** 호출 (카테고리 순회 없음 — 위 주의사항 참고)
- [ ] 타임아웃 설정: 생성 요청 20초, `health_check` 5초 (10-2)
- [ ] `health_check`: Ollama 헬스 체크 엔드포인트 또는 `/api/tags` 호출로 응답 여부만 확인
- [ ] 타임아웃/연결 실패 시 `ProviderUnavailableError` 또는 `TimeoutError` 발생시키도록 처리 (FallbackProvider가 이를 잡아서 다음 provider로 넘어감)
- [ ] 이 시점에는 `LOCAL_LLM_BASE_URL`을 `http://localhost:11434`로 두고 로컬에서만 테스트 (Cloudflare Tunnel은 [05_cloudflare_tunnel.md](05_cloudflare_tunnel.md)에서 나중에 연결)

## 3. `GeminiProvider` (`gemini_provider.py`)

- [ ] Google Gemini API 클라이언트 초기화 (`GEMINI_API_KEY` 환경변수 사용)
- [ ] `draft_suggestion`, `generate_document`을 동일한 프롬프트 템플릿으로 호출 (Provider가 바뀌어도 프롬프트 내용은 동일해야 함 — 12절 템플릿 재사용)
- [ ] `health_check`: 간단한 ping성 요청 또는 항상 true (Gemini는 API 키만 있으면 대부분 가용)

## 4. `FallbackProvider` (`fallback.py`)

- [ ] 10-2절 코드 그대로 구현: provider 리스트를 순회하며 실패 시 다음으로 넘어감
- [ ] `LLM_PROVIDER_ORDER` 환경변수(`local,gemini`)를 파싱해 provider 순서를 동적으로 구성
- [ ] 모든 provider 실패 시 `AllProvidersFailedError` → API 레이어에서 `503 AI 어댑터 전체 장애`로 변환 (9-6절 에러 포맷)

## 5. 환경변수 반영

- [ ] `backend/.env.example`에 10-4절 표의 변수 전부 추가: `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL_NAME`, `GEMINI_API_KEY`, `LLM_PROVIDER_ORDER`
- [ ] `backend/app/core/config.py`에서 이 변수들을 로딩하는 설정 클래스 작성

## 검증 기준

- [ ] `LOCAL_LLM_BASE_URL`을 로컬로 둔 상태에서 `FallbackProvider.draft_suggestion()`을 호출하면 Ollama가 실제로 응답한다
- [ ] 의도적으로 Ollama를 꺼둔 상태에서 같은 호출을 하면 자동으로 Gemini 응답이 돌아온다 (에러 없이)
- [ ] 둘 다 실패하도록 만들면(`GEMINI_API_KEY`를 잘못된 값으로) `AllProvidersFailedError`가 발생한다
