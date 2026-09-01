# A-2. LLM 어댑터 레이어 devlog

체크리스트: `docs/checklists/person_A_infra_ai/02_llm_adapter_layer.md`
브랜치: `feature/llm-adapter` → `dev` PR 대기 중
날짜: 2026-09-01
상태: 코드 완료 / PR 미머지

## 완료 항목

### 프롬프트 템플릿 (12절)

- [x] `backend/app/prompts/draft_suggestion.jinja` — 카테고리별 초안 (근거 자료 우선 반영, based_on 구분)
- [x] `backend/app/prompts/final_document.jinja` — STAR 구조 문서 생성 (정직성 가드레일 — 확정된 사실만 인용)
- [x] 두 파일 모두 Jinja2 렌더링, 코드 하드코딩 없음

### 공통 인터페이스 (`base.py`)

- [x] `LLMProvider` Protocol (`draft_suggestion`, `generate_document`, `health_check`)
- [x] `InterviewContext`, `ConfirmedFact`, `RecordExcerpt` 데이터클래스
- [x] `Suggestion` (draft_text + BasedOn), `DraftDocument` (sentences 리스트) 반환 타입
- [x] `BasedOn` — type: "record" | "generic_pattern", excerpts 리스트
- [x] `ProviderUnavailableError`, `AllProvidersFailedError` 예외 클래스

### LocalOllamaProvider (`local_ollama.py`)

- [x] Ollama `/api/chat` 엔드포인트 호출 (system/user 메시지 분리)
- [x] 타임아웃: 생성 20초, health_check 5초
- [x] Jinja2로 프롬프트 파일 렌더링
- [x] 타임아웃/연결 실패 시 `ProviderUnavailableError` 발생

### GeminiProvider (`gemini_provider.py`)

- [x] `google-generativeai` SDK, `gemini-1.5-flash` 모델
- [x] `response_mime_type="application/json"` 설정
- [x] 동일한 Jinja2 프롬프트 재사용

### FallbackProvider (`fallback.py`)

- [x] `LLM_PROVIDER_ORDER` 환경변수 파싱으로 provider 순서 동적 구성
- [x] `TimeoutError` / `ProviderUnavailableError` 잡고 다음 provider로 넘어감
- [x] 전체 실패 시 `AllProvidersFailedError` → API 레이어에서 503으로 변환 예정

## 핵심 결정 사항

**`/api/generate` → `/api/chat`으로 변경** (`501305f`):
- 모델 비교 테스트에서 flat prompt 방식은 두 모델 모두 JSON 스키마를 지키지 못함
- system 메시지로 "한국어로, JSON만 출력" 지시를 분리하면 품질이 대폭 향상됨
- `local_ollama.py`의 `_generate()` 내부를 `/api/chat` 방식으로 교체

## 커밋

- `9815a12` feat: implement LLM adapter layer with local/Gemini/fallback providers
- `501305f` fix: switch Ollama to /api/chat and confirm qwen2.5:14b as primary model

## 검증 기준 (미완 — Ollama 실행 중일 때 수동 확인 필요)

```python
import asyncio
from app.services.llm.fallback import FallbackProvider

provider = FallbackProvider()
asyncio.run(provider.health_check())   # True 이어야 함

# Ollama 끈 상태에서 → Gemini 자동 폴백 확인
# 둘 다 실패 → AllProvidersFailedError 확인
```

## 남은 작업

- [ ] GitHub PR `feature/llm-adapter` → `dev` 머지
- [ ] `GEMINI_API_KEY` `.env`에 채우고 폴백 실제 동작 테스트
- [ ] 마일스톤 2에서 `draft_suggestion` 실제 API 연동 후 E2E 확인
