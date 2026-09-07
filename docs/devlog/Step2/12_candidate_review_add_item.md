# 활동 세분화 후보 목록에 새 항목 추가하기

세분화(activity_breakdown) 후보 검토 화면(고쳐 쓰기/제외하기)에서는 AI가 처음 제안한
개수보다 항목을 줄일 수만 있었지, 늘릴 방법이 없었다. 사용자 피드백: "지금 입력한 것보다
개수가 적어지면 수정할 수 있는 방법이 없어."

## 구현

- `InterviewChatThread.tsx`: 후보 카드 목록 아래에 "+ 새 항목 추가" 버튼 추가. `CandidateDraft`에
  `isManual?: boolean`을 얹어, 새로 추가된 빈 행은 곧바로 편집 모드로 열리게 했다(빈 문단을
  보여주고 "고쳐 쓰기"를 눌러야 하는 걸 피함).
- `InterviewSection.tsx`: `addManualCandidate()`가 `candidates` 배열 끝에 `index:
  prev.length`인 빈 draft를 추가한다. 이 index는 서버의 원래 `candidate_facts` 배열
  범위를 넘어간다 — 의도된 것.

## 발견한 버그 두 개 (백엔드)

기존 `interview_confirm`은 "AI가 제안한 개수만큼만 확인 가능하다"는 가정 위에 있었다.

1. **`activity_breakdown` 분기가 편집을 무시함**: 자식 카테고리 이름을 지을 때
   `candidate_facts[c.index]["content"]`(AI 원안)를 썼고 `c.final_text`(사용자가 확정한
   값)를 안 썼다 — "고쳐 쓰기"로 이름을 바꿔도 반영이 안 되는 기존 버그였다(이번에 발견).
   `c.final_text.strip()`로 교체.
2. **`invalid_candidate_index` 409가 범위 밖 index를 전부 거부함**: `0 <= index <
   len(candidate_facts)` 체크가 새로 추가한 행(index가 원래 후보 개수보다 큼)을 전부
   막았다. `index < 0`만 거부하도록 바꾸고, 범위 밖이면 `candidate = None`으로 두어
   "AI 근거 없음"으로 취급 — `source_type`은 무조건 `user_edited`, `fact_type`은
   `candidate["fact_type"]` 대신 항상 `pending["fact_type_hint"]`에서 가져오도록
   통일했다(candidate가 None이면 애초에 `candidate["fact_type"]`이 없으므로).

빈 문자열로 제출된 새 행(추가만 하고 안 채운 경우)은 조용히 건너뛴다.

## 검증

- `test_interview.py`: `test_confirm_with_negative_index_returns_409`(기존 out-of-range
  테스트를 음수 index로 교체 — 양수 out-of-range는 이제 유효한 케이스라서),
  `test_confirm_with_index_past_the_candidate_list_adds_a_manual_fact`,
  `test_activity_breakdown_review_can_edit_and_add_items_beyond_the_ai_list` 추가.
  백엔드 전체 160개 통과.
- 프론트 `tsc --noEmit`, `npm run lint` 클린.
- Playwright로 실제 브라우저 확인: 세분화 질문에 활동 2개("MABC 오픈소스 개발자 대회
  참여", "NAIS 해커톤 참여")로 답한 뒤 "+ 새 항목 추가"로 세 번째 항목("직접 추가한 공모전
  C")을 만들고 저장 → "다음" 제출 → `/interview/confirm`이 200으로 응답하며 새
  `current_category_id`로 넘어가는 것 확인(자식 카테고리 3개가 만들어졌다는 뜻). 로컬 LLM의
  카테고리 추출 결과가 실행마다 달라져서(가끔 카테고리 1개, 가끔 2개) 자동화 스크립트 자체는
  일회성으로만 썼고 커밋하지 않음.

## 남은 일
없음 — pytest + 브라우저 확인 모두 완료.
