# A-2. LLM 어댑터 레이어 devlog

체크리스트: `docs/checklists/person_A_infra_ai/02_llm_adapter_layer.md`
날짜: 2026-09-01
커밋: `9815a12`, `501305f`

---

## Protocol 기반 인터페이스 (`base.py`)

`LLMProvider`를 `typing.Protocol`로 선언했다. ABC 상속 대신 Protocol을 쓴 이유는, 테스트에서 mock provider를 만들 때 상속 없이 duck typing만으로 호환되기 때문이다. `@runtime_checkable`을 붙여 `isinstance(obj, LLMProvider)` 확인도 가능하게 했다.

반환 타입은 `@dataclass`로 정의했다. `Suggestion`은 `draft_text`(문자열)와 `BasedOn`(출처 정보)을 가지고, `DraftDocument`는 `SentenceWithEvidence` 리스트를 담는다. `BasedOn.type`은 `"record"` 또는 `"generic_pattern"` 두 값만 허용된다 — B의 [`02_interview_state_machine_api.md`](../../checklists/person_B_frontend_backend/02_interview_state_machine_api.md) 4절에서 정의한 통일안을 그대로 따랐다.

## 프롬프트 파일 관리

프롬프트를 코드에 하드코딩하지 않고 `backend/app/prompts/` 아래 Jinja2 템플릿 파일로 분리했다. 이렇게 하면 프롬프트를 수정할 때 Python 코드를 건드릴 필요가 없고, 두 provider(LocalOllama, Gemini)가 동일한 파일을 공유한다.

`draft_suggestion.jinja`는 `{% if record_excerpts %}` 블록으로 근거 자료가 있을 때와 없을 때의 지시를 분기한다. `final_document.jinja`는 `{% for fact in confirmed_facts %} [{{ loop.index }}]` 로 사실 번호를 매겨 모델이 `fact_indices` 배열을 채울 때 참조할 수 있게 한다.

## LocalOllamaProvider — /api/generate → /api/chat 전환

초기 구현은 Ollama의 `/api/generate`(단일 문자열 프롬프트)를 썼다. 모델 비교 테스트에서 이 방식으로는 두 모델 모두 JSON 스키마를 지키지 못한다는 걸 확인하고, `/api/chat`(messages 배열)으로 교체했다. 핵심 차이는 system 메시지를 별도로 지정할 수 있다는 점이다:

```python
payload = {
    "model": self._model,
    "messages": [
        {
            "role": "system",
            "content": "... Always respond in Korean. Output JSON only.",
        },
        {"role": "user", "content": prompt},
    ],
    "stream": False,
    "format": "json",
}
resp = await client.post(f"{self._base_url}/api/chat", json=payload)
return resp.json()["message"]["content"]   # /api/generate는 ["response"]
```

응답 키도 `/api/generate`의 `response`에서 `/api/chat`의 `message.content`로 달라진다. 타임아웃은 생성 요청 20초, health_check용 `/api/tags` 조회 5초로 설정했다.

## GeminiProvider

`google-generativeai` SDK의 `generate_content_async()`를 사용해 비동기로 호출한다. `GenerationConfig(response_mime_type="application/json")`을 설정하면 Gemini가 JSON 형식만 출력하도록 강제된다. LocalOllamaProvider와 동일한 Jinja2 템플릿을 렌더링해서 프롬프트를 만든다 — provider가 달라도 동일한 프롬프트 내용을 보장하기 위함이다.

## FallbackProvider

`LLM_PROVIDER_ORDER=local,gemini` 환경변수를 `,`로 분리해 provider 순서를 런타임에 결정한다:

```python
mapping = {"local": LocalOllamaProvider(), "gemini": GeminiProvider()}
order = [p.strip() for p in settings.llm_provider_order.split(",")]
self.providers = [mapping[name] for name in order if name in mapping]
```

각 method에서는 provider를 순서대로 시도하고 `TimeoutError`나 `ProviderUnavailableError`가 나면 다음으로 넘어간다. 전부 실패하면 `AllProvidersFailedError`를 던진다 — API 레이어에서 이를 잡아 503으로 변환할 예정이다 (B가 `app/api/` 구현 시 처리).

## 남은 작업

- `GEMINI_API_KEY`를 `.env`에 채워 폴백 실제 동작 확인
- Ollama를 강제로 끈 상태에서 Gemini로 자동 전환되는지 E2E 테스트
- 마일스톤 2에서 B의 인터뷰 API와 연동 후 `draft_suggestion` 실제 흐름 확인
