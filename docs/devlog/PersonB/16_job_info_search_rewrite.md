# "일자리 찾기" → "취업 정보 종합 검색" 전면 재작성

관련 spec: 없음(11~15와 동일하게 체크리스트 밖 항목)
날짜: 2026-09-08

---

## 배경

[15번 devlog](15_worknet_api_investigation_and_error_surfacing.md)에서 확인된 대로, 이전 "일자리 찾기"의 핵심이었던 워크넷 채용정보(구인정보 검색, `210L01`) API는 개인회원 계정을 완전히 차단한다. 반면 같은 방식으로 나머지 9개 워크넷/고용24 API를 실 인증키로 라이브 테스트해보니 전부 개인회원으로 정상 작동했다(채용정보의 형제 API 3개 — 채용행사/공채속보/공채기업정보 — 는 이미 승인된 키로 즉시, 훈련과정 4종·구직자취업역량강화프로그램·강소기업은 각각 새로 신청·승인받은 키로). 사용자가 "일자리 찾기가 아니라 '취업 정보 종합 검색'으로 노선을 틀자"고 결정했고, "질문 하나로 여러 카테고리 동시 검색"(AskUserQuestion으로 확정)을 원칙으로 설계 → 구현했다.

이번 작업은 급여/지역/학력/경력을 한 번에 하나씩 묻던 턴 기반 인터뷰(devlog 13/14)를 포함해 이전 "일자리 찾기"의 거의 전부를 걷어내고, 자유 텍스트 질문 → LLM이 관련 카테고리(들) 판단 + 카테고리별 검색어 추출 → 각 카테고리 API 병렬 호출 → 카테고리별로 묶어 한 화면에 보여주는 무상태 대화형 구조로 교체했다.

## 완료 항목

- **카테고리 6개 설계**(9개 엔드포인트를 사용자 개념 단위로 묶음): 채용행사/공채속보/공채기업정보(각각 별도), 직업훈련과정(국민내일배움카드·사업주훈련·컨소시엄·일학습병행 4개 엔드포인트를 하나로 병합), 구직자취업역량강화프로그램, 강소기업.
- **LLM 능력 교체** (`app/services/llm/base.py`): `JobPreferences`/`JobPosting`/`JobFitResult`/`JobPreferenceInferenceResult`와 Protocol의 `extract_job_preferences`/`judge_job_fit`/`infer_job_preferences_from_facts`를 전부 제거하고 `classify_job_info_query(query) -> list[JobInfoCategoryQuery]` 하나로 교체(카테고리+검색 키워드를 한 번의 JSON 응답으로, `extract_categories`와 같은 원리). `local_ollama.py`/`gemini_provider.py`/`fallback.py` 3곳 동일 반영, 새 프롬프트 `classify_job_info_query.jinja`(기존 3개 프롬프트는 삭제).
- **새 워크넷 클라이언트** `app/services/job_pipeline/job_info_client.py`(기존 `worknet_client.py` 대체): 카테고리별 파서 6개(XML 루트/태그명이 전부 다름 — `empEvList`/`empEvent`, `dhsOpenEmpInfoList`/`dhsOpenEmpInfo`, `dhsOpenEmpHireInfoList`/`dhsOpenEmpHireInfo`, `HRDNet`/`scn_list`, `empPgmSchdInviteList`/`empPgmSchdInvite`, `smallGiantsList`/`smallGiant`), 공용 결과 타입 `JobInfoResult(title, subtitle, meta_lines, detail_url)`으로 정규화. `WorknetApiError` 감지 로직(`<message>`/`<error>` 두 형태)은 그대로 재사용하되, 관찰된 오류 응답이 두 가지 다른 루트/태그 조합이라는 게 이번에 한 번 더 확인됨(devlog 15는 `<wantedRoot><message>` 하나만, 이번엔 다른 카테고리에서 `<GO24><error>`도 나옴 — 둘 다 처리).
- **서버사이드 필터 대신 키워드 부분일치**: 대부분의 형제 API가 자유 키워드 검색 파라미터를 지원 안 해서(devlog 15에서 학력/경력 코드 파라미터를 잘못 짐작했다가 겪은 교훈과 같은 이유로 이번엔 아예 코드값을 추측하지 않음), 기본 조건(훈련과정만 필수인 날짜 범위, 오늘~90일 고정)으로 목록을 받아온 뒤 LLM이 뽑은 키워드로 응답 텍스트를 서버에서 부분일치 필터링(`_filter_by_keywords`). 항목별 적합도를 LLM에게 판단시키던 기존 `judge_job_fit` 패턴은 이번엔 안 씀 — 카테고리가 6개로 늘면서 항목별 LLM 호출까지 걸면 호출 수가 폭발(로컬 Ollama 호출당 수 초~수십 초라는 이 프로젝트에서 반복 확인된 제약).
- **DB**: `job_search_preferences` 테이블 drop(마이그레이션 `735683a2d64a`) — 더 이상 확정된 조건을 저장할 필요가 없는 무상태 대화라. `sessions.status` CHECK 제약은 안 건드림 — `JOB_PREFERENCES_INPUT`/`JOB_RESULTS_REVIEW` 값을 그냥 안 쓰기로 하고, `job_search` 세션은 생성 시점부터 계속 `JOB_SEARCHING` 하나로 고정(더 이상 단계 전이가 없는 상시 대화형 세션이라).
- **엔드포인트 1개로 통합**: 기존 7개(`GET /job-search`, `preferences/extract`, `preferences`, `preferences/ask`, `preferences/turn-confirm`, `search`, `seed-from-gap`) 전부 제거하고 `POST /job-search/query` 하나로. 카테고리 하나가 실패해도(`WorknetApiError`) 그 카테고리만 결과에서 빠지고 나머지는 그대로 보여준다(`asyncio.gather` + 개별 try/except).
- **프론트 전면 교체**: `JobSearchInterviewSection.tsx`/`JobSearchPreferencesSection.tsx`/`JobStyleTagEditor.tsx`/`JobSearchResultsSection.tsx` 삭제, `JobSearchChatPage.tsx`를 단일 대화형 화면으로 재작성 — 항상 켜져 있는 공유 컴포저, 질문 하나당 새 턴(사용자 질문 말풍선 + 카테고리별 결과 그룹 또는 재질문 안내), 서버에 아무것도 저장 안 하므로 새로고침하면 이력이 사라짐(다른 인터뷰 컴포넌트들과 같은 트레이드오프, 의도적).
- 백엔드 신규 테스트 16개(`test_job_info_client.py` 11개 — 카테고리별 파서, 오류 응답 두 형태 감지, 키워드 필터, 훈련과정 4종 병렬 집계+부분 실패, `test_job_search.py` 5개 — 세션 종류 체크, 재질문, 복수 카테고리 동시 반환, 카테고리 하나 실패해도 나머지는 살아있음, 빈 결과도 정상 표시) — 전체 178개 통과. e2e 전면 재작성(복수 카테고리 동시 응답 + 재질문 + 대화 이력 누적 확인), 전체 e2e 7개 통과(2회 연속 재현 확인). eslint/build 클린. 실 인증키로 `job_info_client.py`의 4개 카테고리를 직접 호출해 실제 데이터가 정상적으로 파싱되는 것까지 확인(강소기업 8건, 구직자프로그램 8건, 훈련과정 4종 통합 4건, 공채속보 8건).

## 핵심 결정 사항과 이유

**"질문 하나 = 카테고리 하나"가 아니라 "질문 하나 = 카테고리 여러 개 동시 검색"으로.** AskUserQuestion으로 사용자에게 직접 확인 — API 호출이 늘고(카테고리 수만큼) 화면에 여러 섹션을 한 번에 렌더링해야 해서 복잡도는 커지지만, "이직 준비하는데 도움될 거 있어?" 같은 자연스러운 질문이 실제로 여러 카테고리에 걸치는 게 흔해서 "더 풍부한 정보"라는 이번 요청의 취지에 맞는 쪽을 택함.

**훈련과정 4종을 사용자에게는 "직업훈련과정" 하나로 숨긴다.** 국민내일배움카드/사업주훈련/컨소시엄/일학습병행은 실무자가 아닌 이상 구분하기 어려운 정부 행정 분류라, 사용자에게 "어느 훈련과정인지" 고르게 하는 대신 백엔드가 4개 엔드포인트(각각 별도 인증키)를 항상 같이 호출해서 하나로 합친다 — 하나가 실패해도(승인 상태가 서로 다를 수 있음) 나머지로 계속 진행.

**항목별 LLM 적합도 판단(`judge_job_fit` 패턴)을 이번엔 뺐다.** 카테고리가 1개(이전)에서 6개(지금)로 늘면서, 카테고리마다 항목별로 LLM을 또 부르면 한 번의 질문에 호출 수가 감당하기 어렵게 늘어난다. 대신 LLM은 "이 질문이 어느 카테고리에 해당하고 어떤 키워드로 좁혀야 하는지" 한 번만 판단하고, 실제 항목 선별은 서버 쪽 텍스트 부분일치로 처리 — 정확도는 다소 떨어질 수 있지만 응답 속도와 호출 비용 면에서 실용적인 선택.

**서버에 대화 이력이나 카테고리별 검색 조건을 전혀 저장하지 않는다.** 이전 버전은 "확정된 조건"을 모아뒀다가 검색하는 구조라 저장이 꼭 필요했지만, 지금은 매 질문이 그 자리에서 바로 검색으로 끝나는 무상태 대화라 저장할 이유가 없다 — `job_search_preferences` 테이블 자체를 drop.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `alembic upgrade head`가 `sqlalchemy.exc.ArgumentError: Could not parse SQLAlchemy URL from given URL string`로 실패 | `app/db/migrations/env.py`가 `os.environ.get("DATABASE_URL")`로 프로세스 환경변수를 직접 읽는데(pydantic Settings의 `.env` 자동 로딩과 별개 경로), 이번 Bash 호출에선 `.env`가 실제 프로세스 환경변수로 export돼 있지 않았음(pydantic Settings 쪽만 잘 읽혔음, 별도로 확인함) | `set -a && source .env && set +a` 후 `alembic upgrade head` 실행 — 이후 uvicorn 로컬 실행도 같은 방식으로 함 |

## 남은 작업

- 지역 코드 매핑은 여전히 없다(이번에도 정확한 코드표를 못 구해서 free text 부분일치 필터로 대체) — 확보되면 채용행사/공채속보 등에 실제 지역 파라미터로 반영 가능.
- 훈련과정 조회 날짜 범위(오늘~90일 고정)는 사용자 질문에서 실제 날짜 표현("다음 달", "이번 주")을 뽑아내는 것까지는 이번 범위 밖 — 필요해지면 `classify_job_info_query` 응답에 날짜 필드를 추가하는 정도로 확장 가능한 구조로 만들어둠.
- "이 결과로 일자리 찾기 시작" 버튼(공백기 채우기 결과 화면)은 그대로 뒀지만 더 이상 아무것도 시드하지 않는다(이전엔 `seed-from-gap`으로 키워드/업무스타일 힌트를 채워줬음) — 필요하면 연동을 다시 붙이되, 이번 카테고리 구조에 맞게 다시 설계해야 함.
