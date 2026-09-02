# B-5. 프론트엔드 라우트 구조 및 공통 컴포넌트 devlog

체크리스트: `docs/checklists/person_B_frontend_backend/05_frontend_routes_components.md`
날짜: 2026-09-03
브랜치: `dev`에 직접 (기존 `feature/auth`가 이미 로그인/회원가입 화면을 갖고 있었고, 나머지 라우트는 이미 완성된 백엔드 API들과 묶어 한 번에 진행)

---

## 완료 항목

- 라우트 5개 전부: `app/sessions/[id]/period`, `categories`, `records`, `interview`, `result` + 랜딩 페이지(`app/page.tsx`) 교체
- 공통 컴포넌트 4개: `InterviewChatThread`, `RecordUploadPanel`, `EvidenceTag`, `ToneSlider`
- `@tanstack/react-query` 도입, `lib/query-keys.ts`, `lib/query-provider.tsx`(루트 레이아웃에 장착)
- `lib/api-client.ts`에 session/interview/records/document API 전부 추가 (기존 auth API는 그대로 둠)
- `lib/session-routes.ts`: `sessions.status` → 라우트 매핑(`pathForStatus`) + 카테고리/스텝 한국어 라벨
- `lib/error-messages.ts`: 백엔드 에러 코드/HTTP 상태 → 한국어 메시지 매핑
- **401 → `/auth/refresh` 재시도 → 원 요청 재시도**를 `api-client.ts`에 구현 (아래 "핵심 결정 사항" 참고)
- 상태머신 기반 자동 리다이렉트: 각 세션 페이지가 로드 시 실제 `sessions.status`와 자기 라우트가 안 맞으면 `pathForStatus`로 리다이렉트

## 핵심 결정 사항과 이유

**`GET /interview/next`의 부수효과(DRAFT→CONFIRM 상태 전이)를 감안한 fetch-once 가드**: 이 엔드포인트는 순수 조회가 아니라 호출할 때마다 세션 상태를 전이시키고 `pending_draft`를 서버에 저장한다. React 19 개발 모드는 effect를 마운트 시 두 번 실행하는데, 그대로 두면 같은 draft step에 대해 이 호출이 두 번 나갈 위험이 있었다. `useRef`로 `"{status}:{category_id}"` 키를 기록해 같은 draft step에 대해 한 번만 호출되도록 가드했다(interview 페이지, result 페이지의 최초 `generate` 호출도 동일 패턴).

**새로고침 중 유실되는 `pending_draft`는 임시 방편으로만 처리**: `*_CONFIRM` 상태에서 새로고침하면 프론트가 들고 있던 AI 초안 텍스트가 사라지는데, 이걸 다시 받아올 조회 전용 엔드포인트가 없다(스펙에 없음 — `interview/next`를 다시 부르면 이미 DRAFT가 아니라서 409). `ManualConfirmFallback`으로 "새로고침 전 초안을 못 보여준다"고 알리고 사용자가 직접 답을 입력해 진행은 계속할 수 있게 했다. 근본적으로 고치려면 B-2 API에 `GET .../interview/pending` 같은 조회 전용 엔드포인트가 필요한데, 이번 범위를 넘어서서 devlog에만 남긴다.

**401 자동 재시도를 `api-client.ts` 모듈 레벨에서 처리**: Access Token은 `AuthProvider`의 React state에만 있고(14-3절, localStorage 금지) `api-client.ts`는 컴포넌트 트리 밖의 평범한 모듈이다. 매 호출부가 "401이면 refresh 후 재시도"를 반복 구현하지 않도록, `AuthProvider`가 마운트 시 `registerTokenRefreshHandler(setAccessToken)`으로 자기 자신을 등록해두고, `api-client.ts`의 `withAuthRetry()`가 401을 감지하면 `/auth/refresh`를 호출 → 성공 시 그 콜백으로 새 토큰을 React state에 반영 → 원 요청을 새 토큰으로 재시도한다. `/auth/refresh` 자체 호출이나 애초에 Authorization 헤더가 없던 요청(로그인/회원가입의 진짜 401)은 이 경로를 타지 않게 분기했다.

**`ManualConfirmFallback`을 제외하면 전역 에러 바운더리/토스트 대신 기존 관행(페이지별 인라인 에러 문구)을 그대로 따름**: B-1의 로그인/회원가입 페이지가 이미 이 패턴이라 통일성을 위해 유지했다. `lib/error-messages.ts`가 코드→한국어 메시지 매핑을 공통화해서 "한국어 메시지로 노출"이라는 체크리스트 요건은 충족하되, 새 전역 상태 관리 계층을 추가하지는 않았다.

## 트러블슈팅 (실제 브라우저로 전체 플로우를 처음 완주하며 발견한 것들)

| 증상 | 원인 | 해결 |
|---|---|---|
| 이 프로젝트 처음으로 실제 브라우저 완주 시도, `POST /auth/register`가 브라우저 콘솔에 **CORS 에러**로 표시됨 | 실제로는 CORS 문제가 아니라 백엔드가 500을 던졌는데, Starlette `CORSMiddleware`가 처리 못 한 예외에는 CORS 헤더를 못 붙여서 브라우저가 CORS 실패로 오표시하는 잘 알려진 함정. 진짜 원인은 `.env`의 실 Supabase `DATABASE_URL` 비밀번호가 `asyncpg.exceptions.InvalidPasswordError`로 인증 실패 | 이 세션의 브라우저 수동 테스트 자체는 임시 SQLite로 우회(B-1 devlog가 이미 쓴 방식과 동일, `record_chunks`만 pgvector라 제외). **실 Supabase 비밀번호는 여전히 안 고쳐진 상태로 남아있음 — 아래 "남은 작업" 참고** |
| 인터뷰 1라운드에서 `GET /interview/next`가 **503**(`llm_unavailable`) | 로컬 Ollama(`qwen2.5:14b`)가 방금 켜져서 첫 요청이 모델을 VRAM에 올리는 콜드 스타트 시간이 A의 `LocalOllamaProvider._generate` 하드코딩 타임아웃(20초)보다 오래 걸림 → 로컬 실패 → Gemini도 `GEMINI_API_KEY` 없어서 실패 → 둘 다 실패로 503 | 모델을 한 번 예열(직접 `/api/chat` 호출)한 뒤 재시도하니 통과. **20초 타임아웃은 콜드 스타트에 여전히 너무 짧다 — A-2 쪽에서 설정 가능한 값으로 빼거나 늘리는 걸 권장, 이번 범위에서는 안 고침** |
| 인터뷰 페이지 제목이 "아르바이트" 대신 원시 값 `part_time`으로 표시 | `categoryLabel` 계산에서 `custom_label` 다음 폴백을 `CATEGORY_LABELS`로 안 거치고 `category_type` 원시 문자열을 그대로 씀 | `CATEGORY_LABELS[category_type]`로 수정 |
| `generated_sentences.evidence_fact_ids`가 SQLite에서 테이블 생성 자체가 실패 | B-4에서 이미 겪고 고친 문제(JSONB→JSON) — 이번엔 수동 테스트용 부트스트랩 스크립트에서 같은 테이블 세트를 다시 구성하며 재확인만 함 | 해당 없음(이미 dev에 반영됨), 수동 테스트 DB 부트스트랩에 그대로 반영 |

## 실제로 확인한 것 (실 로컬 Ollama, Playwright로 실제 Chromium 조작)

임시 SQLite + 실제 로컬 `qwen2.5:14b`(LLM 생성)와 `bge-m3`(임베딩) 조합으로 **이 프로젝트 최초로 랜딩→회원가입→로그인→세션 생성→기간 입력→카테고리 선택→기록물(텍스트 붙여넣기)→인터뷰 3라운드(빈도/업무/성과, 실제 AI 초안 확인)→문서 생성(실제 LLM 호출)→일관성 검증 결과 표시(근거 부족 문장이 실제로 "확인이 더 필요한 문장"으로 걸러짐)→최종 확정→텍스트 내보내기**까지 브라우저로 전부 완주했다. 별도로 `JWT_ACCESS_EXPIRE_MINUTES=1`로 낮춰 액세스 토큰이 실제로 만료된 뒤 페이지 새로고침 없이 폼을 제출했을 때 `401 → POST /auth/refresh → 원 요청 재시도`가 사용자에게 보이는 에러 없이 성공하는 것도 네트워크 로그로 확인했다.

## 남은 작업

- **실 Supabase `DATABASE_URL` 비밀번호가 깨져 있음** — `asyncpg.exceptions.InvalidPasswordError`. 이번 수동 테스트는 임시 SQLite로 우회했지만, 실 배포/실 데이터로 테스트하려면 먼저 고쳐야 한다.
- `LocalOllamaProvider`의 20초 타임아웃이 콜드 스타트에 너무 짧음 — 설정값으로 분리하거나 늘리는 걸 권장 (A-2 영역)
- `*_CONFIRM` 상태 새로고침 시 초안 유실 — 근본 해결하려면 B-2에 조회 전용 엔드포인트 추가 필요
- 이미지 업로드는 `SUPABASE_URL`/`SUPABASE_SERVICE_KEY`가 비어 있어 이번 수동 테스트에서 실제로 못 눌러봄 (블로그 URL/텍스트 붙여넣기 경로만 확인)
- 전역 에러 바운더리/토스트 컴포넌트는 미구현(인라인 에러 문구로 대체) — 필요해지면 별도로 추가
