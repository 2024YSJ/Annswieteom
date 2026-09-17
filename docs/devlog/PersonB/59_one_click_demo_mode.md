# 59. 원클릭 데모 모드 (2026-09-16)

devlog 58(트러스트 스코어보드)에 이어 챔피언십 심사위원/투표자가 로그인이나
인터뷰 과정을 거치지 않고 완성된 결과물을 바로 볼 수 있어야 한다는 요구.

## 무엇을

- `GET /api/v1/demo/document` — 완전 무인증(`health.py`와 동일한 수준),
  `settings.demo_session_id`로 지정된 세션 **딱 하나만** 노출한다.
  **경로 파라미터로 session_id를 받지 않는 것이 핵심 설계 포인트** — 그래야
  클라이언트가 임의의 UUID를 넣어 다른 사용자의 세션을 훔쳐볼 길이 아예 없다.
  `demo_session_id`가 비어 있으면(기본값) 404 — 기능 자체가 꺼진 상태.
- `backend/scripts/seed_demo_session.py` — ORM으로 직접 데모 세션을 구성
  (Ollama/임베딩 서버 없이도 완전 결정적으로 시드 가능). **의도적으로 근거
  없는 문장을 하나 포함시켜서**, 정직성 가드레일의 "숨기지 않는다" 동작이
  데모 화면 자체에서 보이도록 함.
- 프론트 `frontend/app/demo/page.tsx` — 읽기 전용 공개 페이지, 글로벌
  트러스트 스코어보드와 나란히 렌더링.
- `ResultSection.tsx`의 `ParagraphSection`/`SentenceRow`를
  `components/DocumentView.tsx`로 추출(편집 콜백 전부 optional화) — 데모
  페이지가 별도의 읽기 전용 사본을 만들지 않고 동일한 근거/배지 렌더링을
  재사용하도록.

## 검증

- `backend/tests/api/test_demo.py` 신규(47줄) — `demo_session_id` 미설정 시 404,
  설정됐지만 FINAL이 아닐 때 404, 정상 조회
- 로컬 dev DB + 실제 프런트/백엔드 페어로 엔드투엔드 확인

## 남은 작업

- [ ] 배포 환경에 실제 `DEMO_SESSION_ID` 값을 넣고 `/demo` 페이지가 실제로
      뜨는지 확인 (로컬에서만 검증됨)

## 관련 커밋

- `9819ac0` feat: add one-click demo mode for judges/voters
