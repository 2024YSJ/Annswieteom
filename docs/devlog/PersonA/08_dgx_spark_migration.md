# A-8. 추론 서버를 DGX Spark로 이관 — 저장소 준비

관련 체크리스트: [person_A_infra_ai/08_dgx_spark_migration.md](../../checklists/person_A_infra_ai/08_dgx_spark_migration.md)
날짜: 2026-09-10
브랜치: `feature/dgx-spark-migration` (base: `dev`)

---

## 배경

추론 서버를 **RTX 4090(Windows) → NVIDIA DGX Spark(GB10, aarch64, DGX OS)**로 완전 교체한다. 4090은 이번에 바로 내린다.

작업을 시작하면서 확인한 사실 두 가지가 계획 전체를 바꿨다.

1. **프로덕션 AI는 이미 죽어 있었다.** `https://llm.annswieteom.com`에 fresh curl → Cloudflare **1033 / HTTP 530**. 터널에 커넥터가 붙어 있지 않다. 즉 이건 "돌아가는 걸 옮기는" 작업이 아니라 "죽은 걸 새 하드웨어로 되살리는" 작업이다.
2. **A-5의 실서버 절차(8절)는 한 항목도 실행되지 않았다.** 그리고 그 절차가 담긴 `feature/cloudflare-tunnel` 브랜치는 `dev`에 머지되지도 않은 상태였다 — `dev`에 있는 05번은 체크박스가 전부 빈 옛 버전이었다.

## 완료 항목 (저장소 쪽)

- [x] `feature/cloudflare-tunnel`(5커밋)을 `dev`에 머지 — 403 Host 헤더 해법, "서비스는 Running인데 터널은 죽음" 해법, 스펠링 통일, 스펙 파일 리네임이 전부 이 브랜치에만 있었다
- [x] A-8 체크리스트 신설, A-5 8절을 그 포인터로 교체
- [x] 문서 전반에서 Gemini 폴백 전제와 Windows 호스트 전제 제거 (07, 03_deployment, 04_local_dev_environment, CLAUDE.md, architecture.md, README 2개, 스펙 §2·§4·§10·§11·§13·§15·§17·§19)
- [x] `infra/cloudflare/config.linux.yml.example`, `verify_tunnel.sh` 신설. `verify_tunnel.ps1`은 유지하되 Access 헤더 파라미터 추가 + 힌트를 systemd로 교체
- [x] 두 verify 스크립트를 "Ollama is running" 확인에서 **계약 검증 4항목**으로 승격
- [x] `.env.example`의 죽은 Gemini 스텁 주석 제거, Railway → Render, bge-m3 안내 추가
- [x] Cloudflare Access 서비스 토큰 헤더 전송 (`Settings.ollama_headers()` + 어댑터 2곳)
- [x] 생성 타임아웃 45 → 240초 상수화, `/api/chat` 스트리밍 전환, `keep_alive` 고정
- [x] `job_search` 시간 예산 90 → 600초
- [x] `document.py`의 `/generate`·`/document/regenerate`에 `LLMUnavailableError` → 503 처리 추가 (기존 버그)
- [x] `GET /api/v1/health/llm` 신설
- [x] `pytest` 354 passed

## 미완 — 온-머신 작업 (사람이 해야 함)

체크리스트 08번의 1~10절 전부. 요약하면:

1. Spark에서 `snap set ollama host="0.0.0.0:11434"`, `qwen2.5:72b` + `bge-m3` + `qwen2.5:32b` pull
2. 계약 검증 4항목(특히 임베딩 길이 1024)과 GPU 실사용 확인
3. cloudflared arm64 설치, `annswieteom-llm-spark` 터널 생성, `--overwrite-dns`로 호스트명 인수
4. Cloudflare Access 애플리케이션 + 서비스 토큰 발급, `.env`/Render에 반영
5. 외부 기기·재부팅·휴대폰 데이터망 확인
6. 브라우저로 한 세션 완주 + `POST /generate` 실측 시간 기록
7. 4090 정리 (터널 삭제, 자격증명 파일 삭제)

**실측값을 여기에 채워야 한다** — 4절의 첫 바이트/총 시간/tok/s, 그리고 문서 생성 실측 시간. 아래 "핵심 결정 사항"의 두 벽이 실제로 어디서 걸리는지가 그 숫자로만 판명된다.

## 핵심 결정 사항과 이유

### 72b를 유지하되, 그 대가를 코드에 명시했다

Spark는 128GB 통합메모리라 4090의 24GB로는 불가능한 크기를 담지만, **메모리 대역폭 273GB/s가 decode 벽**이다. dense 72B Q4(약 43GB)는 토큰마다 그 가중치를 전부 통과시켜야 해서 초당 몇 토큰 수준이다. 즉 이번 이관은 "더 큰 모델을 얻고 속도를 잃는" 교환이고, 하드웨어에서 바로 나오는 제약이라 튜닝으로 벗어날 수 없다. 이 사실 위에서 두 가지가 따라왔다.

**타임아웃 45 → 240초.** 15개 호출부가 각자 `45.0`을 들고 있었다. 4090+14b에서 호출당 4.0초였던 값이고, 72b에서는 문서 생성 한 카테고리도 못 끝낸다. 상수 하나(`_GENERATE_TIMEOUT`)로 모으고, `timeout=45.0` 리터럴이 다시 생기지 않는지 검사하는 테스트를 붙였다 — 다음 서버 교체 때 14곳만 고치고 한 곳을 빠뜨리는 걸 막는 게 목적이다.

**스트리밍 전환은 성능이 아니라 Cloudflare 때문이다.** 이게 이번 작업에서 가장 놓치기 쉬운 지점이었다. Cloudflare 무료·Pro·Business 플랜의 프록시 read timeout(약 100초)은 고정이고, **첫 바이트까지의 시간**에 걸린다. `stream: false`로 72b에 문서 생성을 시키면 몇 분간 아무것도 안 돌아오므로 **엣지가 524를 내고, 우리 타임아웃을 240초로 올려도 소용이 없다 — 요청이 우리한테 돌아오지도 않기 때문이다.** 조각으로 받으면 첫 토큰만 그 100초를 이기면 되고 나머지 예산은 우리 것이 된다. 그래서 `stream: true` + NDJSON 이어붙이기는 전송 방식 변경이지 인터페이스 변경이 아니다 — 호출부 15곳은 여전히 완성된 JSON 문자열 하나를 받는다.

스트리밍이 하나 바꾸는 것: Ollama는 **HTTP 200으로 스트림을 시작한 뒤에도** `error` 필드로 실패를 알린다(모델 없음 등). `raise_for_status()`로는 안 잡히므로 조각마다 검사한다.

**`keep_alive` 고정.** 43GB를 호출마다 재적재하면 그 적재 시간만으로 위 100초를 넘긴다. 서버 환경변수로 줄 수도 있지만 Spark의 Ollama는 snap이라 설정 키가 제한적이어서, 요청에 실어 보내는 쪽이 확실하다.

### `num_ctx`와 임베딩 모델은 일부러 건드리지 않았다

`_NUM_CTX = 8192`를 설정 필드로 빼는 건 방향이 반대다. 72b의 첫 리스크는 컨텍스트 부족이 아니라 지연이고, `num_ctx`를 올리면 KV 캐시와 토큰당 지연이 같이 오른다. 대신 체크리스트 4절에 "가장 큰 프롬프트로 실측" 항목을 넣어 동결 이후 판단 근거를 남겼다.

`bge-m3`도 하드코딩으로 남겼다. 1024는 취향이 아니라 세 테이블의 `VECTOR(1024)` **컬럼 타입**이고, 설정으로 빼면 오타가 부팅 실패가 아니라 **요청 도중의** `EmbeddingDimensionMismatchError`로 바뀐다. 그건 지금보다 나쁘다. 문제는 설정 가능성이 아니라 **문서 공백**이었다 — `bge-m3`는 `CLAUDE.md`에도 `.env.example`에도 한 번도 등장하지 않았고, 셋업 문서 중 언급은 `01_local_llm_setup.md` 한 줄뿐이었다. 새 기계에서 빼먹으면 예외도 배너도 없이 "정렬이 좀 이상하다"로만 보인다. 그래서 모델을 pull하는 모든 자리에 굵게 적었다.

### 롤백은 하드웨어가 아니라 모델이다

4090을 바로 내리므로 DNS를 되돌릴 기계가 없다. 그래서 롤백 경로를 `qwen2.5:32b` **미리 pull**로 만들었다 — 그러면 롤백이 Render 환경변수 `LOCAL_LLM_MODEL_NAME` 한 줄 교체 + 재시작이 된다. 체크리스트 0절 맨 위와 07번 데모 전날 항목에 같은 문장으로 두 번 적었다.

### 문서에서 제일 위험했던 건 "안심시키는 문장"이었다

폴백은 2026-09-09에 사라졌는데, 서버 담당자를 안심시키는 문장들이 그대로 남아 있었다:

- `07_server_ops_checklist.md:42` — "`FallbackProvider`가 자동으로 Gemini로 넘어간다"
- `person_A_infra_ai/README.md:29` — 같은 주장. **서버 운영 경험 없는 팀원용 "막혔을 때" 절**에 있었다
- `07:29`, `03_deployment.md:43-48`, 스펙 §2·§13-3·§17·§19 — "터널을 꺼서 Gemini로 전환되는지 확인"

전부 같은 훈련을 정직한 기대값으로 바꿨다: 터널을 끊으면 AI 경로는 `503 llm_unavailable` + "AI 서버가 수리 중이예요."여야 하고(500이나 무한 로딩이면 버그), 로그인·피드·아카이브 같은 **비-AI 경로는 그대로 동작해야** 한다. 마지막 절이 지금 우리가 할 수 있는 유일한 내구성 주장이다.

`01_repo_and_env_setup.md`의 열린 항목 두 개는 낡은 게 아니라 **해로웠다** — "Gemini API 키 발급"과 "Render에 `GEMINI_API_KEY` 등록"은 pydantic-settings 기본 `extra="forbid"` 때문에 그 키의 존재 자체가 부팅을 죽인다. 그래서 "추가하라"에서 "지워졌는지 확인하라"로 뒤집었다.

Windows 절은 **통째로 지우지 않았다.** 추론 호스트만 Linux이고 개발 기계 두 대는 여전히 Windows다. `CLAUDE.md`의 "Windows-Specific Notes"를 "Platform Notes"로 바꿔 개발 기계 / 추론 호스트 두 목록으로 쪼갰다.

### 헬스 엔드포인트를 지금 만든 이유

`health_check()`가 양쪽 프로바이더에 있는데 프로덕션 호출자가 **0개**였다(유일한 호출자가 `scripts/verify_embedding.py`). 폴백이 없으니 서버가 안 닿는다는 사실을 사용자가 인터뷰 중간에 503을 맞고서야 알게 된다.

그리고 노트북에서 터널로 쏘는 curl은 **다른 경로**를 검사한다. 실제 경로는 Render → Cloudflare Access → Spark이고 Render의 환경변수(모델 이름, Access 토큰)까지 얽혀 있다. `GET /api/v1/health/llm`이 그 전체를 한 요청으로 확인하는 유일한 지점이다.

**`app/main.py`의 `/health`와 합치지 않은 게 설계의 핵심이다.** 그건 Render의 플랫폼 liveness probe라 의존성 없이 즉시 답해야 한다. 거기서 5초짜리 터널 호출을 하기 시작하면 Spark 장애 때 Render가 "서비스가 죽었다"고 판단해 재시작 루프에 빠지고, **부분 장애가 전체 장애가 된다.** 그 분리를 고정하는 테스트를 넣어뒀다.

항상 200을 주는 것도 같은 성격의 결정이다. 운영자용 프로브가 503을 내면 "AI 서버만 죽었다"와 "앱 전체가 죽었다"를 구분할 수 없어져 존재 이유가 사라진다.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `dev`의 `05_cloudflare_tunnel.md`에 8절도, 403 해법도, 서비스 위장 해법도 없음 | `feature/cloudflare-tunnel`(5커밋)이 origin에 있는데 머지가 안 된 상태였다 | 먼저 `dev`에 머지. rebase가 아니라 merge — 커밋이 이미 origin에 있고 devlog 규칙이 커밋 해시 참조를 요구한다 |
| 머지 후 `docs/architecture.md`의 스펙 링크가 깨짐 | 브랜치가 스펙 파일을 리네임했지만 `architecture.md`는 그 브랜치의 merge-base에 없어서 브랜치가 못 고쳤다 | 단독 커밋으로 수정. 머지가 만든 회귀라 다른 변경과 섞지 않았다 |
| 머지 충돌 해결 시 `Railway`가 되살아날 위험 | 브랜치의 05번 65행이 아직 "배포 환경(Railway)"였고, `dev`는 그 줄을 Render로 고쳐둔 상태(`0849608`) | 브랜치 쪽(상위집합)을 채택하되 그 한 줄만 손으로 Render로 되살렸다 |
| `pytest`에서 feed/youthcenter 3개 실패 | 이 변경과 무관 — 그 테스트들은 소스 레지스트리가 비어 있지 않다고 단정해서 `WORKNET_*` 키가 환경에 있어야 통과한다. worktree에는 `.env`가 없다 | 키를 넣고 재실행해 354 passed 확인. `.env` 없는 체크아웃에서는 이 3개가 원래 실패한다 |
| 기존 `test_local_ollama.py` 12개가 전부 깨질 위험 | httpx 스텁의 `post(url, json)`이 새 `headers=` 인자를, 그리고 나중엔 `client.stream(...)`을 못 받는다 | 스텁을 스트리밍 형태로 다시 쓰고, 기록한 헤더는 반환 튜플을 넓히지 않고 `canned` 딕셔너리에 얹었다 — 12개 테스트를 안 건드리려고 |
| 긴 Bash heredoc이 `unexpected EOF`로 끊김 | 명령 문자열이 길어지면 heredoc 종료 토큰까지 도달하지 못한다 | 긴 편집은 스크립트 파일로 쓴 뒤 실행. 한국어 문자열을 유니코드 이스케이프로 넣다가 `추론`을 `추로`로 오타내기도 해서, 그 뒤로는 직접 파일에 썼다 |

## 관련 커밋

| 해시 | 내용 |
|---|---|
| `4b52a45` | `feature/cloudflare-tunnel` → `dev` 머지 |
| `c4f4b30` | 머지가 깨뜨린 스펙 링크 수정 |
| `6f3ef99` | A-8 체크리스트 신설, A-5 8절 포인터화 |
| `e5cdf38` | 문서 전반의 Gemini 폴백·Windows 호스트 전제 제거 |
| `901368f` | Linux cloudflared 템플릿 + 계약 검증 스크립트 |
| `eb4831e` | 죽은 Gemini env 스텁·Railway 잔재 제거 |
| `f0a4cf3` | Cloudflare Access 서비스 토큰 헤더 전송 |
| `3af8b8f` | 타임아웃 상향 + `/api/chat` 스트리밍 (+ job_search 예산, document 503) |
| `abba061` | 운영자용 LLM 헬스 엔드포인트 |

## 남은 작업

- **온-머신 작업 전체** (위 "미완" 절). 이게 진짜 완료 기준이다.
- 실측값 채우기: 첫 바이트/총 시간/tok/s, `POST /generate` 실측.
- **72b에서도 100초 벽을 못 넘으면** 문서 생성을 백그라운드 태스크 + 상태 폴링으로 바꿔야 한다. `records` 파이프라인이 이미 그 패턴이라(`api/records.py`, `RecordStatusRow.tsx`) 발명할 건 없지만 별도 작업 분량이다.
- `frontend/components/LoadingNotice.tsx`의 "최대 1분 정도" 문구가 72b 문서 생성에서 거짓이 된다. 실측 후 조정.
- **한국어 출력 품질을 프로덕션 모델 크기에서 처음 보는 자리다.** `docs/devlog/PersonB/23`에 `extract_activity_period` 프롬프트가 로컬 3b의 표면 민감도에 맞춰 튜닝된 뒤 큰 모델에서 재확인된 적이 없다고 남아 있다. `extract_categories`와 `extract_activity_period`를 검증 목록 맨 앞에 둘 것.
- 9/21 이후: `infra/cloudflare/config.yml.example`(Windows용)과 문서의 Windows 추론 호스트 잔재 정리.
- 이 브랜치는 아직 push하지 않았다. `dev`의 머지 커밋도 로컬에만 있다.
