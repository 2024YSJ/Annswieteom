# 공용 체크리스트 3 — 배포 및 최종 안정화

근거: 명세서 15절, 16절 마일스톤 5, 19절
담당: 공용
선행 조건: 마일스톤 1~4의 각 폴더 체크리스트(A, B) 대부분 완료
브랜치: `chore/deploy-setup` (`dev`에서 분기해 배포 설정만 먼저 정리) + 각 마일스톤 체크포인트마다 `dev → main` 승격 PR (전략 상세는 [01_repo_and_env_setup.md](01_repo_and_env_setup.md) 4절)

## 0. `dev → main` 승격 (배포 전 필수)

브랜치 전략([01_repo_and_env_setup.md](01_repo_and_env_setup.md) 4절)에 따라 Vercel·Railway는 `dev`가 아니라 **`main`**을 추적한다. 아래 1·2번을 진행하기 전에 먼저:

- [ ] 마일스톤 4까지의 작업이 `dev`에서 검증 기준을 통과했는지 확인
- [ ] `dev → main` PR을 만들어 A·B가 함께 리뷰 후 병합 (이 시점부터 `main`이 처음으로 "배포 가능한 상태"가 된다)
- [ ] 이후 마일스톤 5에서 버그를 고칠 때도 같은 흐름 반복: `feature/*` 또는 `fix/*` → `dev` → (확인 후) `main`

## 1. 프론트엔드 배포 (Vercel)

- [ ] Vercel 계정 생성, GitHub 저장소 연결, **Production Branch를 `main`으로 지정**
- [ ] 루트 디렉터리를 `frontend/`로 지정
- [ ] 환경변수(`NEXT_PUBLIC_API_BASE_URL` 등 백엔드 주소) Vercel 프로젝트 설정에 등록
- [ ] 배포 후 발급된 URL로 접속해 랜딩 페이지가 뜨는지 확인

## 2. 백엔드 배포 (Railway)

- [ ] Railway 계정 생성, GitHub 저장소 연결, **배포 브랜치를 `main`으로 지정**, 루트를 `backend/`로 지정
- [ ] 시작 명령어 설정: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- [ ] 환경변수 등록 (10-4절 표 전체): `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL_NAME`, `GEMINI_API_KEY`, `LLM_PROVIDER_ORDER`, `DATABASE_URL`, `JWT_SECRET`, 그리고 [00_shared/01_repo_and_env_setup.md](01_repo_and_env_setup.md)에서 추가한 Supabase Storage 접속 정보
- [ ] `ENVIRONMENT=production` 추가 — [person_B_frontend_backend/01_auth.md](../person_B_frontend_backend/01_auth.md)에서 추가한 값. 이게 없으면(기본값 `development`) Refresh Token 쿠키가 `SameSite=Lax`로 내려가서 Vercel↔Railway 교차 도메인 환경에서 쿠키가 아예 전달되지 않는다(3번 참고)
- [ ] `JWT_SECRET`은 `openssl rand -hex 32`로 새로 생성해서 등록 (로컬 개발용 값과 달라도 무방)
- [ ] 배포 후 `<railway-url>/docs`에서 Swagger UI 접속 확인
- [ ] 프론트엔드의 `NEXT_PUBLIC_API_BASE_URL`을 실제 Railway 배포 주소로 갱신, 재배포

## 3. CORS 및 쿠키 설정 확인 (17절 트러블슈팅, [person_B_frontend_backend/01_auth.md](../person_B_frontend_backend/01_auth.md) 참고)

- [ ] FastAPI `CORSMiddleware`에 Vercel 배포 주소를 `allow_origins`에 추가하고 `allow_credentials=True`인지 확인
- [ ] Refresh Token 쿠키의 `SameSite`가 배포본에서는 `None; Secure`로 설정돼 있는지 확인 (로컬은 `Lax`로도 동작하지만 Vercel↔Railway처럼 최상위 도메인이 다른 배포 환경에서는 `Lax`로는 쿠키가 아예 전달되지 않는다)
- [ ] 배포된 프론트에서 배포된 백엔드로 실제 로그인 → 새로고침(Access Token 재발급) 요청이 CORS/쿠키 에러 없이 성공하는지 확인 — 로그인만 되고 새로고침 후 로그아웃되는 것처럼 보인다면 이 쿠키 설정을 의심할 것

## 4. 폴백 전환 테스트 (10절, 19절 — A·B 함께 진행)

- [ ] A가 Cloudflare Tunnel을 일부러 잠깐 중단
- [ ] 그 상태에서 배포된 서비스에서 AI 초안 요청 / 문서 생성 요청이 여전히 성공하는지 확인 (Gemini로 자동 전환되는지)
- [ ] 응답 시간이 눈에 띄게 느려지는지, 사용자에게 어떤 안내가 나가는지 확인하고 필요 시 프론트 로딩 UI 보완
- [ ] 터널 복구 후 다시 로컬 LLM으로 우선 사용되는지 확인

## 5. 전체 흐름 리허설

- [ ] 가상 시나리오 2~3개(예: "육아로 인한 공백기", "이직 준비 공백기", "프리랜서 활동 공백기")로 회원가입부터 문서 내보내기까지 전체 흐름을 실제로 완주
- [ ] 각 시나리오에서 근거 없는 문장이 섞이지 않는지(정직성 가드레일), 근거 출처가 정확히 표시되는지 확인

## 6. 신규 기능 동결 및 마무리

- [ ] 9/16 이후 신규 기능 추가 중단, 이후는 버그 수정과 발표 준비만 진행하기로 팀 내 합의
- [ ] 데모 당일을 대비해 [`../person_A_infra_ai/07_server_ops_checklist.md`](../person_A_infra_ai/07_server_ops_checklist.md)의 "데모·투표 기간 시작 전날" 항목을 A·B 함께 재확인

## 검증 기준

- [ ] 실제 배포된 URL만으로 (로컬 서버 없이) 회원가입 → 로그인 → 전체 인터뷰 흐름 → 문서 생성 → 내보내기까지 완주된다
- [ ] 로컬 LLM 서버를 껐을 때도 서비스가 죽지 않고 Gemini로 대체되어 계속 동작한다
