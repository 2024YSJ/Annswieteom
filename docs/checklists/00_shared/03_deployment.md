# 공용 체크리스트 3 — 배포 및 최종 안정화

근거: 명세서 15절, 16절 마일스톤 5, 19절
담당: 공용
선행 조건: 마일스톤 1~4의 각 폴더 체크리스트(A, B) 대부분 완료
브랜치: `chore/deploy-setup` (`dev`에서 분기해 배포 설정만 먼저 정리) + 각 마일스톤 체크포인트마다 `dev → main` 승격 PR (전략 상세는 [01_repo_and_env_setup.md](01_repo_and_env_setup.md) 4절)

## 0. `dev → main` 승격 (배포 전 필수)

브랜치 전략([01_repo_and_env_setup.md](01_repo_and_env_setup.md) 4절)에 따라 Vercel·Render는 `dev`가 아니라 **`main`**을 추적한다. 아래 1·2번을 진행하기 전에 먼저:

- [x] 마일스톤 4까지의 작업이 `dev`에서 검증 기준을 통과했는지 확인 — 백엔드 테스트 69개, 실 Supabase + 실 로컬 LLM으로 전체 브라우저 완주 2회(2026-09-03)
- [x] `dev → main` PR을 만들어 A·B가 함께 리뷰 후 병합 (이 시점부터 `main`이 처음으로 "배포 가능한 상태"가 된다) — [PR #4](https://github.com/2024YSJ/Annswieteom/pull/4) 병합 완료(2026-09-03)
- [ ] 이후 마일스톤 5에서 버그를 고칠 때도 같은 흐름 반복: `feature/*` 또는 `fix/*` → `dev` → (확인 후) `main`

## 1. 프론트엔드 배포 (Vercel)

> **2026-09-17 갱신**: 이 절의 체크박스가 전부 비어 있었지만, `docs/devlog/PersonA/08_dgx_spark_migration.md`가
> 2026-09-11에 "배포된 사이트(`https://annswieteom.com`)에서 AI 응답이 생성된다"를 직접 확인한 기록을
> 남겼다 — 이건 Vercel 프론트가 이미 실제로 떠 있고 Render 백엔드를 향해 요청을 보내고 있다는 뜻이므로
> 아래 4개 항목은 실제로는 완료된 상태다. 체크리스트가 그 시점 이후로 갱신되지 않았을 뿐이다.

- [x] Vercel 계정 생성, GitHub 저장소 연결, **Production Branch를 `main`으로 지정** — `annswieteom.com`이 라이브(PersonA/08 devlog, 2026-09-11)
- [x] 루트 디렉터리를 `frontend/`로 지정 — 위와 동일 근거
- [x] 환경변수(`NEXT_PUBLIC_API_BASE_URL` 등 백엔드 주소) Vercel 프로젝트 설정에 등록 — 위와 동일 근거
- [x] 배포 후 발급된 URL로 접속해 랜딩 페이지가 뜨는지 확인 — 위와 동일 근거

## 2. 백엔드 배포 (Render)

> 2026-09-09 정정: 이 절은 원래 Railway 기준으로 쓰여 있었지만 실제 운영 백엔드는 **Render**다
> ([00_shared/04_local_dev_environment.md](04_local_dev_environment.md)가 처음부터 Render로 기록하고 있었다).
> 문서가 갈려 있던 탓에 환경변수를 어디에 넣어야 하는지 실제로 혼동이 생겨 바로잡는다.

- [x] Render 계정 생성, GitHub 저장소 연결, **배포 브랜치를 `main`으로 지정**, 루트를 `backend/`로 지정 — 라이브 확인(PersonA/08 devlog, 2026-09-11)
- [x] 시작 명령어 설정: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` — 위와 동일 근거
- [x] 환경변수 등록 (10-4절 표 전체): `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL_NAME`, `LLM_ACCESS_CLIENT_ID`, `LLM_ACCESS_CLIENT_SECRET`, `DATABASE_URL`, `JWT_SECRET`, 그리고 [00_shared/01_repo_and_env_setup.md](01_repo_and_env_setup.md)에서 추가한 Supabase Storage 접속 정보 — PersonA/08 devlog가 "Render 환경변수 3개 반영" 확인
- [x] **`GEMINI_API_KEY`와 `LLM_PROVIDER_ORDER`가 Render에 남아 있지 않은지 확인.** 등록하는 항목이 아니라 *삭제됐는지 확인하는* 항목이다 — 2026-09-09에 두 설정을 코드에서 지웠고, pydantic-settings가 기본 `extra="forbid"`라 이 키가 환경에 남아 있으면 `Settings()` 생성이 `ValidationError`로 죽어 **컨테이너 부팅 자체가 실패한다**(`docs/devlog/PersonB/24_remove_gemini_no_fallback.md`) — PersonA/08 devlog가 "부재 확인(있으면 배포 성공 자체가 증거)"로 재확인
- [x] 추론 서버를 DGX Spark로 이관한 뒤에도 `LOCAL_LLM_BASE_URL`은 **같은 호스트명**(`https://llm.annswieteom.com`)이므로 값 변경도 재배포도 필요 없다 — 바뀌는 건 `LOCAL_LLM_MODEL_NAME`과 Access 토큰 두 개뿐이다([../person_A_infra_ai/08_dgx_spark_migration.md](../person_A_infra_ai/08_dgx_spark_migration.md)) — DGX Spark 이관 자체가 완료되어 이 항목은 실행됨
- [x] `ENVIRONMENT=production` 추가 — [person_B_frontend_backend/01_auth.md](../person_B_frontend_backend/01_auth.md)에서 추가한 값. 이게 없으면(기본값 `development`) Refresh Token 쿠키가 `SameSite=Lax`로 내려가서 Vercel↔Render 교차 도메인 환경에서 쿠키가 아예 전달되지 않는다(3번 참고) — 배포된 사이트에서 로그인 기반 흐름(인터뷰→생성)이 동작하므로 쿠키가 실제로 전달되고 있음이 간접 확인됨
- [ ] `JWT_SECRET`은 `openssl rand -hex 32`로 새로 생성해서 등록 (로컬 개발용 값과 달라도 무방) — 실행 여부를 직접 증언하는 devlog 없음, Render 대시보드에서 직접 확인 필요
- [x] **`main`에 머지하기 전에 프로덕션 DB 마이그레이션을 먼저 돌린다.** — PersonA/08 devlog가 마이그레이션 `f3b6d0c8a114` 적용을 `alembic current`로 확인; 이후 championship-showcase의 `6fa82e770439`/`b7e2f4a9c1d5`도 동일 요령으로 반드시 재확인할 것 Render에는 `render.yaml`도 `Procfile`도 없고 시작 명령이 `uvicorn`뿐이라 **마이그레이션이 자동으로 돌지 않는다** — 새 테이블/컬럼을 쓰는 코드가 먼저 배포되면 해당 엔드포인트가 500으로 떨어진다.
  ```bash
  cd backend
  DATABASE_URL='<프로덕션 연결 문자열>' venv/Scripts/python.exe -m alembic upgrade head
  DATABASE_URL='<같은 값>' venv/Scripts/python.exe -m alembic current   # 최신 리비전인지 확인
  ```
  순서가 중요하다: **테이블·컬럼 추가는 지금 배포된 코드를 깨뜨리지 않으므로 머지 전에 돌리는 쪽이 항상 안전하다.** 반대로 컬럼 삭제·타입 변경이 섞인 마이그레이션이면 배포와 동시에 돌려야 하니 별도로 계획한다.
  이 프로젝트는 이걸 이미 한 번 놓쳤다 — `docs/devlog/Step2/06_the_migration_that_never_ran_and_the_effect_that_never_refired.md`.
- [ ] 배포 후 `<render-url>/docs`에서 Swagger UI 접속 확인 — 직접 증언하는 devlog 없음, 수동 확인 필요
- [x] 프론트엔드의 `NEXT_PUBLIC_API_BASE_URL`을 실제 Render 배포 주소로 갱신, 재배포 — 배포된 프론트가 배포된 백엔드로 실제 요청을 보내고 있으므로 간접 확인됨(PersonA/08 devlog)

## 3. CORS 및 쿠키 설정 확인 (17절 트러블슈팅, [person_B_frontend_backend/01_auth.md](../person_B_frontend_backend/01_auth.md) 참고)

- [x] FastAPI `CORSMiddleware`에 Vercel 배포 주소를 `allow_origins`에 추가하고 `allow_credentials=True`인지 확인 — 코드에 반영됨(PersonB/01 devlog), 배포본에서 로그인 기반 흐름이 동작하므로 실효성도 간접 확인
- [x] Refresh Token 쿠키의 `SameSite`가 배포본에서는 `None; Secure`로 설정돼 있는지 확인 (로컬은 `Lax`로도 동작하지만 Vercel↔Render처럼 최상위 도메인이 다른 배포 환경에서는 `Lax`로는 쿠키가 아예 전달되지 않는다) — `environment=production` 스위치로 구현됨(PersonB/01 devlog), Render에 `ENVIRONMENT=production` 반영도 위 2절에서 확인
- [ ] 배포된 프론트에서 배포된 백엔드로 실제 로그인 → 새로고침(Access Token 재발급) 요청이 CORS/쿠키 에러 없이 성공하는지 확인 — 로그인만 되고 새로고침 후 로그아웃되는 것처럼 보인다면 이 쿠키 설정을 의심할 것. **이 항목만은 여전히 미확인**: 지금까지의 증거는 "로그인된 상태로 흐름이 동작했다"이지 "30분 Access Token 만료 이후 갱신이 성공했다"를 직접 확인한 적은 없다

## 4. LLM 서버 중단 시 동작 확인 (19절 — A·B 함께 진행)

> **2026-09-17 기준 미실행.** 이 절과 5절은 마감 점검에서 확인한 진짜 잔여 항목이다 — 데모 주간
> (9/15~9/20) 중에 실제로 실행해야 한다.

> 이 절은 원래 "폴백 전환 테스트"였다. 2026-09-09에 Gemini를 제거해 **폴백이 없으므로**, 확인할 것이 "대체 경로로 넘어가는지"에서 "폴백 없이도 *깨지지 않고* 끝나는지"로 바뀌었다. 훈련 자체는 그대로 필요하다 — 폴백이 없어진 만큼 오히려 더 필요하다.

- [ ] A가 Cloudflare Tunnel을 일부러 잠깐 중단
- [ ] 그 상태에서 AI 초안 / 문서 생성 요청이 **`503 llm_unavailable`**로 끝나고 화면에 **"AI 서버가 수리 중이예요."**가 뜨는지 확인 — **500이나 무한 로딩이면 버그다**(에러 코드가 `llm_unavailable`이 아니면 프론트의 한국어 문구 매핑을 타지 못한다)
- [ ] **비-AI 경로는 그대로 동작하는지** 확인 (로그인, 세션 목록, 메인 피드, 아카이브). 이게 지금의 실질적인 내구성 주장이다
- [ ] 터널 복구 후 **재배포 없이** 정상 동작으로 회복되는지 확인
- [ ] 이 훈련 중 사용자에게 나가는 안내 문구가 실제 대기 시간과 맞는지 확인하고 필요 시 프론트 로딩 UI 보완

## 5. 전체 흐름 리허설

- [ ] 가상 시나리오 2~3개(예: "육아로 인한 공백기", "이직 준비 공백기", "프리랜서 활동 공백기")로 회원가입부터 문서 내보내기까지 전체 흐름을 실제로 완주
- [ ] 각 시나리오에서 근거 없는 문장이 섞이지 않는지(정직성 가드레일), 근거 출처가 정확히 표시되는지 확인

## 6. 신규 기능 동결 및 마무리

> **2026-09-17 갱신 — 이 절의 동결은 실제로 지켜지지 않았다.** `feature/championship-showcase`가
> 9/16~9/17에 신규 기능 5개(트러스트 스코어보드, 데모 모드, GPU 배지, 공유 카드, 문답 예시
> 프리뷰 — [devlog 58~62](../../devlog/PersonB/58_honesty_trust_scoreboard.md) 참고)를 추가해 `dev`/`main`에
> 병합했다. 이건 문서가 낡은 게 아니라 팀이 동결 결정을 실제로 뒤집고 쇼케이스용 기능을 밀어넣은
> 것으로 보인다 — 사실 자체를 숨기지 않고 기록만 남긴다. 앞으로 추가 기능을 더 넣을지는 팀 판단이
> 필요하고, 지금부터는 최소한 아래 항목을 지킬 것을 권장한다.

- [ ] 지금(9/17) 이후로는 정말로 신규 기능 추가 중단, 버그 수정과 발표 준비만 진행하기로 팀 내 재확인
- [ ] 데모 당일을 대비해 [`../person_A_infra_ai/07_server_ops_checklist.md`](../person_A_infra_ai/07_server_ops_checklist.md)의 "데모·투표 기간 시작 전날" 항목을 A·B 함께 재확인

## 검증 기준

- [ ] 실제 배포된 URL만으로 (로컬 서버 없이) 회원가입 → 로그인 → 전체 인터뷰 흐름 → 문서 생성 → 내보내기까지 완주된다
- [ ] 로컬 LLM 서버를 껐을 때 AI 경로는 `503` + "AI 서버가 수리 중이예요."로 정직하게 멈추고, 비-AI 경로(로그인·피드·아카이브)는 계속 동작한다. 터널 복구 시 재배포 없이 회복된다
