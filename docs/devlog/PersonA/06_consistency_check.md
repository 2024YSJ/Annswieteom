# A-6. 후처리 일관성 검증 devlog

체크리스트: `docs/checklists/person_A_infra_ai/06_consistency_check.md`
날짜: 2026-09-03
브랜치: `feature/consistency-check` (`dev`에서 분기)

---

## 구현 (`app/services/consistency_check.py`)

12-4절 코드를 그대로 옮기되, 파라미터 하나(`embedding_provider`)를 추가했다:

```python
async def check_sentence_consistency(
    sentence: str,
    cited_facts: list[ConfirmedFact],
    embedding_provider: EmbeddingProvider | None = None,
) -> bool:
    if not cited_facts:
        return False
    similarity = await max_cosine_similarity(sentence, [f.content for f in cited_facts], embedding_provider)
    return similarity >= settings.consistency_threshold
```

`cited_facts`는 ORM `app.models.confirmed_fact.ConfirmedFact`를 그대로 받는다 — B의 `document_generator.py`가 카테고리별 `confirmed_facts`를 DB에서 조회한 결과를 바로 넘기면 되고, 별도 변환 계층이 필요 없다.

`max_cosine_similarity`는 문장 하나와 fact 여러 개를 **한 번의 `embed()` 호출**로 같이 임베딩한다 (`[sentence, *fact_contents]`) — fact가 여러 개여도 임베딩 API를 여러 번 왕복하지 않는다. 코사인 유사도 자체는 numpy 없이 순수 파이썬으로 계산했다 — 이 프로젝트가 numpy를 직접 의존성으로 선언한 적이 없고(들어와 있다면 trafilatura 등의 전이 의존성일 뿐), 벡터 두 개 dot/norm 계산에 별도 라이브러리가 필요할 정도로 무거운 연산이 아니다.

## 핵심 결정 사항과 이유

**`embedding_provider`를 옵션 인자로 추가**: 명세서 12-4절 시그니처엔 없는 파라미터지만, 이게 없으면 이 함수를 실제 Ollama/Gemini 네트워크 호출 없이는 단위 테스트할 방법이 없다 — 체크리스트 자체가 "명백히 무관한 문장→false", "근거 요약 문장→true" 같은 구체적 단위 테스트 시나리오를 검증 기준으로 요구하고 있어서, 테스트 가능성이 시그니처 순수성보다 우선한다고 판단했다. 기본값이 `None`이라 `check_sentence_consistency(sentence, cited_facts)`처럼 스펙 그대로 호출해도 동작은 같다 — `document_generator.py`(B-4) 쪽에서는 이 인자를 그냥 생략하면 된다.

**`CONSISTENCY_THRESHOLD`를 `Settings`에 추가**(`consistency_threshold: float = 0.55`): 체크리스트가 "환경변수 또는 config 상수로 분리"를 요구했고, 이미 이 프로젝트의 다른 튜닝 가능 값(`local_llm_model_name` 등)이 전부 `Settings`를 통하고 있어 같은 자리에 뒀다.

## 임계값 튜닝 — 아직 미완료

체크리스트 2절(실제 생성 문장 10~20개로 사람 판단과 비교해 0.45~0.65 사이 조정)은 **아직 하지 않았다** — B-4(`document_generator.py`)가 없어서 실제로 생성된 문장 샘플 자체가 존재하지 않기 때문이다. 기본값 0.55(명세서 초기값)를 그대로 둔 채 다음 단계로 넘어간다. B-4가 실제 문장을 생성하기 시작하면 그 샘플로 튜닝하고 이 devlog를 갱신할 것.

## 테스트 전략

`tests/services/test_consistency_check.py` — `FakeEmbeddingProvider`(텍스트→고정 벡터 딕셔너리)로 실제 임베딩 호출 없이 8개 케이스 검증: 빈 `cited_facts`(임베딩 호출 자체가 없어야 함), 무관한 문장(직교 벡터→0.0), 일치하는 문장(동일 벡터→1.0), 여러 근거 중 최댓값 선택, `max_cosine_similarity`/`_cosine_similarity` 자체의 수치 정확성(직교/동일/영벡터 0-division 방지)까지. 전부 순수 함수 레벨이라 FastAPI/DB 없이 실행된다.

## 트러블슈팅

`pytest tests/`를 이 브랜치에서 전체로 돌리면 `tests/api/` 쪽 conftest가 `app.main`을 임포트하면서 [[project-b3-records-feature]]에서 이미 발견·수정한 "`-> None` + 204 조합이 이 Python/FastAPI 버전 조합에서 라우트 등록 자체를 깨뜨리는" 버그가 그대로 재현된다 — 그 수정이 아직 `feature/records-feature`에만 있고 `dev`엔 머지되지 않았기 때문. A-6은 API 레이어를 전혀 안 건드리므로(`tests/services/test_consistency_check.py`만 실행) 이 브랜치 자체의 검증에는 영향 없지만, B-4에서 `api/document.py`를 추가하는 순간 다시 막힐 것 — B-4 시작 전에 `feature/records-feature`를 `dev`로 먼저 머지하는 게 좋겠다.

## 남은 작업

- 임계값 실측 튜닝 (B-4가 실제 문장을 생성하기 시작한 뒤)
- `document_generator.py`(B-4)에서 `generated_sentences` row 생성 시마다 이 함수를 호출하도록 연결
