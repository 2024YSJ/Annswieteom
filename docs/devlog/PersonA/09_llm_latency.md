# 09. AI 서버 응답 속도 개선 (2026-09-11)

## 배경

> **결과 (같은 날 후속)**: Spark 벤치 후 운영 모델을 **`qwen3.5:35b-a3b`로 교체**했다 — 아래 "모델 교체" 절.
> 그리고 이번 Spark 벤치에서 32b는 13이 아니라 **6.8 tok/s**로 나왔다(`eval_duration` 기준, 차이의 원인은 미확인 — 트러블슈팅).

운영 추론은 Render → Cloudflare Tunnel/Access → DGX Spark의 Ollama(`qwen2.5:32b`)다. Spark는
메모리 대역폭(273GB/s)이 decode 병목이라 32b가 **약 13 tok/s**다(devlog 08 실측 — 뒤에 6.8로 정정). prefill은 빠르다.
그래서 응답 시간은 거의 이 식으로 정해진다.

```
응답 시간 ≈ (출력 토큰 수 ÷ 13 tok/s) × (한 요청에서 순차로 부르는 LLM 호출 수)
```

줄이는 방법은 셋뿐이다: ① 출력 토큰 줄이기 ② tok/s 올리기(모델) ③ 요청 경로의 호출 수 줄이기.
데모 주간(9/16~20) 전이라 **품질 재검증 없이 되는 ①③을 구현**하고, ②는 판단 도구(A/B 스크립트)까지만 만들었다.

## 완료

- [x] **0단계 계측**: 호출마다 `llm <메서드> model=… wall=… load=… prefill=…tok out=…tok (… tok/s)` 한 줄을 남긴다.
  Ollama 스트림 마지막 줄(`done:true`)의 `eval_count`/`eval_duration` 등을 버리던 걸 살렸다.
- [x] **`app.*` 로거를 INFO로 연다**(`main.py`). 로깅 설정이 아예 없어서 지금까지 `logger.info`가 운영 로그에 한 줄도 안 찍혔다.
- [x] **`extract_facts`가 발췌 원문을 다시 쓰지 않게**: 모델은 `based_on.chunk_ids`만 내고, text/published_at은
  서버가 프롬프트에 넣었던 발췌에서 채운다(`_parse_based_on`). 옛 형식(`excerpts:[{chunk_id,text}]`)으로 답해도 chunk_id만 읽는다.
- [x] **`judge_sufficiency`의 `reason` 제거**: 어디서도 읽지 않았고, `sufficient` 뒤에 나오니 판단에도 영향이 없었다.
- [x] **활동 기간 추론을 confirm 응답 뒤로**: `interview_confirm`이 judge_drilldown·draft_answer보다 먼저 순차로 부르던 걸
  BackgroundTasks(`infer_category_period_in_background`)로 옮겼다. 싼 게이트(`_period_inference_needed`)는 요청 안에서 먼저 본다.
- [x] **임베딩**: `bge-m3` 요청에 `keep_alive: -1`. 문서 생성의 일관성 검사를 문장마다 1회 → **카테고리당 1회**로 묶었다
  (`evaluate_sentences_consistency`, 같은 텍스트는 한 번만 보냄). 재생성 경로는 단건 함수 그대로.
- [x] **`LOCAL_LLM_DISABLE_THINKING`** 설정(기본 false): 켜면 `"think": false`를 싣는다.
- [x] **A/B 비교 스크립트** `backend/scripts/compare_llm_models.py`.
- [x] 테스트 추가(인용 채우기, 모르는 chunk_id, think 플래그, 계측 로그, 배치 일관성 검사, 임베딩 keep_alive). 전체 pytest 통과.

## 미완 / 이번 범위 밖

- [ ] **HTTP 연결 재사용(공유 `httpx.AsyncClient`)** — 계획에 넣었다가 뺐다. 아래 "결정" 참고.
- [x] **운영 모델 교체** — Spark 벤치 후 `qwen3.5:35b-a3b` + `LOCAL_LLM_DISABLE_THINKING=true`로 교체, 운영 `/health/llm`에서 `model_name` 확인(아래 "모델 교체").
- [ ] **3단계: 동시 처리(`OLLAMA_NUM_PARALLEL` + 문서 생성 카테고리 병렬화)** — 데모 이후. 아래 "남은 작업".
- [ ] 배포 후 Render 로그의 `llm …` 줄로 before/after 실측값을 이 문서에 채우기.

## 핵심 결정

**왜 모델 교체보다 출력 축소를 먼저 했나.** 모델 교체는 효과가 가장 크지만(아래 표) 16개 프롬프트의 한국어 품질과
정직성 가드레일을 다시 검증해야 한다. 출력 축소는 동작이 같고 결과만 빨라지므로 데모 전에 안전하다.
`extract_facts` 변경은 정직성도 좋아진다 — 예전에는 모델이 **다시 쓴** 발췌 text를 그대로 저장했으니, 모델이 발췌를
바꿔 쓰면 원문과 다른 문장이 "기록물 인용"으로 남을 수 있었다.

**기간 추론을 백그라운드로 옮긴 대가.** 방금 끝난 턴의 `followup_budget`에는 새 기간이 반영되지 않고 다음 confirm부터
반영된다. 기간은 원래 "실패해도 조용히 넘기는" 커버리지 메타데이터이고 예산 보너스는 늦어도 한 턴이라 받아들였다.
워커는 사실을 새로 읽어 게이트를 다시 보므로 그 사이 사용자가 직접 지정한 기간(`user_set`)은 덮어쓰지 않는다.
백그라운드 작업은 자기 세션이 필요해서 `get_background_session_factory` DI 훅을 새로 뒀다 — `AsyncSessionLocal`을
직접 쓰면 테스트의 `get_db` 오버라이드가 닿지 않아 테스트가 설정 DB로 붙는다.

**`think` 필드를 기본으로 보내지 않은 이유.** 로컬 Ollama 0.33.3은 비-thinking 모델(qwen2.5)에 `think:false`를 보내도
200으로 무시하는 걸 확인했지만, Spark의 Ollama 버전에서는 확인하지 않았다. 운영 동작을 바꿀 이유가 없는 필드라 설정으로 뺐다.

**루트가 아니라 `app` 로거만 INFO로 연 이유.** 루트를 올리면 httpx가 요청 URL을 INFO로 찍는데, 고용24 호출은
`authKey`를 쿼리스트링에 싣는다 — 키가 Render 로그에 남는다.

**공유 HTTP 클라이언트를 뺀 이유.** 이득은 호출당 TLS 핸드셰이크(Render→Cloudflare 엣지, 대략 0.1초 안팎)인데 LLM 호출
하나가 수 초~수십 초라 1~2% 수준이다. 반면 모듈 수준 `AsyncClient`는 이벤트 루프에 묶여서 pytest(테스트마다 새 루프)와
기존 테스트 스텁(`httpx.AsyncClient`를 갈아끼우는 방식) 전부를 손봐야 한다. 데모 전에 들일 비용이 아니었다.

## 모델 후보 (2단계 — 판단 자료)

MoE는 토큰당 활성 파라미터만 읽으므로 대역폭이 병목인 Spark에서 dense보다 몇 배 빠르다. 공개 벤치마크(Spark + Ollama):

| 모델 | 구조 | decode tok/s |
|---|---|---|
| `qwen2.5:32b` (현재, 우리 실측) | dense | 약 13 |
| Qwen 3.5 35B-A3B | MoE | 약 48 |
| Gemma 4 26B | MoE | 약 53 |
| gpt-oss:20b | MoE | 약 50 |
| gpt-oss:120b | MoE | 약 42~60 |

출처: [tokenstead DGX Spark benchmarks](https://tokenstead.ai/guides/dgx-spark-benchmarks-2026),
[kubesimplify Qwen3.8-27B on Spark](https://blog.kubesimplify.com/qwen3-8-27b-on-dgx-spark). **외부 수치는 참고용이고,
우리 프롬프트로 스크립트를 돌린 값이 기준이다.**

### 실행 방법 (사용자)

1. Spark에서: `ollama pull <후보 태그>` (정확한 태그는 `ollama.com/library`에서 확인. 32b는 지우지 않는다 — 롤백용)
2. 노트북 `backend/.env`를 **잠시** 운영 터널로: `LOCAL_LLM_BASE_URL=https://llm.annswieteom.com`, Access 토큰 두 개 채우기
   (`docs/checklists/00_shared/04_local_dev_environment.md`의 절차 그대로)
3. `cd backend; .\venv\Scripts\python.exe scripts/compare_llm_models.py qwen2.5:32b <후보> --think-off --out compare.md`
   (`--think-off`는 thinking 기본 모델용. 비교 대상 모두에 같이 걸리지만 qwen2.5에는 영향 없음)
4. `compare.md`에서 속도 표와 ⚠ 표시(인용 없는 문장, 근거에 없는 숫자, 기록물 인용 누락)를 보고, 문서 생성 원문을 읽어 한국어를 판단
5. `.env`를 로컬 값으로 되돌리고 토큰을 다시 비운다. 스크립트는 끝날 때 운영 모델이 아닌 후보를 Spark 메모리에서 내린다
6. 채택하면 Render의 `LOCAL_LLM_MODEL_NAME`(+필요 시 `LOCAL_LLM_DISABLE_THINKING=true`)만 바꾼다. 롤백은 그 반대

로컬 스모크(`qwen2.5:3b-instruct` vs `llama3.2:3b`, 노트북 GPU — 스크립트 동작 확인용이지 판단 자료가 아니다):
두 모델 모두 5개 케이스가 끝까지 돌았고 합계 77s / 85s, 18~20 tok/s. 둘 다 `extract_facts`에서 답변과 일치하는 발췌를
인용하지 않아 ⚠가 떴다 — 스크립트가 잡아야 할 종류의 품질 차이를 실제로 잡는다는 확인이기도 하다.

## 모델 교체 (2026-09-11)

### 벤치 방법
노트북에서 터널로 재는 대신 **Spark 안에서 `localhost:11434`로** 쟀다(터널·Access 토큰이 필요 없고, 순수 모델 속도만 본다).
`backend/scripts/build_spark_bench.py`가 앱 코드로 **실제 프롬프트**(PR #62 문구 포함)를 렌더링해 파이썬 기본 라이브러리만 쓰는
스크립트 하나를 만들고, 그걸 Spark 터미널에 붙여넣어 돌렸다. 요청 옵션도 앱과 같다(`format:json`, `num_ctx` 8192, 호출별 temperature, `think:false`).
웹사이트 공백기 채우기 흐름 6단계: 카테고리 추출 → 사실 추출(블로그 인용 기대) → 파고들기 판단 → 입력창 초안 → 충분성 판단 → 문서 생성.
자동 판정: 앱 파서가 거부할 응답, 인용 없는 문장, 인용한 근거에 없는 숫자, 기록물 인용 누락, 숨은 추론 출력.

### 결과 (Spark, Ollama 0.33.3, 각 1회)

| 단계 | qwen2.5:32b | qwen3.5:35b-a3b | gemma4:26b |
|---|---|---|---|
| extract_categories | 11.8s · 6.9 t/s | 2.3s · 41.1 t/s | 2.2s · 67.2 t/s |
| extract_facts | 24.0s · 6.8 t/s | 6.4s · 40.8 t/s | 4.0s · 64.0 t/s |
| judge_drilldown | 8.7s · 6.9 t/s | 2.5s · 41.2 t/s | 15.3s · 50.0 t/s |
| draft_answer | 10.5s · 6.9 t/s | 1.9s · 42.1 t/s | 1.7s · 51.8 t/s |
| judge_sufficiency | 2.3s · 7.8 t/s | 0.8s · 44.5 t/s | 0.8s · 56.7 t/s |
| generate_document | 34.5s · 6.8 t/s | 6.1s · 41.5 t/s | 5.2s · 60.3 t/s ⚠ |
| **합계** | **91.9s** | **20.1s** | **29.1s** |

`qwen3.5:35b-a3b` 3회 반복: 합계 20.5 / 17.1 / 17.6초, `should_ask=True`·`sufficient=False`로 매번 같고 경고 0건.

### 판단
- **`qwen3.5:35b-a3b` 채택.** 약 6배 빠른 decode, 정직성 경고 0건. 사실 추출에서 "오픈 준비"와 "음료 제조"를 별개 사실로 나누고
  블로그 인용도 정확했다. 문서에서 사실 1·2를 한 문장으로 묶으면서 둘 다 인용했다.
- **`gemma4:26b` 탈락.** 가장 빠르지만 문서 문장 **본문에 `[1]` 같은 인용 번호를 그대로 적었고**(그대로 경력기술서에 찍힌다),
  첫 문장이 "…수행하며 [1]"로 끊겼다. 파고들기 판단은 출력 1초 분량인데 15.3초 — 원인은 1회 측정으로 모름.
- **바뀌는 동작:** qwen3.5는 사실 4개로는 `sufficient=False`(32b·gemma는 True). 고정 질문 뒤 후속 질문 예산을 더 쓴다 —
  인터뷰가 카테고리당 한두 턴 길어질 수 있지만 턴당 대기는 크게 줄었다. 부담되면 `interview_sufficiency.jinja` 기준을 조정.
- 세 모델 모두 입력창 초안에서 약간 추측한다("수기로 관리" 등). 초안은 원래 추측해도 되는 출발점이라 교체와 무관.

### 교체 / 롤백
- Render: `LOCAL_LLM_MODEL_NAME=qwen3.5:35b-a3b`, `LOCAL_LLM_DISABLE_THINKING=true` → 재배포 후 `GET /api/v1/health/llm`의
  `model_name`이 `qwen3.5:35b-a3b`인 것 확인. (이 엔드포인트는 연결만 본다 — 실제 생성은 사이트에서 한 번 돌려 확인)
- 롤백: `qwen2.5:32b` + `LOCAL_LLM_DISABLE_THINKING=false`. 32b는 Spark에 남겨 둔다.
- 운영 체크리스트(07), CLAUDE.md, 스펙, 로컬 개발 문서, `infra/cloudflare/verify_tunnel.*`(기본 모델 + `think:false`)를 새 모델 기준으로 갱신.

## 트러블슈팅

| 문제 | 원인 | 해결 |
|---|---|---|
| 계측 로그를 넣을 곳을 찾다가, 기존 `logger.info`(피드 수집 등)가 운영에서 한 번도 안 보였을 것을 발견 | 앱 어디에도 로깅 설정이 없어 루트 기본 레벨(WARNING)이 적용됨 | `main.py`에서 `app` 로거에만 핸들러 + INFO |
| 기간 추론을 백그라운드로 옮기면 테스트가 설정 DB로 붙음 | 워커가 여는 세션은 `get_db` 오버라이드 밖 | `get_background_session_factory` 훅 + conftest 오버라이드 |
| 문서엔 32b가 약 13 tok/s였는데 벤치에선 6.8 | **원인 미확인.** devlog 08의 13은 844토큰/63초(총 시간 역산)라 순수 decode는 그보다 빨라야 맞는데, 이번 `eval_duration` 기준은 절반이다. 측정 조건(동시 운영 요청, Ollama 버전, 벤치 중 다른 모델 적재 여부)이 달랐을 수 있다 | 운영 모델을 바꿨으므로 32b를 다시 잴 필요는 크지 않다. 새 모델 속도는 운영 `llm …` 로그로 계속 확인 |
| Spark SSH가 비밀번호 인증이라 원격 실행 불가, 긴 스크립트를 옮기기 번거로움 | 키 인증 미설정, 저장소는 private라 Spark가 raw URL로 받을 수 없음 | 스크립트를 파이썬 기본 라이브러리만 쓰는 파일 하나로 만들어 heredoc 한 번 붙여넣기로 저장·실행 |

## 관련 커밋

- `84f8d84` 계측 로그, 출력 축소(extract_facts chunk_ids / sufficiency reason), 기간 추론 백그라운드화, 임베딩 keep_alive·배치, think 설정, A/B 스크립트
- `a5063f5` 이 devlog와 스펙 10-2절

## 남은 작업

- **3단계 동시 처리 (데모 이후)**: decode는 대역폭 병목이라 여러 요청을 배치하면 가중치 한 번 읽기로 함께 처리한다
  (공개 측정: 4병렬에서 총 처리량 약 1.8배, 요청당 속도는 하락 —
  [Ollama 병렬 처리](https://www.glukhov.org/llm-performance/ollama/how-ollama-handles-parallel-requests/),
  [8 에이전트 실험](https://jangwook.net/en/blog/en/local-llm-concurrent-requests-num-parallel-experiment/)).
  켜면 문서 생성의 카테고리 루프를 `asyncio.gather` + 세마포어로 돌릴 수 있다. 다만 `08_dgx_spark_migration.md`가
  `OLLAMA_NUM_PARALLEL`을 건드리지 않는다고 못박았고 `job_search.py`의 순차 처리와 시간 예산이 그 전제에 기대므로,
  둘 다 재측정해야 한다. `num_ctx`(8192) × 병렬 수만큼 KV 캐시도 늘어난다.
- **권장하지 않음**: vLLM/TensorRT-LLM 런타임 교체(추측 디코딩 등 효과는 크지만 GB10 CUDA 셋업 위험), Q3 이하 양자화(한국어 품질),
  `num_ctx` 상향(지연만 증가).
- 배포 후 운영 `llm …` 로그로 `extract_facts`(인용 있는 턴)와 `interview_confirm` 체감 시간 before/after 기록.
