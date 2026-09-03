# B 담당 체크리스트 — 프론트엔드 & 백엔드 로직

당신(B)은 인증, 인터뷰 상태머신, 문서 생성 API, 그리고 프론트엔드 전체를 담당한다. A가 만드는 AI 어댑터(`services/llm`)와 기록물 파이프라인(`services/record_pipeline`)은 인터페이스로만 가져다 쓰면 되고, 그 내부 구현은 A의 담당이다.

## 담당 폴더 (5절)

- `frontend/` 전체
- `backend/app/api/`
- `backend/app/services/interview_orchestrator.py`
- `backend/app/services/document_generator.py`

## 순서

| 파일 | 내용 | 명세서 절 | 시점 |
|---|---|---|---|
| [01_auth.md](01_auth.md) | 회원가입/로그인/JWT | 7, 9-1 | 1주차 |
| [02_interview_state_machine_api.md](02_interview_state_machine_api.md) | 인터뷰 상태머신 + 세션/인터뷰 API | 8, 9-2, 9-3 | 1~2주차 |
| [03_records_feature.md](03_records_feature.md) | 기록물 업로드 API + 프론트 UI | 9-4, 13(UI), 14 | 2주차 |
| [04_document_generation.md](04_document_generation.md) | 문서 생성/조회/수정 API + 결과 화면 | 9-5, 12(연동), 14 | 2~3주차 |
| [05_frontend_routes_components.md](05_frontend_routes_components.md) | 라우트 구조, 공통 컴포넌트, 상태 관리 | 14 | 1~3주차 전체 |

## 정직성 가드레일과 B의 책임 (1-2절)

당신이 만드는 `document_generator.py`와 `interview_orchestrator.py`가 이 원칙이 실제로 지켜지는 핵심 지점이다:
- 인터뷰 중 AI가 제시한 초안(`ai_draft_text`)은 사용자가 확인/정정하기 전까지 **절대 `confirmed_facts`에 들어가면 안 된다.**
- `document_generator.py`의 오케스트레이션 함수(`generate_full_document(session_id, tone)`, 세부는 [04_document_generation.md](04_document_generation.md) 참고)는 세션의 카테고리를 순회하되, **A가 만든 `LLMProvider.generate_document(facts: list[ConfirmedFact], tone: str)`을 호출할 때는 그 카테고리의 `confirmed_facts` 리스트와 톤 문자열만** 넘긴다 — 세션이나 카테고리 ORM 객체 전체를 넘기지 않는다. 이 경계가 "확정된 사실만 최종 생성 입력이 될 수 있다"는 원칙을 코드로 강제하는 지점이다.
