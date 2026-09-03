# Phase 3 — AI 카테고리 추출

Claude-Desktop형 UI 재설계 로드맵의 세 번째 단계. [Phase 2](phase2_unified_chat_ui.md)에서 5개 페이지를 하나의 채팅 화면으로 합쳤다면, 이번엔 그 화면 안의 카테고리 선택 단계를 체크박스 직접 선택에서 자유 텍스트 + AI 추출로 바꾼다.

## 목표

1. 사용자가 공백기 활동을 자유 텍스트로 적으면 AI가 카테고리(활동 종류)를 추출해 제안
2. 사용자가 제안된 목록을 수정(이름 변경/삭제/직접 추가)한 뒤 확정
3. `PeriodSection`/`RecordsSection`/`InterviewSection`/`ResultSection`, 오케스트레이터, 사이드바 등 나머지는 전혀 안 건드림

## 추출 방식: 한 번에(single-shot)

텍스트 상자에 활동을 적고 "카테고리 찾기"를 누르면 AI가 한 번에 목록을 제안한다. 텍스트를 고쳐서 다시 누르면 이전 제안은 버리고 새로 교체한다(누적 아님). AI와 여러 턴 대화하며 점진적으로 좁혀가는 방식은 이번엔 채택하지 않았다 — 대화 기록/턴 상태를 새로 설계해야 할 만큼 범위가 커서, 필요해지면 별도 단계로 분리하는 쪽을 택했다.

## 정직성 가드레일: 추출은 저장이 아니다

새 엔드포인트 `POST /sessions/{id}/categories/extract`는 **아무것도 DB에 쓰지 않는다** — AI의 제안일 뿐, 사용자가 확인한 사실이 아니기 때문이다. 실제 저장은 기존 `POST /sessions/{id}/categories`가 그대로 담당한다(요청 바디에 `custom_label`만 추가됐을 뿐, 상태 전이·엔드포인트 자체는 Phase 1/2 이전부터 있던 것 그대로).

## `category_type`은 내부 분류용, `custom_label`이 진짜 이름

`activity_categories.category_type` 컬럼은 여전히 8종 CHECK 제약(`part_time`/`freelance`/.../`other`)을 통과해야 한다. AI에게 "이 중 가장 가까운 걸 고르되 확신 없으면 other"라고 지시하고, 사용자가 실제로 쓴 표현은 `custom_label`에 그대로 담게 했다 — `custom_label` 컬럼은 원래부터 있었지만(Phase 1 이전) 지금까지 한 번도 실제로 채워진 적이 없었다. 프론트엔드는 이미 어디서든 `custom_label ?? CATEGORY_LABELS[category_type]`로 표시해왔으므로(Phase 2 `CategorySection`/`InterviewChatThread` 등), 이 변경만으로 AI가 지은 자유로운 이름이 화면 전체에 자연스럽게 반영된다 — 추가로 손댈 곳이 없었다.

## 백엔드 변경

- `LLMProvider` 프로토콜에 `extract_categories(free_text, gap_start, gap_end) -> list[CategorySuggestion]` 추가, `FallbackProvider`/`LocalOllamaProvider`/`GeminiProvider` 구현(기존 `draft_suggestion`과 동일한 JSON 파싱 + malformed-response 방어 패턴 재사용)
- LLM이 8종에 없는 `category_type`을 반환하면 서버가 `"other"`로 강제 치환(나중에 저장 시 CHECK 제약 위반 방지)
- 새 `POST /sessions/{id}/categories/extract` — `CATEGORY_SELECT` 상태에서만 호출 가능(상태 전이 없음, `records.py`의 논트랜지션 패턴과 동일), 모든 LLM 실패 시 503 `llm_unavailable`

## 프론트엔드 변경

`CategorySection.tsx` 하나만 전면 교체(active 모드만; completed 모드는 무수정). 체크박스 8개 대신: 자유 텍스트 상자 → "카테고리 찾기" → 편집 가능한 제안 목록(각 항목 텍스트 수정/삭제, "+ 직접 추가"로 수동 추가 가능, `category_type: "other"`로 저장) → "확인"으로 기존 `POST /categories` 호출.

## 의도적으로 처리하지 않은 것 (Phase 3 범위 밖)

- AI와 여러 턴 대화하며 점진적으로 카테고리를 좁히는 방식
- 자유 텍스트에서 기간(날짜)까지 같이 추출해 `PeriodSection`을 자동 채우는 것
- `category_type` 8종 제약 자체를 없애거나 늘리는 것

## 다음 단계

Phase 4(기록물 업로드를 채팅 입력창의 첨부 버튼으로 이동) 착수 시 별도 spec 문서 작성 예정.
