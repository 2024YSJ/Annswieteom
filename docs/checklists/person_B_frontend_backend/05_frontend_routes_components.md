# B-5. 프론트엔드 라우트 구조 및 공통 컴포넌트

근거: 명세서 14절
선행 조건: [01_auth.md](01_auth.md) (로그인 흐름), 이후 각 기능 API가 완성되는 대로 해당 화면 완성
폴더: `frontend/`
브랜치: `feature/frontend-shell` (`dev`에서 분기, 완료 후 `dev`로 PR) — 공통 라우팅·레이아웃·`api-client.ts` 골격만 여기서 작업하고, 기능별 화면(로그인, 기록물 업로드, 결과 화면 등)은 해당 기능 브랜치(`feature/auth`, `feature/records-feature`, `feature/document-generation`)에서 함께 진행
시점: 1~3주차 전체에 걸쳐 진행 (기능별 화면은 해당 API와 함께)

## 1. 라우트 구조 (14-1절)

- [ ] `app/page.tsx` — 랜딩 페이지
- [ ] `app/register/page.tsx`, `app/login/page.tsx` — [01_auth.md](01_auth.md)에서 구현
- [ ] `app/sessions/[id]/period/page.tsx` — 공백기 기간 입력
- [ ] `app/sessions/[id]/categories/page.tsx` — 활동 카테고리 선택(복수 선택)
- [ ] `app/sessions/[id]/records/page.tsx` — [03_records_feature.md](03_records_feature.md)에서 구현
- [ ] `app/sessions/[id]/interview/page.tsx` — 채팅형 인터뷰 UI
- [ ] `app/sessions/[id]/result/page.tsx` — [04_document_generation.md](04_document_generation.md)에서 구현
- [ ] (v1 명세에 있던 `job-description/page.tsx`는 채용공고 파싱 제거로 **만들지 않는다**)

## 2. 핵심 공통 컴포넌트 (14-2절)

- [ ] `InterviewChatThread`: AI 말풍선(초안 제시) + 사용자 응답(빠른 확인 버튼 + 자유 텍스트 입력) — [02_interview_state_machine_api.md](02_interview_state_machine_api.md)의 `interview/next`, `interview/confirm`과 연동. `interview/next` 응답의 `based_on`(기록물 근거 여부)을 말풍선에 작은 배지로 표시해, 사용자가 "이건 내 블로그 글 근거" vs "이건 AI의 일반적인 추측"을 구분하고 확인/정정할 수 있게 한다 (1-3절 Recognition over Recall 원칙)
- [ ] `RecordUploadPanel`: [03_records_feature.md](03_records_feature.md) 참고
- [ ] `EvidenceTag`: [04_document_generation.md](04_document_generation.md) 참고
- [ ] `ToneSlider`: [04_document_generation.md](04_document_generation.md) 참고

## 3. 상태 관리 (14-3절)

- [ ] React Query 도입, 쿼리 키 컨벤션 확립: `['session', sessionId]`, `['session', sessionId, 'interview', 'next']`, `['session', sessionId, 'document']`
- [ ] `lib/api-client.ts`: 백엔드 호출 공통 래퍼(`NEXT_PUBLIC_API_BASE_URL` 환경변수로 백엔드 주소를 읽고, Authorization 헤더 자동 부착, **모든 요청에 `credentials: "include"` 포함**(안 그러면 브라우저가 refresh token 쿠키를 아예 보내지 않는다 — [01_auth.md](01_auth.md) 참고), 401 시 `/auth/refresh` 재시도 후 재요청) — `NEXT_PUBLIC_API_BASE_URL`은 [00_shared/01_repo_and_env_setup.md](../00_shared/01_repo_and_env_setup.md)에서 `frontend/.env.local.example`에 이미 등록해뒀다
- [ ] `lib/query-keys.ts`: 쿼리 키 상수 모음
- [ ] Access Token은 React Context에만 보관 (localStorage 금지), 새로고침 시 `/auth/refresh`로 재발급받아 Context 복원

## 4. 공통 UX 체크

- [ ] 상태머신 상태(`sessions.status`)에 따라 사용자를 올바른 라우트로 자동 리다이렉트 (예: 새로고침해도 자기 진행 단계로 돌아옴)
- [ ] API 에러(9-6절 포맷)를 공통 처리해 사용자에게 한국어 메시지로 노출하는 에러 바운더리/토스트 구현
- [ ] CORS 관련 이슈 없는지 로컬 개발 중 `localhost:3000` ↔ `localhost:8000` 간 확인 (17절)

## 검증 기준

- [ ] 전체 라우트를 순서대로(랜딩 → 회원가입/로그인 → 기간 입력 → 카테고리 선택 → 기록물 업로드/스킵 → 인터뷰 → 결과) 클릭만으로 완주할 수 있다
- [ ] 인터뷰 중간에 새로고침해도 마지막 진행 상태로 복귀한다
- [ ] Access Token 만료 시나리오(짧게 테스트하려면 만료 시간을 임시로 줄여서)에서 자동 재발급이 눈에 띄는 에러 없이 동작한다
