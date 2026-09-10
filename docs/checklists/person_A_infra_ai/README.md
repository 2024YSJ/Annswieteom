# A 담당 체크리스트 — 인프라 & AI (4090 PC 보유, 서버 운영 경험 없음)

당신(A)은 명세서에서 "서버를 한 번도 운영해본 적 없는 팀원"으로 지칭되는 사람이다. 걱정할 필요 없다 — 명세서 2-1절, 13-3절, 19절은 정확히 당신을 위해 쓰였고, 아래 체크리스트도 그 눈높이를 그대로 유지했다: **개념 설명 → 명령어 → 확인 방법** 순서로, 한 번에 여러 단계를 묶지 않고 하나씩 진행한다.

## 먼저 읽을 것

**서버가 뭔지, 왜 안전한지 궁금하다면 먼저 명세서 [2-1절](../../specs/annswieteom_detailed_spec.md)을 읽어라.** 한 문장 요약: 당신의 PC에는 Ollama라는 프로그램 하나만 "서버"로 켜두면 되고, Cloudflare Tunnel은 PC 전체가 아니라 딱 포트 11434(Ollama 전용 문) 하나만 인터넷에 연결해준다.

## 담당 폴더 (5절)

- `backend/app/services/llm/` — LLM 어댑터
- `backend/app/services/embedding/` — 임베딩 어댑터
- `backend/app/services/record_pipeline/` — 기록물 파싱·청킹·OCR

## 순서

| 파일 | 내용 | 명세서 절 | 시점 |
|---|---|---|---|
| [01_local_llm_setup.md](01_local_llm_setup.md) | Ollama 설치, 모델 비교·확정 | 3, 4, 10-3 | 1주차 |
| [02_llm_adapter_layer.md](02_llm_adapter_layer.md) | LLMProvider / GeminiProvider / FallbackProvider | 10 | 1~2주차 |
| [03_embedding_pipeline.md](03_embedding_pipeline.md) | 임베딩 어댑터 | 11 | 2주차 |
| [04_record_pipeline.md](04_record_pipeline.md) | 블로그 파싱, 청킹, OCR, 의미 검색 | 13-1, 13-2 | 2주차 |
| [05_cloudflare_tunnel.md](05_cloudflare_tunnel.md) | 로컬 Ollama를 외부에 안전하게 노출 | 13-3 | 2주차 (급하지 않음) |
| [06_consistency_check.md](06_consistency_check.md) | 생성 문장의 사실 일치 여부 자동 검증 | 12-4 | 2~3주차 |
| [07_server_ops_checklist.md](07_server_ops_checklist.md) | 매일/데모 당일 서버 점검 루틴 | 19, 17 | 상시 (2주차부터) |
| [08_dgx_spark_migration.md](08_dgx_spark_migration.md) | 추론 서버를 RTX 4090에서 DGX Spark로 이관 | 2-1, 13-3, 17, 19 | 2026-09-10 ~ 동결(9/16) 전 |

## 막혔을 때 기억할 것 (17절)

이 프로젝트는 A가 담당하는 로컬 서버 쪽에서 무슨 문제가 생기더라도 **서비스 전체가 멈추지 않도록** 설계돼 있다(`FallbackProvider`가 자동으로 Gemini API로 넘어간다). 그러니 Cloudflare Tunnel 설정이나 모델 튜닝에서 며칠 막히더라도 조급해하지 않아도 된다 — 07번 체크리스트의 트러블슈팅 항목부터 확인하면 된다.
