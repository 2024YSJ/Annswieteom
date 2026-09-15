# 49. 조건없는질문·unsupported_note 직무모순·4카테고리 후보풀 확대 (2026-09-15)

devlog 44~48과 22개 직업 실계정 테스트를 거치며 정리한 잔여 과제 중 3가지를
이번에 고쳤다(eval_job_search.py 실제 실행은 프로덕션 터널 접근 준비 후
별도로 이어간다).

## 1. "조건 없는 질문"이 전부 걸러지던 문제

"강소기업 추천해줘", "요즘 채용행사 뭐 있어?"처럼 비교할 지역/직무 조건이
아예 없는 질문은, 실제로는 데이터가 있어도 0건으로 나왔다.
`select_relevant_job_info_results.jinja`의 "관련 있는 항목이 하나도 없으면
빈 배열"이라는 지시를, LLM이 "비교할 기준 자체가 없으면 전부 무관하다"로
확대 해석한 것으로 보인다.

**수정**: 그 지시 바로 뒤에 명시적 예외를 추가했다 — "질문에 비교할 구체적
조건이 아예 없으면 목록 전체를 관련 있다고 보고 전부 골라라." 새 few-shot
예시("강소기업 추천해줘")를 추가했는데, devlog 45에서 이미 겪은 실수(새
예시를 기존 마지막 예시 뒤에 붙였다가 exhaustive-selection 회귀 테스트가
고정한 자리를 깨뜨림)를 반복하지 않도록 **기존 마지막 예시 앞**에 끼워
넣었다(`test_select_relevant_prompt_demands_exhaustive_selection` 그대로
통과 확인).

`job_search.py`는 변경 없음 — 이 프롬프트는 이미 `payload.query` 원문을 받고
있어 새 지시만으로 충분하다.

## 2. `unsupported_note` 직무명 모순 (지역 모순과 같은 패턴)

devlog 44 Phase 3에서 "카테고리를 골랐는데 unsupported_note가 그 지역을
미지원이라 언급하는" 모순을 고쳤는데, 같은 구멍이 **직무명**에도 그대로
있었다. 실측: "인천 초등학교 교사 채용 소식 있어?"가
`categories=["public_recruitment"]`를 정확히 고르고도 `unsupported_note`에
"초등학교 교사 채용정보"라고 방금 검색에 쓸 그 직무명을 미지원 사유로
지어냈다.

**수정**: `classify_job_info_query.jinja`에 지역-모순 방지 지시와 나란히
직무-모순 방지 지시("카테고리를 골랐다면 그 직무 자체를 unsupported_note
사유로 쓰지 마라")와 "초등학교 교사" 반례를 추가했다. `job_search.py`의
기존 방어선(지역 검사)과 나란히 `query_params.keywords` 검사를 추가해,
`unsupported_note`가 방금 추출한 keyword를 그대로 포함하면 버린다.

## 3. 서버 필터 없는 4개 카테고리 — 후보 풀 확대

`public_recruitment`/`public_recruitment_company`/`job_seeker_program`(서버
필터 자체가 없음)과 `promising_sme`(지역 필터만 있음)는 결과가 모자라도 좁은
후보 풀(20~30건)에 갇혀 있었다. 두 가지 실측을 했다:

**실측 1 — `display`/`startPage` 실제 동작 확인**: `probe_job_info_fields.py`
방식으로 4개 엔드포인트에 `display=30`/`100`, `startPage=1`/`2`를 직접
호출했다. 결과: `display`는 요청한 만큼(100건까지 확인) 실제로 다른 항목을
돌려주고(30건에서 100건으로 늘려도 중복 없이 늘어남), `startPage=2`는
`startPage=1`과 **완전히 겹치지 않는** 다른 항목을 준다 — 진짜 페이지네이션이
존재한다(public_recruitment total=250, public_recruitment_company
total=6227, promising_sme total=15291 — 다들 한 번에 다 못 가져올 만큼
많다).

**실측 2 — 즉시 고칠 수 있는 누락**: `_widen_attempt`의 `promising_sme`
분기가 지역만 떼고 재조회하면서 `limit`은 그대로 기본값(20)이었다 — "전국
전체"로 넓힌 조회인데 "지역 한정" 조회와 똑같이 좁은 채였다.

**수정**: 여러 페이지를 병합하는 것보다 간단하고 결과가 사실상 같은 "한
번에 더 크게 요청"을 택했다 — `_WIDENED_UNFILTERED_LIMIT`을 60→100으로
올리고(실측으로 100까지는 안전하게 확인됨), `promising_sme`의 widen도 이
상수를 같이 쓰도록 고쳤다. 진짜 다중 페이지 병합은 100으로도 부족하다는
게 확인되면 그때 추가하기로 미뤄뒀다(총량이 워낙 커서 애초에 "최신 스냅샷"
성격의 기능이라는 한계는 여전히 남는다).

## 검증

`cd backend && pytest` 전체 회귀 통과(신규: unsupported_note 직무모순 가드
테스트 2개, promising_sme widen limit 확인 1개 보강).

`eval_job_search.py`에 새 골든 케이스 2개(`job_title_contradiction_elementary_teacher`,
`no_criteria_recommend_anything`)와 직무-모순 자동 채점을 추가했고,
`select_relevant_job_info_results`를 합성 후보로 직접 채점하는 새 경로
(`RelevanceCase`/`RELEVANCE_CASES`)도 추가했다 — "조건 없는 질문 → 전부
관련", "조건이 있으면 여전히 정상 필터링"(회귀 가드) 케이스 포함. **실제
프로덕션 터널로는 아직 안 돌려봤다** — 로컬 .env가 여전히 개발용 약한
모델을 가리키고 있어(`LOCAL_LLM_BASE_URL=http://localhost:11434`,
`qwen2.5:3b-instruct`), 프로덕션 터널 접근 값(`LLM_ACCESS_CLIENT_ID`/
`SECRET`, `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL_NAME=qwen3.5:35b-a3b`)을
넣은 뒤 실행이 필요하다.

## 남은 작업

- [ ] `.env`를 프로덕션 값으로 일시 변경 → `python scripts/eval_job_search.py
      --out job_search_eval.md` 실행 → 결과 확인 → `.env` 원복.
- [ ] 배포 후 실계정 브라우저 재현: "강소기업 추천해줘"(조건없음), "인천
      초등학교 교사"(unsupported_note 모순), 4개 카테고리 관련 직업 1~2개.
- [ ] `_WIDENED_UNFILTERED_LIMIT=100`이 실제로 재현율을 얼마나 올리는지,
      더 큰 값(예: 200)도 안전한지, 그리고 그래도 부족하면 진짜 다중 페이지
      병합을 추가할지는 실측 결과를 보고 판단.

## 관련 커밋

- (머지 전 — `fix/unsupported-note-keyword-contradiction` 브랜치, 이번
  3가지 수정을 모두 포함)
