# Phase 2. 통합 채팅 UI devlog

관련 spec: [docs/specs/phase2_unified_chat_ui.md](../../specs/phase2_unified_chat_ui.md)
날짜: 2026-09-03

---

[Phase 1](06_phase1_guest_sessions_and_sidebar.md)과 마찬가지로 원래 마일스톤 체크리스트에는 없던 항목이라 대응하는 checklist 파일이 없다. 백엔드는 한 줄도 안 건드렸다 — 순수 프론트엔드 재배치.

## 완료 항목

- 예전 5개 라우트(`/sessions/{id}/{period,categories,records,interview,result}`) 삭제, `frontend/app/sessions/[id]/page.tsx` 하나로 통합
- 5개 섹션 컴포넌트(`PeriodSection`/`CategorySection`/`RecordsSection`/`InterviewSection`/`ResultSection`) 신규 — 각각 completed(요약 말풍선)/active(실제 폼) 두 모드
- `InterviewChatThread`를 카테고리 1개 전용에서 여러 카테고리를 이어 보여주도록 일반화(카테고리 구분선 추가)
- `RecordUploadPanel`에 `onRecordsChange` 콜백 추가해서 "기록물 없이 넘어가기"/"다음으로" 버튼 문구가 실제 업로드 여부를 반영하도록 개선
- `session-routes.ts`의 `pathForStatus` 삭제, `INTERVIEW_STATUSES`/`RESULT_STATUSES` 공용 상수로 대체
- `guest.spec.ts` URL 검증 갱신 + 신규 `session-flow.spec.ts` 추가(기간→카테고리→기록물스킵→인터뷰 진입까지 실제 로컬 백엔드로 주행, `interview/next`만 목킹)
- 실 로컬 Ollama(`qwen2.5:14b`)로 전체 플로우(기간→카테고리→기록물→인터뷰 3문항→문서생성→최종확정→내보내기) 수동 브라우저 주행 2회 재확인(1회차에서 버그 발견 후 수정, 2회차에서 재확인)

## 핵심 결정 사항과 이유

**"완료/진행 중" 두 모드를 갖는 섹션 모델을 택하고, 범용 채팅 메시지 버스는 도입하지 않음.** 백엔드가 순수한 순방향 상태머신이라 지금 당장은 메시지 스트림 추상화가 과설계라고 판단했다. Plan 서브에이전트에게 이 판단을 검증받았고, Phase 3(자유 대화로 카테고리 추출)가 들어올 때 그 부분에 한해 별도로 메시지 모델을 도입하고 지금의 섹션 모델과 공존시키면 된다는 결론을 얻었다.

**아직 도달하지 않은 섹션은 JSX에서 아예 렌더링 자체를 안 함(숨기지 않음).** 예전엔 페이지 이동마다 완전히 새로 마운트됐는데, 한 페이지로 합치면서 "안 보이게 숨겨두고 계속 마운트"를 택하면 `fetchedForRef` 같은 중복 방지 effect가 화면에 없는 상태에서 뒤에서 돌 위험이 있었다. 조건부 렌더링 자체를 빼는 쪽으로 설계해서 이 위험을 원천 차단했다.

**인터뷰 섹션은 결과 단계에서도 계속 렌더링됨(의도적).** `interviewActive || resultActive`일 때 `InterviewSection`을 계속 보여줘서, 결과 화면에 도달한 뒤에도 스크롤을 올리면 이전에 확인한 사실들이 그대로 남아있게 했다 — Claude Desktop처럼 대화 기록이 안 사라지는 게 목표였으므로.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| 실 Ollama로 전체 플로우를 수동 주행했더니, 3번째 사실 확인 후(문서 생성까지 성공적으로 끝났는데도) 화면에 "새로고침으로 이전 AI 초안을 다시 보여드릴 수 없어요. \"\"에 대한 답변을 직접 적어주세요" 폴백 폼이 계속 떠 있음 | `InterviewSection`의 `isConfirmStepWithoutDraft = !DRAFT_STEPS.has(status) && !pending` 조건이, 예전(페이지가 인터뷰 상태일 때만 존재)엔 안전했지만 이번 설계에서 `InterviewSection`이 `RESULT_GENERATE`/`RESULT_REVIEW` 단계에서도 계속 마운트되면서 깨짐 — 이 두 상태도 "DRAFT가 아니고 pending도 없음"을 만족해버려서 조건이 잘못 참이 됨 | `CONFIRM_STEPS`(`*_CONFIRM` 3개) 집합을 새로 만들어 `isConfirmStepWithoutDraft = CONFIRM_STEPS.has(status) && !pending`로 좁힘. **교훈**: 컴포넌트를 "특정 상태에서만 존재"에서 "여러 상태에 걸쳐 계속 마운트"로 바꿀 때, 그 컴포넌트 내부의 "이것도 아니고 저것도 아니면"류 소거법 조건은 새로 넓어진 상태 범위에서 다시 검증해야 한다 — 자동화 테스트(`session-flow.spec.ts`)는 인터뷰 진입까지만 다뤄서 이 버그를 못 잡았고, 실 LLM으로 끝까지 수동 주행해보고서야 발견함 |
| `next build`가 이미 삭제한 5개 라우트의 타입 선언을 못 찾겠다며 실패(`Cannot find module '.../period/page.js'`) | `.next/dev/types/validator.ts`에 이전 `next dev` 실행이 만든 오래된 라우트 타입 캐시가 남아있었음 | `.next` 디렉터리를 지우고 재빌드 |
| Playwright로 `interview/next`만 네트워크 레벨에서 목킹해서 인터뷰 confirm까지 자동화하려던 최초 계획이 실은 동작 불가능함을 검증 중 발견 | `interview/next`를 가로채면 그 요청이 실 백엔드에 절대 도달하지 않아서, 서버 쪽 `DRAFT→CONFIRM` 전이와 `pending_draft` 기록이 실제로는 일어나지 않음. 그 상태에서 `interview/confirm`을 실제로 호출하면 서버는 여전히 `FREQ_DRAFT`인 걸로 알고 있어서 `409 no_pending_draft`/`step_mismatch`로 거부됨. `GET /sessions/{id}`도 같이 목킹해서 진행을 흉내 내는 방법도 검토했으나, 그러면 상태머신 전체를 테스트 안에 다시 구현하는 꼴이라(이미 백엔드 pytest가 커버 중인 로직의 신뢰할 수 없는 사본) 포기 | `session-flow.spec.ts`는 인터뷰 섹션 진입(카테고리 구분선 + 목킹된 초안 렌더링 확인)까지만 자동화하고, confirm 클릭 이후는 (a) 백엔드 pytest의 기존 상태머신 테스트, (b) 실 Ollama로 끝까지 가는 수동 브라우저 주행 — 이 두 가지로 커버 범위를 명확히 나눔 |

## 남은 작업

없음 — Phase 2 범위 전체 완료(자동 테스트 통과, 실 LLM으로 전체 플로우 수동 재확인 완료). 다음은 Phase 3(카테고리 직접 선택 제거, 자유 대화에서 AI가 키워드 추출) — 착수 시 별도 spec 문서 작성 예정.
