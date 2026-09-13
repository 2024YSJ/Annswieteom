# 42. "공백기 채우기" → "커리어 채우기" 문구·프롬프트 정리 (2026-09-13)

이전에 커밋 전 상태로 남아 있던 "공백기 채우기"→"커리어 채우기" 부분 리네이밍
(사용자 노출 문구만 일부 변경, 약 23개 파일)을 마저 완료했다. 사용자가 범위를
명시적으로 확정했다: 내부 식별자(`GapPeriod`, `kind='gap_fill'`, `gap_start`/
`gap_end`)와 DB 스키마는 그대로 두고, **사용자 노출 문구와 LLM 프롬프트 문구만**
정리한다. 기간 입력 단계(`POST /sessions/{id}/period`)도 FSM 첫 관문·`GapPeriod`
not-null 제약으로 구조적으로 얽혀 있어 이번 범위에서는 필수로 유지하고, 문구와
논리 근거만 중립화했다.

## 완료

### 프론트엔드 남은 문구
`app/layout.tsx`(메타 설명·keywords), `app/page.tsx`(히어로 서브타이틀/eyebrow —
flow-title/resume-card는 이전 작업에서 이미 반영됨), `opengraph-image.alt.txt`,
`PeriodSection.tsx`(기간 입력 질문 문구, 확인 말풍선), `ExampleDocumentModal.tsx`,
`PreferenceEditor.tsx`, `ProfileAttributesEditor.tsx`, `ResultSection.tsx`,
`logo/generate_icons.py`(아이콘 서브타이틀) — 전부 문맥에 맞는 자연스러운 한국어로
정리했다("공백기가"→"커리어가" 같은 기계적 조사 치환은 피함).

### 백엔드 LLM 프롬프트
`.jinja` 10개 파일의 공통 도입부("너는 구직 공백기 경력 재구성을 돕는
어시스턴트다.")를 "너는 사용자의 커리어 경험을 재구성하는 걸 돕는 어시스턴트다."로,
`[USER]` 섹션의 "공백 기간: {{ gap_start }} ~ {{ gap_end }}" 라벨을 "기간: ..."으로
통일했다(변수명 `gap_start`/`gap_end`는 안 건드림).

`probe_activity_question.jinja`의 핵심 논리 근거 한 줄을 다시 썼다:
> "쉬었다"도 유효한 답이라는 걸 열어둬라 — **이 서비스의 이름 자체가 그 전제 위에
> 있다.**
→
> "특별한 활동이 없었다"도 유효한 답이라는 걸 열어둬라 — **판단하지 말고 있는
> 그대로 받아들여라.**

`interview_followup_question.jinja`의 모호한 답 예시에 "그냥 그랬다"(실사용
테스트에서 실제로 나온 표현)를 "그냥 쉬었다" 옆에 추가했다.

### 정합성 확인
지난 조사에서 `job-search-flow.spec.ts` 주석이 다른 e2e 스펙과 다르게 "공백기
채우기"로 남아 있다는 지적이 있었으나, 실제 확인 결과 이미 "커리어 채우기"로
일치돼 있었다 — 조치 불필요.

### e2e 테스트 동기화
`PeriodSection.tsx`의 질문 문구/확인 말풍선 변경에 맞춰
`session-flow.spec.ts`의 세 어서션(질문 문구, 확인 말풍선 2곳)을 같은 커밋에서
고쳤다 — 문구만 바꾸고 테스트를 안 고치면 e2e가 깨진다.

## 범위 밖으로 남긴 것 (의도적)

- DB 스키마/마이그레이션, `GapPeriod`/`GapPeriodRead`/`GapPeriodSet`,
  `gap_periods` 테이블, `kind='gap_fill'`, `linked_gap_session_id`,
  `gap_start`/`gap_end` — 전부 그대로.
- 사용자 비노출 코드 주석/docstring(`coverage.py`, `activity_category.py`,
  `interview_orchestrator.py`, `PreferenceEditor.tsx` 상단 설명 등 다수) — 식별자가
  안 바뀌므로 "공백기"를 언급하는 설명 자체는 여전히 정확하다.
- `docs/devlog/**`(과거 기록), `docs/specs/**`, `docs/architecture.md`,
  `README.md` — 개발자 문서는 이번 범위 밖.
- e2e/테스트의 임의 테스트 데이터(`"내 첫 공백기 세션"`, `"이직 준비 공백기"`) —
  앱 문구가 아니라 테스트가 스스로 지어낸 값이라 무관.

## 핵심 결정과 이유

**기계적 문자열 치환이 아니라 문맥별로 다시 썼다.** "공백기가"→"커리어가"처럼
조사가 어색해지는 치환을 피하려고, grep으로 찾은 각 위치를 직접 읽고 자연스러운
한국어로 바꿨다 — 이미 끝난 "공백기 채우기"→"커리어 채우기" 복합명사 치환과 같은
결.

**`probe_activity_question.jinja`만 논리를 다시 썼다.** 나머지 프롬프트는 gap
특유의 가정이 없어 도입부/라벨만 바꾸면 충분했지만, 이 파일의 "쉬었다도 유효한
답"이라는 지시는 서비스 이름("안 쉬었음")의 반어법 전제에 직접 기댄 근거였다 —
커리어 채우기가 "쉬었어도 됨"만이 아니라 어떤 활동이든 다루게 되므로, 서비스 이름
의존을 빼고 "판단하지 말라"는 일반 원칙으로 바꿨다.

**기간 입력 단계는 그대로 필수로 뒀다.** `GapPeriod`가 not-null이고 FSM의 첫
상태(`PERIOD_INPUT`)라 이걸 선택적으로 만들려면 새 세션 종류(`job_search`가 이미
기간을 건너뛰는 것과 비슷한 패턴)와 여러 곳의 `scalar_one()` 방어 코드가
필요하다 — 사용자가 이번 범위에서는 제외하기로 결정했다.

## 검증

pytest 507개 전체 통과(문구/프롬프트만 바꿨으므로 회귀 없음 — 사전 확인:
`test_prompt_templates.py`는 카테고리 이름 존재만 확인하고 "공백기" 문자열을
직접 assert하지 않음). 프론트 `tsc --noEmit` 통과. `grep -rn "공백기"
frontend/ backend/app/`로 최종 스윕해 범위 밖 항목(코드 주석/임의 테스트 데이터)
외에는 남은 게 없음을 확인.

e2e는 실제 dev 서버+원격 dev Supabase가 떠 있어야 해서 이번엔 실행하지 않고,
변경한 문자열이 `session-flow.spec.ts`의 어서션과 정확히 일치하는지 grep으로
수동 대조했다 — 로컬에서 `npm run test:e2e`로 한 번 더 확인 권장.

## 관련 커밋

- (머지 전 — 지난 턴의 Case D/G 수정과 함께 통합 커밋 예정)

## 남은 작업

- [ ] `frontend/e2e/session-flow.spec.ts` 실제 실행 확인(dev 서버 필요, 이번엔 미실행)
- [ ] `GapPeriod`를 선택적으로 만드는 흐름 개편(새 세션 kind 등)은 이번에 범위 밖으로
      결정됨 — 필요성이 재확인되면 별도 작업으로.
