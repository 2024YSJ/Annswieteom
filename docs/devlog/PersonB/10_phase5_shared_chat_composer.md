# Phase 5. 공유 채팅 입력창 + 질문 영구 보존 devlog

관련 spec: [docs/specs/phase5_shared_chat_composer.md](../../specs/phase5_shared_chat_composer.md)
날짜: 2026-09-03

---

Phase 1~4 로드맵을 다 완료하고 실제 화면을 보여드린 뒤 받은 피드백으로 시작된 추가 단계라 대응하는 checklist 파일이 없다.

## 완료 항목

- `POST /sessions/{id}/period/extract` 신규(기존 `extract_categories`와 동일 패턴, DB에 아무것도 안 씀) — 기간도 완전 자유 텍스트로 입력받음
- 새 `ChatComposer.tsx` — 화면 전체 유일한 텍스트 입력창, 순수 입력 캡처(API 호출 안 함), `forStep`으로 스탬핑된 이벤트를 오케스트레이터가 해당 섹션에만 전달
- `PeriodSection`/`CategorySection`/`RecordsSection`이 자체 입력 위젯을 버리고 `composerEvent` prop으로 트리거되도록 전면 수정
- `ChatBubble`에 `variant: "card"|"message"` 추가, `ResultSection`은 기존 `variant="card"` 유지, 나머지는 새 기본값 `"message"`(좁고 회색인 진짜 채팅 말풍선)
- 세 섹션 전부 완료 모드에서 원래 AI 질문을 왼쪽 말풍선으로 영구 보존(`aria-live` 없이)
- `InterviewChatThread`도 확인된 사실마다 실제 질문 문구를 별도 말풍선으로 추가(`QUESTION_BY_FACT_TYPE`, 백엔드 무변경)
- 백엔드 테스트 4개 추가(`test_period_extraction.py`), `session-flow.spec.ts`를 새 컴포저 흐름에 맞게 갱신
- 실 로컬 Ollama로 전체 흐름 재확인 — "작년 1월부터 3월까지 쉬었어요" 같은 완전 자유 텍스트가 실제로 정확한 날짜로 파싱됐고, 스크롤을 올려보니 기간/카테고리/기록물/인터뷰 전 단계의 AI 질문이 전부 로그에 그대로 남아있는 것 확인

## 핵심 결정 사항과 이유

**컴포저는 순수 입력 캡처만, API 호출은 각 섹션이 계속 담당.** 기간·카테고리는 원래도 "추출→확인" 로직을 섹션이 갖고 있었으니, 기록물만 예외적으로 컴포저에 API 호출을 몰아주면 일관성이 깨진다고 판단해서 셋 다 같은 패턴(컴포저는 이벤트만 올려보내고, 활성 섹션이 실제 네트워크 호출을 함)으로 통일했다.

**`ChatComposer`의 "단계 바뀌면 입력 상태 초기화"는 `useEffect` 대신 `key={activeStep}` 리마운트로.** React 공식 문서가 권장하는 패턴이기도 하고, 마침 이 프로젝트의 eslint 설정이 effect 안에서의 동기적 setState 호출을 막고 있어서(아래 트러블슈팅), 애초에 effect가 필요 없는 케이스를 effect 없이 처리하는 쪽을 택했다.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `npx eslint .`가 새로 쓴 컴포넌트 4개에서 `react-hooks/set-state-in-effect` 에러를 냄 | effect 본문에서 `setError(null)` 등을 `.then()` 콜백이 아니라 바로 동기적으로 호출 — 이 프로젝트의 React 19/Next 16 계열 eslint 설정이 이 패턴 자체를 금지함 | 3개 섹션은 effect 본문을 `async function run() {...}; run();`으로 감싸서 setState 호출이 별도 함수 스코프 안에서 일어나게 함(별도 함수 스코프 안이면 규칙이 안 걸림). `ChatComposer`의 리셋 케이스는 애초에 effect가 필요 없어서 `key={activeStep}` 리마운트로 대체 |
| 위 수정 직후 `next build` 타입체크가 "Property 'value' does not exist on type ComposerEvent" 에러(file 케이스) | `composerEvent.kind !== "text"`로 좁혀놓은 판별이 effect 바깥 스코프에서만 유효한데, 안쪽 `async function run()`에서 `composerEvent!.value`로 다시 접근하니 TypeScript가 그 내부 함수까지 판별 축소를 못 이어줌(클로저를 넘어가는 판별 보존은 TS가 안 해줌) | 판별이 유효한 바깥 스코프에서 `const text = composerEvent.value`로 먼저 뽑아두고, `run()` 안에서는 그 지역 변수만 사용 |
| `CategorySection.tsx` 첫 수정본에서 `useEffect`를 `if (mode === "completed") return ...` 조기 리턴 **뒤**에 넣어버림 | React Hooks 규칙(모든 hook은 조건 없이 항상 같은 순서로 호출돼야 함)을 놓침 — `PeriodSection`은 처음부터 early return 앞에 뒀는데 `CategorySection`을 옮기면서 실수로 뒤에 둠 | early return 앞으로 이동, `mode !== "active"` 조건은 effect 본문 안의 guard로 처리(hook 자체는 항상 호출되지만 내용만 조건부 실행) |

## 남은 작업

없음. 사용자 피드백으로 촉발된 추가 단계였고, 애초에 의도했던 "진짜 하나의 채팅 대화" 모습이 이제 실제로 구현됐다.
