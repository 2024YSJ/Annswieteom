# 10. Spark CUDA 크래시 원인 확정 — ollama/ollama#17434 (2026-09-12)

## 배경

09번(모델 교체) 다음 날, 게스트 6세션으로 운영을 검증하다 간헐적 `503 llm_unavailable`을
관찰했다. 처음엔 원인을 몰라 몇 가지를 잘못 추정했다 — 순서대로 기록해 둔다(같은 삽질을
반복하지 않기 위해).

## 틀렸던 추정들

1. **"모델이 JSON 형식을 어겼다"** — 실패율이 `extract_facts`(사실 추출)에만 몰려 있고
   (순차 8.3%, 동시 3건 33.3%), flat-JSON 호출(`extract_period` 등)은 43/43 성공했다는
   측정만 보고 "출력 형식이 복잡한 호출만 실패한다"고 판단했다. **틀렸다** — 실제로는
   `extract_facts` 프롬프트가 가장 길어서(기록물 발췌 + 확정 사실 전체를 담음) 크래시
   임계값을 넘긴 것뿐이었다(아래 참고).
2. **`_collect_stream`이 `message.thinking`을 안 읽어서 빈 content가 나온다** — think 필드
   추측이었다. **틀렸다.**

## 확정된 원인 (Render 로그로 직접 확인)

```
{"error":"an error was encountered while running the model: CUDA error\nCUDA error: an illegal memory access was encountered"}
{"error":"llama-server process no longer running: unknown CUDA error\nCUDA error: an illegal memory access was encountered"}
```

Ollama의 모델 실행 프로세스(`llama-server`)가 GPU 커널 안에서 죽는다. Spark의
`journalctl -u ollama`(root 권한 필요 — `sudo` 없이는 자기 서비스 로그도 안 보인다,
`adm`/`systemd-journal` 그룹 소속이 아니면)로 실제 크래시 스택을 확인했다:

```
ggml-cuda.cu:108: CUDA error: an illegal memory access was encountered
  in function ggml_cuda_kernel_launch at common.cuh:1670
  cudaLaunchKernelEx(&pdl_cfg.cfg, kernel, std::forward<Args>(args)... )
llama-server terminated  error="signal: aborted (core dumped)"
```

거의 동일한 로그 신호(`n_ctx_slot = 8192, n_keep = 4, task.n_tokens = ...`, `common.cuh`의
비슷한 줄 번호)를 가진 공개 이슈가 있다 — **[ollama/ollama#17434](https://github.com/ollama/ollama/issues/17434)**
(같은 하드웨어: DGX Spark GB10, sm_121, `cuda_v13` 빌드). 이슈 원 제보자는 "JSON 스키마 +
`think:false`"를 트리거로 지목했지만, 코멘트의 `reservelab`(같은 하드웨어, Ollama 0.32.13)이
하루를 들여 더 정밀하게 좁혔다:

**진짜 트리거: 모델이 막 재적재된 직후("cold")에, 그 첫 요청의 프롬프트가 Ollama 기본
마이크로배치(`-b/-ub 1024`)를 넘으면 100% 크래시한다.** 이진 탐색으로 경계를 정확히
찾았다 — 1019토큰 정상, 1059토큰 크래시. `think:true`/`false`/생략 셋 다 크래시했다(같은
2000토큰 시스템 프롬프트로 3/3 재현) — 즉 `think`는 원인이 아니라 우연히 같이 있었을 뿐이다.
**warm 상태(이미 한 번 요청을 넘긴 러너)에서는 같은 모양 요청 24연속 무사고**였다 — 이게
왜 간헐적으로 보이는지의 답이다: 재적재 직후 첫 긴 요청에서만 터진다.

이게 우리 로그의 연쇄 크래시를 정확히 설명한다 — 15:02:19 → 35 → 53초에 세 번 연달아
죽었는데, 매번 21GB를 재적재한 직후 다음 긴 요청이 들어와 다시 cold 크래시한 것이다.

## 확정된 해결책

`reservelab`이 cold 러너 기준 10회 반복으로 측정:

| 설정 | 크래시 | 대가 |
|---|---|---|
| 기본값 | 10/10 | — |
| `OLLAMA_FLASH_ATTENTION=0` | 0/10 | 프리필 다소 느려짐(1.12s vs 0.77s), 생성 속도 그대로 |
| `LLAMA_ARG_CTX_CHECKPOINTS=0` | 0/10 | **반복 대화의 프롬프트 캐시가 사라짐**(19000→2500 tok/s) |

메인테이너(`rick-github`)가 `OLLAMA_FLASH_ATTENTION=0`을 제안했고, 다른 제보자(`tomsonlee93`)가
A/B로 완전 해결을 확인했다(다른 모델 회귀 없음).

**우리 앱에는 FA=0이 맞다.** `LLAMA_ARG_CTX_CHECKPOINTS=0`은 반복 대화의 프롬프트 캐시를
꺼버리는데, 우리 인터뷰는 같은 카테고리 안에서 맥락이 계속 늘어나는 대화형이라 그 캐시
이득을 잃으면 손해가 더 크다.

**시도했지만 안 통한 것들**(`reservelab` 기록, 참고용): `GGML_CUDA_DISABLE_FUSION=1`,
`GGML_CUDA_PDL=0`, `GGML_CUDA_DISABLE_GRAPHS=1`, `GGML_CUDA_FORCE_MMQ=1`,
`GGML_CONTEXT_SHIFT=0`, `num_ctx` 8192↔32768 — 전부 크래시 그대로.

## 적용

`docs/checklists/person_A_infra_ai/07_server_ops_checklist.md`의 "처음 설정할 때"와
"문제가 생겼을 때"에 `OLLAMA_FLASH_ATTENTION=0` 절차와 진단 명령을 추가했다. **Spark
SSH는 비밀번호 인증이라 이 세션이 직접 적용할 수 없다 — 사용자가 직접 실행해야 한다.**

앱 쪽은 이 크래시가 재발해도(FA=0을 아직 안 걸었거나, 다른 트리거로 또 죽거나) 사용자
노출을 줄이는 완화책을 넣었다 — 재시도 1회 + 요청 직렬화(PersonB devlog 37).

## 디버깅 교훈

- **`journalctl`은 기본적으로 자기 서비스 로그도 안 보인다.** `adm`/`systemd-journal`
  그룹 소속이 아니면 힌트만 찍고 빈 결과를 준다 — 빈 결과를 "로그가 없다"로 오독하지
  말고 `sudo`를 먼저 시도한다.
- **GitHub 이슈는 제목/본문만으로 판단하지 않는다.** 이 이슈의 제목("think:false"가
  원인)은 사실 최초 제보자의 **틀린 가설**이었고, 진짜 원인은 코멘트 안에 있었다. `gh`나
  브라우저 도구가 코멘트를 못 읽어오면(동적 로딩) GitHub REST API
  (`api.github.com/repos/.../issues/N/comments`)로 직접 받아 확인한다.
- **자기 로그와 남의 이슈가 같은 신호를 내는지 문자 그대로 대조한다.** `n_ctx_slot`,
  `task.n_tokens`, 크래시 파일:줄번호가 거의 일치하는 걸 확인하고서야 "같은 버그"라고
  결론 내렸다 — 증상(간헐적 503)만 보고 넘겨짚었으면 트리거를 계속 틀렸을 것이다.

## 관련 커밋

- `bdc871f` — 07_server_ops_checklist.md 수정 + 이 devlog ([PR #67](https://github.com/2024YSJ/Annswieteom/pull/67))

## 남은 작업

- [ ] 사용자가 Spark에서 `OLLAMA_FLASH_ATTENTION=0` 적용
- [ ] 적용 후 부하 재측정(`backend/scripts/build_spark_bench.py`)으로 크래시 0건 확인
- [ ] 적용됐는데도 재발하면 `qwen2.5:32b` 롤백 검토(체크리스트에 절차 있음)
