# 53. DB 추가 없이 취업 정보 검색 후보 풀 넓히기 (2026-09-15)

"0건이 자주 나오는데 DB로 캐싱하면 나아지나?"라는 질문에서 시작했다. 조사
결과 기존 `feed_items` 캐시(devlog 25/40)는 카테고리당 최신 50건·6시간
주기로 홈 화면 "둘러보기"용이라 재사용할 수 없고, 이 프로젝트엔 별도
워커/크론도 없어(`render.yaml`/`Procfile` 없음) "전체 데이터셋을 항상 최신
유지"하려면 지금 없는 스케줄러 인프라를 새로 만들어야 한다는 걸 확인했다.
사용자가 새 DB 테이블 대신 **"DB 추가 말고 검색 개수 또는 품질을 늘릴 수
있는 방안을 조사하라"**고 명시적으로 요청해, 기존 라이브 조회 파이프라인
안에서 끝내는 쪽으로 방향을 잡았다(`docs/checklists/person_A_infra_ai/
08_dgx_spark_migration.md`의 "기능 동결(9/16)"도 큰 인프라 변경을 미루는
근거가 됐다).

## Phase 1 — 실측: display/페이지네이션 상한

devlog 49와 같은 방식(임시 진단 스크립트, 인증키는 출력 안 함, 실행 후 삭제)
으로 `public_recruitment`/`public_recruitment_company`/`promising_sme`/
`job_seeker_program`에 `display=100/200/300/500`을 직접 호출했다.

**핵심 발견 — devlog 49의 "100까지는 검증, 그 이상은 미실측"이 이번에
갈렸다: display는 100에서 정확히 캡된다.** 200/300/500을 줘도 서버는 항상
같은 100건을 그대로 돌려줬다(`new_vs_prev_display=0` — 이전 단계와 완전히
동일한 집합). 반면 `startPage=2`는 `startPage=1`과 겹치는 항목이 0개였다 —
진짜 페이지네이션은 있고, 캡은 "한 번에 받는 양"에만 걸린다.

즉 100건 넘게 받으려면 "그냥 상수를 올리는" 방법은 안 통하고, **여러
페이지를 병렬로 조회해 병합**해야 한다.

부수적으로, 이 라운드에서 각 카테고리의 실제 응답 필드를 전부 덤프해
확인했다: `public_recruitment`/`public_recruitment_company`는 애초에
**응답 자체에 지역 정보 필드가 없다**(주소·지역명 태그 없음). devlog 46이
"서버 파라미터로 지역을 못 건다"고 확인했던 것보다 더 근본적인 한계다 —
클라이언트 쪽에서 텍스트로 지역을 매칭하는 것도 원천적으로 불가능하다.
`promising_sme`(regionNm/coAddr)와 `job_seeker_program`(orgNm/openPlcCont)은
지역 관련 텍스트가 있어 1차 필터가 통할 여지가 있다.

## Phase 2 — 넓은 원본 풀 + 값싼 1차 필터

**`backend/app/services/job_pipeline/job_info_client.py`**
- `_PAGE_SIZE = 100`(실측 캡), `_RAW_POOL_LIMIT = 300`(기존
  `_UNFILTERED_FETCH_LIMIT=30`을 대체) 추가.
- `_fetch_paged()` 헬퍼 추가 — `limit`이 100을 넘으면 `startPage`를
  `ceil(limit/100)`장 병렬로 던져 `source_key`(없으면 `title`+`subtitle`)로
  중복 제거해 병합한다. 페이지 하나가 실패해도(WorknetApiError) 다른
  페이지가 성공했으면 그것만 빼고 합치고, 전부 실패했을 때만 예외를 올린다
  — `search_job_fairs()`의 표현별 병렬 조회(devlog 46)와 같은 any_ok 패턴.
- `search_public_recruitment`/`search_public_recruitment_companies`/
  `search_job_seeker_programs`/`search_promising_smes`를 이 헬퍼를 쓰도록
  리팩터링(파싱 로직은 함수로 분리, 순수 함수라 리팩터링 자체는 로직 변경
  없음). 기본 `limit`을 `_RAW_POOL_LIMIT`(300)로 올렸다 — HTTP는 병렬이라
  비용은 여전히 ~0.3~0.4초대(devlog 49/52 실측 범위와 같은 규모).
  `worknet_source.py`(피드 수집)는 여전히 `limit=50`으로 명시 호출하므로
  1페이지만 도는 기존 동작 그대로다(회귀 테스트로 확인).

**`backend/app/services/job_pipeline/regions.py`**
- `region_match_terms(region_names)` 추가 — `resolve_region_filters()`가
  API 파라미터(코드)를 만드는 것과 달리, 이건 `JobInfoResult`의
  title/subtitle/meta_lines 같은 자유 텍스트에 부분일치시킬 substring
  목록을 돌려준다("경기 북부" → 시·군 이름 10개, "수도권" → 서울/경기/인천,
  그 외는 시/군/구 접미사를 뗀 이름).

**`backend/app/services/job_pipeline/prefilter.py`(신규)**
- `prefilter_candidates(raw, query_params, limit)` — 넓힌 원본 풀에서
  키워드(occupation_synonyms 동의어 확장 포함, limit 5)나 지역
  (region_match_terms) 중 **하나라도** 텍스트에 일치하면 통과시킨다(OR).
  "지역·직무를 다 만족해야 한다"는 최종 판단은 여전히 LLM이 한다
  (devlog 45) — 1차 필터는 재현율을 지키는 예비 단계일 뿐이다.
- 조건(키워드·지역)이 아예 없으면 devlog 49의 "비교 기준 없음 → 전부 관련"
  원칙과 같은 이유로 필터 없이 앞에서부터 `limit`개를 그대로 돌려준다.
- **폴백 기준은 "적으면"이 아니라 "0건이면"이다.** 처음엔 "통과 5건 미만이면
  폴백"으로 설계했으나, 테스트를 작성하며 반례를 발견했다 — 실제로 3~4건만
  맞아떨어지는 건 정상적인 좁은 결과이고, 그걸 30건짜리 미필터 목록으로
  덮어버리면 오히려 손해다. `public_recruitment`/`public_recruitment_company`
  처럼 애초에 지역 정보가 응답에 없는 카테고리에서 지역 조건을 걸면 매칭이
  0건이 되는데, 그 경우에만 "필터 자체가 이 데이터엔 안 맞는다"고 보고
  원본 풀 앞부분으로 되돌아간다.

**`backend/app/api/job_search.py`**
- `_PREFILTERED_CANDIDATE_LIMIT = 30`(예전 `_UNFILTERED_FETCH_LIMIT`과 같은
  크기 — LLM 프롬프트 크기·지연시간을 지금과 비슷하게 유지하기 위해),
  `_JOB_FILTER_MISSING_CATEGORIES`(4개 카테고리) 추가.
- 관련성 판정(`_judge_relevant`) 호출 **직전**, 이 4개 카테고리에 한해
  `prefilter_candidates(raw_results, query_params, _PREFILTERED_CANDIDATE_LIMIT)`
  를 적용해 넓은 원본 풀(최대 300건)에서 추린 후보만 LLM에 넘긴다.
- **widen(관련성 부족 시 재시도) 로직은 의도적으로 건드리지 않았다.** 기존
  `_widen_attempt`가 이미 "조건을 풀고 `_WIDENED_UNFILTERED_LIMIT=100`건을
  프리필터 없이 그대로 LLM에 넘겨 재판정"하는 안전망 역할을 하고 있어서,
  1차 필터가 너무 빡빡했을 때의 폴백을 이미 만족한다 — 별도로 재구성하면
  `test_widen_retries_promising_sme_without_region_when_results_are_scarce`
  등 기존 회귀 테스트와 충돌할 위험만 커지고 얻는 게 없었다.

## 트러블슈팅

- **집필 중 폴백 임계값 설계 오류를 테스트로 잡았다**: `prefilter.py`
  테스트(`test_keyword_or_region_match_is_enough_not_both`)를 작성하다가,
  "통과 5건 미만이면 폴백"이라는 처음 설계가 이 테스트의 정상적인 4건 매칭
  결과까지 지워버리는 것을 발견했다 — 폴백 조건을 "0건일 때만"으로 고쳤다
  (위 Phase 2 설명 참고).
- **작업 중 다른 세션의 미커밋 변경과 같은 작업 디렉터리를 공유하고
  있었다**: `dev`에서 새 브랜치를 체크아웃했더니, 동시에 진행 중이던 다른
  세션의 "게스트 세션 제한 제거" 작업(미커밋 상태)이 내 브랜치 위로 같이
  올라왔다 — 두 작업의 파일이 겹치지 않아 데이터 손실은 없었지만, 커밋
  시점에 브랜치가 꼬일 뻔했다. `dev`로 되돌리고, 이 작업만 `git worktree`로
  분리된 별도 디렉터리에 패치로 옮겨 커밋했다 — 같은 저장소를 여러 세션이
  동시에 쓸 때는 브랜치를 바꾸기 전에 `git status`로 남의 미커밋 변경이
  없는지 먼저 확인해야 한다는 교훈.

## 테스트

- `backend/tests/services/test_prefilter.py`(신규, 7개): 조건 없음 통과,
  키워드/지역 각각 매칭, OR 매칭, 0건일 때만 폴백, limit 적용.
- `backend/tests/services/test_regions.py`: `region_match_terms` 4개 추가
  (권역 확장, 수도권 확장, 접미사 제거, 빈 값 skip).
- `backend/tests/services/test_job_info_client.py`: 페이지네이션 5개 추가
  (100 초과 시 여러 페이지 호출, 100 이하는 호출 1회 유지, 페이지 간 중복
  제거, 페이지 하나 실패해도 나머지로 병합, 전부 실패 시에만 예외).
- `backend/tests/api/test_job_search.py`: 1차 필터가 실제로 라우트에
  연결됐는지 확인하는 통합 테스트 1개 추가(LLM에 넘어간 candidates가
  프리필터된 부분집합인지 검증).
- `cd backend && pytest` 전체 회귀: 540 → 557 (신규 17개), 전부 통과.

## 검증 (배포 후 진행 — 아직 미실행)

- [ ] 배포 후 이번 라운드에서 0건이었던 질의 일부(관세사, 감정평가사, 사서,
      관광가이드 등) 재확인 — 실제로 더 찾아내는지, 아니면 work24에 데이터
      자체가 없는 직업인지.
- [ ] 응답 지연시간 체감 확인(카테고리당 HTTP 호출이 최대 3배로 늘었지만
      병렬이라 이론상 영향은 작다).

## 관련 커밋

- (머지 전 — `fix/job-search-widen-candidate-pool` 브랜치, 별도 worktree에서
  작업)

## 남은 작업

- [ ] 배포 후 실계정 재확인(위 검증 항목).
- [ ] `public_recruitment`/`public_recruitment_company`의 "지역 정보 자체가
      없다"는 구조적 한계는 이번 변경으로도 해결되지 않는다 — 완전한 해결은
      work24가 필드를 추가하거나 DB로 다른 소스와 조인하는 것뿐이라 현재는
      추적만 한다.
