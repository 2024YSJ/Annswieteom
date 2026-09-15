# 46. 채용행사/직업훈련과정 키워드 동의어 확장 (2026-09-15)

devlog 45 직후 실계정으로 22개 직업을 테스트하다가, 사용자가 "AI가 뽑은 직업
키워드가 실제 API 검색어와 안 맞아서 0건이 되는 것 아니냐 — 인자가 유한하면
가장 가까운 값을 고르게 해서 정확도를 높이자"는 가설을 제시했다. 지역 코드
(`regions.py`)처럼 유한한 값 체계가 존재한다면 같은 방식으로 풀 수 있어
보였다.

## 조사

devlog 39(2026-09-13)에서 이미 6개 카테고리 전부에 대해 직무/직종 관련
파라미터 후보를 8~9개씩 실제로 호출해 확인한 기록이 있었다 — 재조사 대신 이걸
근거로 삼았다:

- **직종 분류 코드는 고용24 어디에도 없다.** 지역과 달리 유한한 코드 체계
  자체가 존재하지 않는다.
- **`job_fair`(채용행사)**: `keyword`가 `eventNm`(행사명) **리터럴 부분
  일치**로 작동.
- **`training_course`(직업훈련과정)**: `srchTraProcessNm`이 과정명 **리터럴
  부분 일치**로 작동.
- **`promising_sme`/`public_recruitment`/`public_recruitment_company`/
  `job_seeker_program`은 직무 관련 파라미터 자체가 없다** — 9개 후보 전부
  시도했지만 반영되는 게 하나도 없었다. 이 4개 카테고리의 0건은 이번 작업으로
  고칠 수 없다.

즉 "가장 가까운 유한 인자를 고르게 한다"는 지역식 코드 매핑은 직업에 적용할 수
없다(그런 코드가 없으므로). 대신 사용자가 선택한 대안 — 리터럴 부분일치
검색에 여러 표현을 시도해보는 **동의어 매핑표**를 직접 구축했다.

## 수정

`backend/app/services/job_pipeline/occupation_synonyms.py`(신규): 직업명 →
실제 제목에 나올 법한 표현 몇 개를 매핑한 로컬 테이블 +
`expand_occupation_keyword(keyword, limit)`. `regions.py`와 철학은 같지만(LLM은
있는 그대로만 뽑고, 결정론적 로컬 테이블이 변환 담당) **API가 검증해준 공식
코드가 아니라 휴리스틱 추정 테이블**이라는 점을 모듈 docstring에 명확히
구분해 적었다 — 실제 제목 텍스트를 관찰하며 계속 보정해야 하는 값이다. 22개
직업 배터리를 시드로 21개 항목을 채웠다(공채속보로만 분류되는 "초등학교 교사"는
의도적으로 제외 — 이 표가 닿지 않는 카테고리라서).

`job_info_client.py`:
- `search_job_fairs`: 키워드 추출 결과를 `expand_occupation_keyword`로
  최대 3개 표현까지 펼쳐 `asyncio.gather`로 동시 호출, `source_key`(없으면
  `title, subtitle`)로 중복 제거해 병합.
- `_training_combos`: 캡을 통과한 각 키워드에 동일하게 최대 2개 표현을 얹어
  펼침. 이후 기존 `_MAX_TRAINING_COMBOS=3` 절단과 `_run()`의 중복 제거가
  그대로 적용되므로 새 병합 코드가 필요 없었다.
- `job_search.py`는 **변경 없음** — `_widen_attempt`의 `job_fair` 분기는
  `query_params.keywords`를 통째로 비우는 방식이라 이 팬아웃과 완전히
  독립적이다.

## 핵심 결정과 이유

- **조회는 정확 일치만.** 부분 문자열 포함까지 허용하면 "간호"가 "간호사"
  그룹에 잘못 걸리는 등 의도치 않은 오탐 위험이 있다. 매핑 안 된 키워드는
  오늘과 동일하게 그대로 1회 호출(회귀 없음, `expand_occupation_keyword`가
  못 찾으면 `[keyword]`만 반환하므로 자동 보장).
- **`_training_combos`의 지역×키워드 절단은 최소 변경으로 남겨둠.** 지역
  여러 개 + 키워드 동의어 확장이 겹치는 드문 경우 기존 지역 우선순위 조합
  방식이 일부 지역을 캡 밖으로 밀어낼 수 있지만, 지금 단계에서는 손대지
  않기로 했다(라운드로빈 교차 배치는 필요성이 확인되면 별도 작업).
- **`extract_job_info_query_params.jinja`는 이번엔 손대지 않음.** 테이블은
  LLM이 뽑은 키워드가 표제어/동의어와 정확히 일치할 때만 작동한다. 먼저 이
  상태로 실측해 히트율을 보고, 낮으면 그다음에 프롬프트를 테이블 표제어 쪽으로
  유도하는 걸 검토하기로 했다.
- 이건 devlog 40의 임베딩 기반 의미 매칭기(추천 피드용)와는 별개다 — 그건
  피드 추천에, 이건 `job_fair`/`training_course` 두 카테고리의 질의 시점
  리터럴 검색에 쓰인다.

## 트러블슈팅

기존 조합 테스트들(`test_each_same_dimension_value_becomes_its_own_combo`
등 7개)이 "자바"/"디자인"/"간호" 같은 리터럴 키워드가 확장 없이 그대로
조합에 들어간다고 단언하고 있었다 — 최종 시드 테이블에는 이 값들이 없어 실제
충돌은 없었지만, 테이블이 자라면서 다시 깨질 수 있는 구조였다. 메커니즘과
데이터를 분리하는 게 맞다고 보고, `expand_occupation_keyword`를 항등 함수로
monkeypatch하도록 전부 고쳤다.

## 검증

`cd backend && pytest` 전체 529개 통과(기존 521 + 신규 8: job_fair 확장/미매핑
회귀 가드 2개, `_training_combos` 확장/무키워드 2개, `occupation_synonyms.py`
단위 테스트 4개).

## 남은 작업

- [ ] 배포 후 22개 직업 배터리 재실행 — `job_fair`/`training_course`에서 실제
      재현율이 얼마나 개선됐는지 측정. `promising_sme`/`public_recruitment`류
      0건은 이번 작업 범위 밖이라 그대로일 것으로 예상.
- [ ] 실측 제목 텍스트를 관찰하며 `occupation_synonyms.py` 테이블 보강.
- [ ] 히트율이 낮으면 `extract_job_info_query_params.jinja`를 테이블 표제어
      쪽으로 유도하는 것 검토.

## 관련 커밋

- (머지 전 — `feature/occupation-keyword-synonyms` 브랜치)
