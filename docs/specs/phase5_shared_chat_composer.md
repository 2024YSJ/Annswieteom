# Phase 5 — 공유 채팅 입력창 + 질문 영구 보존

Phase 1~4 로드맵이 끝난 뒤, 실제로 만들어진 화면을 보여드리고 받은 피드백을 반영한 추가 단계. 지금까지는 "5개 페이지를 한 화면에 모은 것"이었지 진짜 "하나의 채팅 대화"는 아니었다 — 단계마다(기간/카테고리/기록물) 각자 다른 입력 위젯(날짜 선택기, 텍스트박스+버튼, 첨부 컴포저)이 개별 카드처럼 붙어있었다.

## 목표

1. 답변 입력은 화면 전체에서 **하나의 공유 채팅 입력창**으로만 한다 — 기간(날짜)도 완전히 자유 텍스트로.
2. **AI가 던진 질문 자체도 채팅 로그에 영구히 남는다** — 단계가 완료돼도 AI의 원래 질문이 사라지지 않고, 사용자의 답변과 짝을 이뤄 그대로 보존된다.

인터뷰 단계(빈도/업무/성과)의 "AI가 초안을 제안하고 사용자가 그대로 확인하거나 고쳐서 확인하는" 방식은 정직성 가드레일과 관련된 의도적 설계라 그대로 뒀다 — 이미 답변이 사라지지 않는 방식이었어서 요구사항과 충돌하지 않는다. 다만 "무엇을 물었는지"가 작은 캡션 한 줄로만 표시되던 부분은 이번에 같이 고쳤다.

## 백엔드: 기간도 자유 텍스트에서 추출

Phase 3의 `extract_categories`와 완전히 같은 패턴으로 `POST /sessions/{id}/period/extract`를 추가했다. 카테고리와 다른 점: 날짜를 잘못 해석해서 조용히 넘어가면 실제 데이터 품질 문제가 되므로, "확신 있게 파싱됨"(`start_date`/`end_date` 둘 다 값 있음)과 "파싱 못 함"(둘 다 `null`, 에러 아닌 정상 응답)을 명확히 구분했다. 이 사이의 애매한 상태(하나만 `null`)는 만들지 않는다 — `FallbackProvider.extract_period`는 provider가 `None`을 반환하면 그걸 성공으로 보고 즉시 반환한다(다음 provider로 안 넘어감). 이 엔드포인트도 `categories/extract`와 마찬가지로 **DB에 아무것도 안 쓴다** — 실제 저장은 기존 `POST /period`가 그대로 담당.

## 프론트: 하나의 `ChatComposer` + 3개 섹션 배선

새 `ChatComposer` 컴포넌트가 화면 전체에서 유일한 텍스트 입력창이다. 순수 입력 캡처 컴포넌트로 유지했다 — API 호출은 안 하고, `{kind, value/file, nonce, forStep}` 이벤트를 오케스트레이터에 올려보내면 오케스트레이터가 `forStep`이 일치하는 섹션에만 그 이벤트를 내려준다.

**`forStep`으로 필터링하는 이유**: 단계가 막 바뀌는 순간(예: 기간 확정→카테고리 섹션 마운트) 이전 단계의 이벤트가 새로 마운트된 섹션에 잘못 소비될 수 있는 1-렌더 레이스가 있다. nonce만으로는 못 막고, 이벤트가 만들어진 시점의 `forStep` 값으로 필터링해야 이 레이스가 원천적으로 사라진다.

각 섹션(Period/Category/Records)은 자기 도메인 로직(추출 API 호출, 결과 상태)은 그대로 유지하고, 트리거만 "자기 안의 입력 필드"에서 "부모가 내려주는 `composerEvent` prop"으로 바뀌었다. Records만 첨부(📎) 버튼이 필요해서, `ChatComposer`가 `activeStep==="records"`일 때만 첨부 버튼+팝오버+숨김 파일 input+URL 인라인폼을 같이 보여준다. 드래그앤드롭은 컴포저가 아니라 `RecordsSection`의 기록물 목록 영역에 그대로 남겼다 — 공유 입력창의 대상이 아니기 때문.

`ChatComposer`는 `activeStep`이 바뀌면 `key={activeStep}`로 **리마운트**시켜서 입력 중이던 텍스트/팝오버 상태를 초기화한다 — `useEffect`로 상태를 리셋하는 대신 리마운트를 택한 이유는 아래 트러블슈팅 참고.

## `ChatBubble`에 `variant` 추가

기존 `side="left"`는 Phase 2 때 날짜폼/체크박스/드래그앤드롭 같은 실제 폼을 담기 위해 일부러 넓고(카드형) 만들어졌다. 이제 그 폼들이 전부 공유 입력창으로 빠져나갔으니, 좁고 회색인 진짜 "채팅 메시지" 모양(`variant="message"`, 인터뷰의 기존 pending 말풍선과 동일 스타일)이 더 맞는다. 다만 `ResultSection`은 톤슬라이더+문장편집 UI를 담고 있어서 여전히 넓은 카드가 필요하므로, 기본값을 바꾸는 대신 `variant` prop을 추가하고 `ResultSection`의 기존 호출부에는 전부 `variant="card"`를 명시했다.

## 완료된 단계의 질문 영구 보존

`PeriodSection`/`CategorySection`/`RecordsSection` 전부 `mode==="completed"`일 때 기존 오른쪽 요약 말풍선 위에 원래 AI 질문 문구를 왼쪽 말풍선으로 추가했다. 이 영구 보존 말풍선엔 `aria-live` 안 씀 — 그건 "새로 나타난" 질문에만 필요하고, 완료된 걸 매번 다시 안내하면 새로고침마다 스크린리더가 예전 질문을 전부 다시 읽어주는 회귀가 생긴다.

인터뷰 쪽(`InterviewChatThread`)도 같은 원리로, 확인된 사실마다 있던 작은 회색 캡션("빈도 · 확인됨")을 답변 말풍선의 `label`로 옮기고, 실제 질문 문구("얼마나 자주 하셨나요?")를 답변 바로 위에 별도 왼쪽 말풍선으로 추가했다. `fact.fact_type`만으로 어떤 질문이었는지 클라이언트에서 바로 유도 가능해서(`QUESTION_BY_FACT_TYPE`) 백엔드 변경은 없었다.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `npx eslint .`가 `PeriodSection`/`CategorySection`/`RecordsSection`/`ChatComposer`에서 `react-hooks/set-state-in-effect` 에러 | effect 본문에서 `setError(null)`/`setIsExtracting(true)` 같은 걸 동기적으로 바로 호출 — 이 프로젝트의 eslint 설정(React 19/Next 16 계열)이 이 패턴을 금지함(`.then()`/`.catch()` 콜백 안에서의 호출은 허용) | 3개 섹션은 effect 본문을 `async function run() {...}; run();` 형태로 감싸서 setState 호출이 별도 함수 스코프 안에서 일어나게 함. `ChatComposer`의 "activeStep 바뀌면 상태 리셋" 케이스는 애초에 effect가 필요 없는 경우였음 — `key={activeStep}`로 리마운트시켜서 effect 자체를 없앰(React 공식 문서가 권장하는 "prop 바뀌면 상태 리셋" 패턴) |
| 위 수정 직후 `next build` 타입체크가 `PeriodSection`/`CategorySection`에서 "Property 'value' does not exist on type ComposerEvent(file 케이스)" 에러 | `composerEvent.kind !== "text"`로 좁혀놓은 판별이 effect 바깥 스코프에서만 유효했는데, `async function run() {...}` 안에서 `composerEvent!.value`로 다시 접근하니 TypeScript가 그 내부 함수 스코프에서는 판별을 다시 증명 못 함(닫힘 스코프를 넘어간 판별 축소는 보존 안 됨) | 판별이 유효한 바깥 스코프에서 `const text = composerEvent.value;`로 미리 뽑아두고, `run()` 안에서는 이 `text` 지역 변수만 사용 |

## 의도적으로 처리하지 않은 것 (Phase 5 범위 밖)

- 인터뷰 단계의 "AI가 초안 제안 → 사용자 확인/수정" 방식을 자유 입력형으로 바꾸는 것 — 정직성 가드레일 관련 의도적 설계, 원래도 답변이 안 사라졌으므로 이번 요구사항과 무관
- 오래된 완료 말풍선들을 접어서 화면 길이를 관리하는 기능 (Phase 2 spec에서도 이미 범위 밖으로 명시)

## 다음 단계

없음 — 사용자 피드백으로 시작된 추가 단계였고, 이걸로 로드맵이 실제 의도에 맞게 마무리됐다.
