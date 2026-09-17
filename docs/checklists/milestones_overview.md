# 마일스톤 개요 (주차별) — 폴더별 체크리스트 매핑

근거: 명세서 16절
마감: 2026-09-20

각 마일스톤이 끝날 때, 아래 "검증 기준"을 실제로 통과하는지 확인한 뒤 다음으로 넘어간다.

브랜치 흐름은 항상 `feature/*` → `dev` (PR) → (마일스톤 체크포인트에서만) `main`이다. 각 표의 "브랜치" 열은 그 마일스톤 동안 열려 있을 브랜치 이름이며, 전체 전략과 매핑표는 [00_shared/01_repo_and_env_setup.md](00_shared/01_repo_and_env_setup.md) 4절에 있다.

## 마일스톤 1 — 기반 다지기 (1주차)

| 담당 | 체크리스트 | 브랜치 |
|---|---|---|
| 공용 | [00_shared/01_repo_and_env_setup.md](00_shared/01_repo_and_env_setup.md) | `dev`에 직접 |
| 공용 | [00_shared/02_database_schema.md](00_shared/02_database_schema.md) | `feature/db-schema` |
| B | [person_B_frontend_backend/01_auth.md](person_B_frontend_backend/01_auth.md) | `feature/auth` |
| A | [person_A_infra_ai/01_local_llm_setup.md](person_A_infra_ai/01_local_llm_setup.md) | 없음(로컬 설치) |
| A | [person_A_infra_ai/02_llm_adapter_layer.md](person_A_infra_ai/02_llm_adapter_layer.md) (골격만, 로컬 테스트로 충분) | `feature/llm-adapter` |

**검증 기준**: 회원가입 → 로그인 → 토큰으로 인증된 API 호출이 실제로 동작한다.

## 마일스톤 2 — 인터뷰 흐름 (1~2주차)

| 담당 | 체크리스트 | 브랜치 |
|---|---|---|
| B | [person_B_frontend_backend/02_interview_state_machine_api.md](person_B_frontend_backend/02_interview_state_machine_api.md) (더미 텍스트로 우선 진행) | `feature/interview-flow` |
| A | [person_A_infra_ai/02_llm_adapter_layer.md](person_A_infra_ai/02_llm_adapter_layer.md) (실제 동작 완성) | `feature/llm-adapter` |

**검증 기준**: 카테고리 하나를 끝까지(빈도→업무→성과) 확인/정정해서 `confirmed_facts`에 실제로 저장되는지 확인. 로그인 → 기간 입력 → 카테고리 선택 → AI 초안 확인/정정까지 실제로 돌아간다.

## 마일스톤 3 — 기록물 연동 (2주차)

| 담당 | 체크리스트 | 브랜치 |
|---|---|---|
| A | [person_A_infra_ai/03_embedding_pipeline.md](person_A_infra_ai/03_embedding_pipeline.md) | `feature/embedding-pipeline` |
| A | [person_A_infra_ai/04_record_pipeline.md](person_A_infra_ai/04_record_pipeline.md) | `feature/record-pipeline` |
| A | [person_A_infra_ai/05_cloudflare_tunnel.md](person_A_infra_ai/05_cloudflare_tunnel.md) | 없음(또는 `chore/cloudflare-tunnel`) |
| B | [person_B_frontend_backend/03_records_feature.md](person_B_frontend_backend/03_records_feature.md) | `feature/records-feature` |

**검증 기준**: 블로그 URL을 넣으면 해당 기간 게시물이 초안 생성 시 근거로 실제 반영된다.

## 마일스톤 4 — 문서 생성 (2~3주차)

| 담당 | 체크리스트 | 브랜치 |
|---|---|---|
| B | [person_B_frontend_backend/04_document_generation.md](person_B_frontend_backend/04_document_generation.md) | `feature/document-generation` |
| A | [person_A_infra_ai/06_consistency_check.md](person_A_infra_ai/06_consistency_check.md) | `feature/consistency-check` |

**검증 기준**: 카테고리 여러 개를 끝까지 진행했을 때, 근거 없는 문장이 섞이지 않고 각 문장에 출처가 표시된다.

**➡ 이 마일스톤이 끝나면 처음으로 `dev → main` 승격 PR을 만든다** ([00_shared/03_deployment.md](00_shared/03_deployment.md) 0번 항목) — 마일스톤 5의 배포가 이 지점부터 가능해진다.

## 마일스톤 5 — 배포 및 안정화 (3주차)

| 담당 | 체크리스트 | 브랜치 |
|---|---|---|
| 공용 | [00_shared/03_deployment.md](00_shared/03_deployment.md) | `chore/deploy-setup` + `dev → main` |
| A | [person_A_infra_ai/08_dgx_spark_migration.md](person_A_infra_ai/08_dgx_spark_migration.md) (추론 서버를 DGX Spark로 이관) | `feature/dgx-spark-migration` |
| A | [person_A_infra_ai/07_server_ops_checklist.md](person_A_infra_ai/07_server_ops_checklist.md) (데모 당일 대비 항목) | 없음 |
| B | [person_B_frontend_backend/05_frontend_routes_components.md](person_B_frontend_backend/05_frontend_routes_components.md) (전체 라우트 완주 확인) | `feature/frontend-shell` |

**검증 기준**: 배포된 URL만으로 전체 흐름이 완주된다. ~~로컬 서버 장애 시에도 Gemini 폴백으로 서비스가 유지된다~~ — **2026-09-09 Gemini를 제거하면서 이 기준은 폐기했다.** 폴백이 더 이상 없으므로 로컬 서버가 죽으면 AI 기능은 503으로 멈추고 화면에 "AI 서버가 수리 중이예요."가 뜬다. 그 대신 **데모 당일 로컬 추론 서버와 터널의 상태 점검이 필수 항목**이 된다([person_A_infra_ai/07_server_ops_checklist.md](person_A_infra_ai/07_server_ops_checklist.md)). 2026-09-10에 그 추론 서버를 RTX 4090에서 DGX Spark로 교체하기로 했고, 4090을 그대로 내리기 때문에 **하드웨어 롤백 경로가 없다** — 롤백은 같은 Spark에서 더 작은 모델로 내려앉는 것뿐이다([person_A_infra_ai/08_dgx_spark_migration.md](person_A_infra_ai/08_dgx_spark_migration.md)). ~~9/16 이후 신규 기능 동결~~ — **실제로는 지켜지지 않았다**, 마일스톤 6 참고. 이후 발견되는 버그는 `fix/*` 브랜치로 `dev`를 거쳐 `main`에 반영한다.

## 마일스톤 6 — 구직정보 연계 · 메인 피드 · 프로필 매칭 · 챔피언십 쇼케이스 (체크리스트 밖, 3주차 이후)

> **2026-09-17 신설.** 마일스톤 1~5는 원 스펙(명세서 16절) 기준이라 이 범위 밖의 작업이 전혀
> 반영돼 있지 않았다. 실제로는 마일스톤 4~5 사이 기간에 이보다 훨씬 큰 2차 기능 물결이 진행됐고,
> `docs/devlog/PersonB/06`~`57`, `docs/devlog/Step2/`에만 기록되어 있었다. 이 절은 그 사실을
> 문서화하고, 세부 체크리스트 파일을 새로 만드는 대신 devlog를 근거 소스로 삼아 마일스톤
> 표기 체계에 편입한다 — 이 규모(devlog 50개 이상)를 항목별 체크박스로 재작성하는 것은 실익보다
> 비용이 크다고 판단했다.

| 하위 기능 | 관련 spec | 관련 devlog | 상태 |
|---|---|---|---|
| 게스트 세션 · 통합 채팅 UI (5-phase 리팩터) | 없음 | PersonB 06~10 | 완료 |
| 구직정보 연계(고용24 API, 인터뷰 답변 → 검색 쿼리) | [job_search_and_gap_link.md](../specs/job_search_and_gap_link.md) | PersonB 11~20, 39, 41, 43~53 | 완료 — `210L01`(기업회원 전용) 한 엔드포인트만 제외, [63_worknet_status_correction.md](../devlog/PersonB/63_worknet_status_correction.md) 참고 |
| 메인 페이지 피드(정책·훈련·채용 추천) | [main_page_feed.md](../specs/main_page_feed.md) | PersonB 25~27, 30, 32~34 | 완료, 일부 UI 다듬기(페이지네이션 UI, 카테고리 칩) 미착수 |
| 프로필 속성 추출 · 계층형 매칭 | [profiling_and_matching.md](../specs/profiling_and_matching.md) | PersonB 29, 31, 38, 40, 54~57 | 완료 |
| 챔피언십 쇼케이스 5종(정직성 스코어보드/데모 모드/GPU 배지/공유 카드/문답 예시) | 없음 | PersonB 58~62 | 완료 (2026-09-16~17) |

**검증 기준**: 위 devlog들의 "검증" 절에 기록된 pytest/브라우저 확인이 각각 통과했음 — 개별
devlog 참고. 이 마일스톤 전체를 관통하는 단일 흐름 검증은 없음(원 스펙 밖 작업이라 처음부터
그렇게 계획되지 않았음).
