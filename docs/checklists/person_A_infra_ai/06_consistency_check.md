# A-6. 후처리 일관성 검증 (정직성 가드레일의 마지막 방어선)

근거: 명세서 1-2절, 12-4절
선행 조건: [03_embedding_pipeline.md](03_embedding_pipeline.md) (코사인 유사도 계산에 임베딩 필요)
폴더: `backend/app/services/` (문서 생성 파이프라인과 맞물리는 부분이라 B의 `document_generator.py`와 인터페이스를 맞춰야 함)
브랜치: `feature/consistency-check` (`dev`에서 분기, 완료 후 `dev`로 PR)
시점: 2~3주차

> **왜 필요한가**: 정직성 가드레일은 "confirmed_facts만 입력으로 쓴다"는 데이터 흐름 강제만으로는 완전하지 않다 — LLM이 프롬프트 지시를 무시하고 확정 사실에 없는 내용을 지어낼 가능성이 항상 있다. 이 검증은 그런 경우를 사후에 잡아내는 마지막 방어선이다.

## 1. 함수 구현

- [x] 12-4절 코드 그대로 구현 (파라미터 하나 추가 — 아래 devlog 참고):
  ```python
  async def check_sentence_consistency(
      sentence: str, cited_facts: list[ConfirmedFact]
  ) -> bool:
      if not cited_facts:
          return False
      similarity = await max_cosine_similarity(sentence, [f.content for f in cited_facts])
      return similarity >= CONSISTENCY_THRESHOLD
  ```
- [x] `max_cosine_similarity`: 생성된 문장과 인용된 각 fact.content를 임베딩해 코사인 유사도를 계산하고 최댓값을 반환 (03_embedding_pipeline.md의 provider 재사용)
- [x] `CONSISTENCY_THRESHOLD`를 설정값(환경변수 또는 config 상수)으로 분리, 초기값 0.55

## 2. 임계값 튜닝

- [ ] 실제 생성된 문장 샘플 10~20개를 놓고 사람이 봤을 때 "근거와 맞다/틀리다"를 판단한 것과, 함수가 내놓은 결과를 비교 — **아직 안 함**, 실제 생성 샘플이 몇 개 안 쌓임(B-5 실 브라우저 테스트 2건 정도)
- [ ] 임계값을 0.45~0.65 범위에서 조정하며 오탐(맞는데 걸러짐)/누락(틀린데 통과) 균형 확인 — 기본값 0.55 그대로
- [ ] 최종 확정한 임계값과 그 근거를 코드 주석 또는 팀 공유 메모로 남김

## 3. 문서 생성 파이프라인과의 연결

- [x] `generated_sentences` row 생성 시마다 이 함수를 호출해 `consistency_check_passed` 값 채우기 — 이 호출 지점은 B가 만드는 `document_generator.py` 안에 있으므로, 함수 시그니처를 먼저 B와 합의
- [x] 검증 실패 문장은 **자동 삭제하지 않고** `consistency_check_passed=false`로만 저장 (12-4절 — 프론트가 "확인이 더 필요한 문장"으로 별도 표시)

## 검증 기준

- [x] 명백히 근거와 무관한 문장(테스트용으로 일부러 만든 문장)을 넣으면 `false`가 반환된다 — 유닛 테스트(fake embedding)로 확인
- [x] 근거를 그대로 요약한 문장을 넣으면 `true`가 반환된다 — 유닛 테스트(fake embedding)로 확인
- [x] `cited_facts`가 빈 리스트면 무조건 `false` (근거 없는 문장은 항상 걸러짐) — 유닛 테스트로 확인
- [x] 실제 카테고리 여러 개로 문서를 생성했을 때, 근거 없이 지어낸 문장이 있다면 `consistency_check_passed=false`로 표시되어 놓치지 않는다 — B-5 실 브라우저 테스트에서 실제 `bge-m3` 임베딩으로 문장 하나가 실제로 "확인이 더 필요한 문장"으로 걸러지는 것을 직접 확인(자동 삭제 안 되고 화면에 그대로 표시됨)
