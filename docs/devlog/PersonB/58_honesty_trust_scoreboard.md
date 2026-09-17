# 58. 정직성 트러스트 스코어보드 (2026-09-16)

`feature/championship-showcase` 브랜치의 첫 기능. 참가 대회(챔피언십) 심사/발표
자리에서 "이 서비스가 실제로 근거 없이는 문장을 만들지 않는다"는 정직성
가드레일의 핵심 가치를 숫자로 즉시 보여줄 방법이 필요했다. DB에는 이미
`evidence_fact_ids`, `consistency_check_passed`, `edited_by_user`
(`generated_sentences`), `ai_draft_text`(`confirmed_facts`) 같은 값이 있었지만
어디에도 집계되어 노출되지 않고 있었다.

## 무엇을

- `backend/app/services/trust_score.py` 신규 — 순수 파이썬 집계(`TrustStats`).
  세션당 문장 수가 수십 개 수준이라 SQL 집계 대신 파이썬으로 계산하고,
  `evidence_fact_ids`가 SQLite/Postgres 양쪽에서 쓰는 제네릭 JSON 컬럼이라
  DB별 JSON 함수에 의존하지 않는 편이 이식성이 좋다는 판단.
  - `evidence_coverage_ratio`: 근거가 달린 문장 비율
  - `consistency_pass_rate`: 기계 일관성 검사를 통과한 비율
  - `ai_acceptance_rate`: 사용자가 손대지 않고 그대로 남긴 문장 비율(문서 단계)
  - `interview_ai_acceptance_rate`: AI가 제시한 초안(`ai_draft_text`)이 그대로
    확정된 비율(인터뷰 단계)
- `GET /sessions/{id}/trust-score` (세션별), `GET /trust-score/global`
  (인증 없이 접근 가능 — `FINAL` 상태 문서만 대상. DRAFT를 섞으면 "아직 손보는
  중"인 상태가 발표 지표를 왜곡하므로 의도적으로 제외)
- `document.py`의 비공개 조립 헬퍼(`_document_read` 등)를 `services/document_assembly.py`로
  추출 — 뒤이은 데모 모드(59)·공유 카드(61) 라우트가 동일 로직을 재사용할 수 있도록
  선행 리팩터링
- 프론트: `components/TrustScoreboard.tsx`, `lib/api/trust.ts`, `ResultSection.tsx`에 연결

## 검증

- `backend/tests/api/test_trust_score.py` 신규(68줄) — 세션/글로벌 두 엔드포인트,
  DRAFT 제외 여부, 분모 0(문장 없음)일 때 `None` 처리 등

## 남은 작업

- [ ] 배포된 사이트에서 실제 확정 문서 여러 건으로 `/trust-score/global` 수치가
      기대한 범위(대부분 근거 있음, 일관성 통과율 높음)로 나오는지 육안 확인

## 관련 커밋

- `e9c3bc9` feat: add honesty trust scoreboard (session + global)
