# 35~37단계 — 기록물 삭제, 문단 삭제/이동 성능, 카테고리 소분류

## 35단계 — 올린 기록물을 지울 수 있게

기록물 삭제 API(`DELETE /records/{id}`)는 이미 있었는데 `RecordsSection` UI에 버튼이 없었다.
`RecordStatusRow`에 "삭제" 버튼과 자체 `isDeleting`/에러 상태를 추가하고, `RecordsSection`에
`removedIds` 로컬 상태를 둬서 삭제 즉시 목록에서 사라지도록(백엔드 재조회를 기다리지 않고)
처리했다. 지나간 카테고리든 현재 카테고리든 화면에 보이는 모든 기록물에 동일하게 적용된다.

## 36단계 — "문단 이동이 너무 오래 걸린다" + 문단 삭제 추가

**성능 원인**: 이동 자체는 가벼운 조작인데, 이동 후 프론트가 문서 전체를 다시 불러오면서
`GET /document`가 문장마다 근거 인용을 조회하는 `resolve_fact_citation`이 **호출할 때마다
완전히 새 DB 커넥션을 열고 있었다** — 근거 사실이 여러 개면 그 개수만큼 원격 Supabase에
새 연결을 맺었다 끊었다를 반복. LLM/정합성 검사와는 무관한 순수 커넥션 오버헤드였다.
`resolve_fact_citations`(복수형)로 바꿔 이미 열린 세션을 재사용하고, 문장 하나의 근거들을
한 쿼리로 묶어 가져오도록 고쳤다.

**문단 삭제**: `DELETE /document/paragraphs/{id}` 추가, 프론트에 "문단 삭제" 버튼 +
`window.confirm()`(세션 삭제 때 쓰던 패턴 재사용) 추가. 구현 중 진짜 버그를 하나 잡았다 —
`GeneratedParagraph.sentences`에 ORM 삭제 cascade가 없어서, `db.delete(paragraph)`만 하면
SQLAlchemy가 문장을 지우는 대신 **FK를 NULL로 만들어 "제목 없는 미아 문단"으로 둔갑**시켰다
(테스트로 바로 잡음). merge-next처럼 재배치가 필요 없으므로, 문장들을 명시적으로 먼저
`db.delete()`한 뒤 문단을 지우는 방식으로 고쳤다.

## 37단계 — 질문 심층화(A+D) + 카테고리 내부 소분류

첨부된 실제 생성 문서에서 "study" 카테고리(CS336 강의 + Claude Code 가이드 학습)가 "무엇을
했다"만 나오고 정확히 뭘 배웠는지/어떻게 활용했는지가 안 나오는 문제가 발견됐다. 원인은
두 가지: ① 고정 질문 자체가 "내용"을 안 묻고, AI 드릴다운도 "왜"(동기)만 캐묻도록 튜닝돼
있었다. ② 카테고리 하나에 서로 다른 활동(CS336, Claude Code)이 섞여 있어도
`next_base_question`이 카테고리 전체 단위로 "이 fact_type은 답변됨"을 추적해서, 근거가
풍부한 쪽 얘기만 하고 카테고리가 끝나버렸다 — "공모전"을 여러 개 했을 때도 같은 증상.

**A (질문 심층화)**: `study`/`project`/`freelance`/`other` 4개 타입에 "구체적으로 어떤
내용을 배우셨고 어떻게 활용해보셨나요?" 류의 5번째 고정 질문을 추가. `part_time` 등
나머지는 기존 질문이 이미 그 도메인에서 충분히 구체적이라 손대지 않았다.

**D (충분성 강화)**: `interview_sufficiency.jinja`에 "내용과 실제 활용이 안 드러났으면
sufficient는 false" 기준 추가.

**소분류**: 새 테이블이나 새 상태머신 없이, `ActivityCategory`에 자기참조 FK
`parent_category_id`와 `activity_split_checked` 플래그만 추가해서 소분류를 "부모가 있는
ActivityCategory 행"으로 표현했다. 이러면 질문은행 조회, `questions_asked` 카운팅,
`confirmed_facts.category_id`, 문서 생성까지 기존 코드가 거의 그대로 재사용된다 — 손봐야
했던 건 카테고리 순회(`interview_orchestrator._walk_order`)가 부모 자리에 자식들을
끼워 넣도록 트리를 인식하게 만드는 것뿐이었다.

카테고리마다 실제 콘텐츠 질문 전에 "이 카테고리 안에 서로 다른 개별 활동이 여러 개 있나요?"
를 한 번(예산에 안 들어감) 묻고, 2개 이상 나오면 그 자리에서 자식 카테고리들을 만들어
그리로 들어간다. 자식은 생성 시점에 `activity_split_checked=True`로 시작해 재귀적으로
다시 쪼개려 들지 않는다. 자식은 별도 기록물 요청 단계를 안 가지므로(기록물은 RECORD_UPLOAD
단계에서만 첨부 가능하도록 이미 막아뒀음), **부모 카테고리의 기록물 풀을 공유**하도록
`chunk_search`에 부모 폴백을 추가했다(사용자 확정 사항).

### 트러블슈팅
- 새 fact_type(`content_application`, `technical_detail`)을 추가하면서
  `confirmed_facts.fact_type`의 DB CHECK 제약도 같이 넓혀야 했다 — 모델의 파이썬 튜플만
  고치고 마이그레이션을 빠뜨리면 프로덕션에서 그대로 500이 난다(이전 마이그레이션 누락
  사고들과 같은 패턴이라 이번엔 처음부터 같이 챙겼다).
- 기존 인터뷰 테스트 전부가 "카테고리 진입 직후 첫 `/interview/ask`가 곧바로 실제 고정
  질문을 반환한다"고 가정하고 있어서, 새 "여러 활동 있나요?" 턴이 그 가정을 깼다 —
  `_advance_to_first_category`가 내부적으로 이 턴을 "하나뿐이에요"로 자동 스킵하도록 고쳐
  대부분의 기존 테스트를 그대로 통과시키고, 실제 분기(2개 이상 응답)를 검증하는 테스트는
  스킵 없는 `_advance_to_interviewing`을 새로 만들어 따로 작성했다.
- 실제 로컬 LLM(qwen2.5:3b)으로 "CS336 lecture videos and the Claude Code guide"를 답해서
  실제로 두 개의 자식 카테고리로 쪼개지는 것, 자식이 자기 몫의 새 5번째 질문까지 정상적으로
  받는 것까지 curl로 확인했다.

## 남은 일
- 이 브랜치를 머지하면 `f1a2b3c4d5e6`(소분류 컬럼), `a2b3c4d5e6f7`(fact_type 확장) 두
  마이그레이션을 프로덕션 Supabase에도 적용해야 한다.
- 소분류는 부모의 기록물 풀을 공유하는 것으로 범위를 좁혔다 — 소분류 전용 기록물 요청
  단계는 필요성이 확인되면 후속 작업으로 남겨뒀다.
- `frontend/e2e/session-flow.spec.ts`는 이번 작업 이전부터 이미 오래된 UI 문구/첨부 위치를
  가정하고 있어 실행하면 깨질 것으로 보인다 — 이번 변경으로 새로 깨진 건 아니지만, 언젠가
  손볼 필요가 있다.
