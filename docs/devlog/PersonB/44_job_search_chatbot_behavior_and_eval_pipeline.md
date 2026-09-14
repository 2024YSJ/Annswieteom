# 44. 취업 정보 검색을 실제 챗봇답게 — 대화 맥락·적응형 재검색·오분류 수정·평가 파이프라인 (2026-09-15)

실제 계정으로 12개 질의를 다양하게 시도한 결과("사실상 챗봇이 되어야 하는데
그러지 못하고 있다"), 취업 정보 검색이 매 메시지를 독립적으로 처리하는 1회성
파이프라인(분류→조회→필터→반환)이었음을 확인했다. 원인 4가지를 고쳤고, 이번이
이 기능 최초의 실제 평가 파이프라인이다.

## 완료

### Phase 1 — 대화 맥락(멀티턴)
`JobInfoQueryRequest.history: list[str]`(이전 사용자 발화 원문, 최근 5턴)를
추가했다. DB 마이그레이션 없이 프론트가 이미 들고 있는 `turns`를 그대로 실어
보내는 방식을 택했다 — 기존 "무상태 대화, 프론트가 로컬로만 누적" 철학을 그대로
유지하면서 "그럼 서울도 같이 봐줘" 같은 후속 질문을 이해하게 됐다.
`classify_job_info_query`/`extract_job_info_query_params` 양쪽 프롬프트에
`[이전 대화]` 블록과 few-shot을 추가했다.

### Phase 2 — 결과 0건일 때 적응형 재검색
`search_training_courses`에만 있던 완화 패턴(`_MIN_RESULTS_BEFORE_WIDENING`)을
`job_search.py` 레벨로 일반화했다: 관련성 판정 후 결과가
`_MIN_RELEVANT_BEFORE_WIDENING=3` 미만이면 `promising_sme`는 지역 필터를,
`job_fair`는 키워드 필터를 떼고 재조회하고, 서버 필터가 아예 없는 3개
카테고리(`public_recruitment`/`public_recruitment_company`/`job_seeker_program`)는
후보 풀을 2배로 넓혀 재조회한다. `JobInfoCategoryResultRead.broadened`로
실제로 넓혔을 때만 사용자에게 "조건을 넓혀서 찾아봤어요"를 보여준다 — 실제
챗봇이라면 "이렇게 다르게 시도해봤다"를 설명해야 한다는 원칙.

### Phase 3 — 프로필-상충 오분류 버그 수정
"내 프로필 말고 인천에서 디자이너 뽑는 데 있어?"가 카테고리는 맞게 고르면서도
"인천은 지원 안 함"이라는 사실이 아닌 unsupported_note를 만들어내던 문제를
고쳤다. 프롬프트에 명시적 예외(지역/직무는 검색 조건일 뿐 미지원 사유가 될 수
없다, 프로필 힌트는 질문에 단서가 없을 때만 참고)를 추가했고, 프롬프트만으로
100% 못 막을 걸 대비해 `job_search.py`에 사후 방어선을 뒀다 — 카테고리가
선택됐는데 `unsupported_note`가 방금 추출한 지역명을 그대로 언급하면 버린다.

### Phase 4 — 평가 파이프라인 신설
`backend/scripts/eval_job_search.py`(신규) — 이 기능에 실제 Ollama 출력을
자동 채점하는 장치가 하나도 없었다(조사 확인: `compare_llm_models.py`/
`build_spark_bench.py`는 커리어 채우기 흐름만 다룸, `test_job_search.py`는
FakeLLMProvider만 사용). 실제 라이브 테스트 12개 + 다양성을 더한 8개, 총 20개
골든셋을 만들어 카테고리 정밀도/재현율, unsupported_note 존재 여부, "카테고리
선택+지역명 미지원 언급" 모순(Phase 3 버그 패턴)을 자동 채점하고, 마크다운
리포트로 사람이 읽을 원문을 남긴다. `compare_llm_models.py`와 같은 스타일
(수동 CLI, 실제 Spark 터널 필수, CI 아님).

## 핵심 결정과 이유

**대화 맥락을 DB에 저장하지 않았다.** 프론트가 이미 `turns`를 로컬 상태로 들고
있어서, 그걸 그대로 요청에 실어 보내는 쪽이 새 컬럼/마이그레이션/정리 로직 없이
가장 작은 변경으로 같은 효과를 낸다. 새로고침하면 사라지는 트레이드오프도
지금과 동일해 사용자 기대를 안 바꾼다. 사용자 확인 완료.

**적응형 재검색을 job_search.py 레벨에 뒀다(job_info_client.py 내부가 아니라).**
`promising_sme`는 서버가 지역만 필터링하고 키워드 관련성은 클라이언트에서
LLM이 판단한다 — 그래서 "원본 건수는 충분한데 관련성 판정 후엔 모자란" 경우가
생긴다. training_course의 기존 완화 로직은 원본 건수 기준이라 이 케이스를 못
잡는다. 관련성 판정 결과를 아는 유일한 곳이 job_search.py라 거기서 판단해야
했다.

**region-drop 재조회가 예산을 넘을 걱정은 실측 근거로 미리 배제했다.**
`_QUERY_BUDGET_SECONDS=600`초, 카테고리당 관련성 판정 1회 ~37초 기준으로
카테고리 하나가 최대 2번(원본+widen) 돌아도 여유가 크다 — 실제로 모든 카테고리가
동시에 widen돼도 예산 안에 들어온다.

**오분류 방어선을 카테고리 라벨이 아니라 추출된 지역명과 비교했다.** 처음엔
"unsupported_note가 선택된 카테고리 라벨(예: '공채속보')을 언급하면 버린다"로
설계했는데, 실제 버그 사례("인천 지역 채용정보...")는 카테고리 라벨을 전혀
언급하지 않고 지역명만 언급했다 — 그 오분류 패턴 자체를 다시 확인하고 검사
기준을 지역명 비교로 바꿨다.

## 검증

pytest 519개 전체 통과(신규 5개: history 전달, widen 재시도 발동/미발동,
오분류 방어선 발동/미발동 — 회귀 없음 확인을 위해 이미 있던
`test_query_with_no_conditions_falls_back_to_stored_profile`/
`test_query_caps_the_number_of_categories`도 widen 재조회를 감안해 수정).
프론트 `tsc --noEmit` 통과.

**스테이징/실계정에서만 가능(자동화 불가)**:
- `python backend/scripts/eval_job_search.py --out job_search_eval.md`를 실제
  Spark 터널로 돌려 20개 골든셋 채점 결과 확인 — 이번 세션에서는 로컬 dev의
  약한 모델로 돌리는 게 무의미해 실행하지 않았다.
- 실제 계정에서 "경기 프로그래머 강소기업 찾아줘" → "그럼 서울도 같이 봐줘"
  같은 실제 후속 대화로 맥락 이해를 눈으로 확인.
- "경기 프로그래머 강소기업 찾아줘"(widen 발동 기대), "내 프로필 말고 인천에서
  디자이너 뽑는 데 있어?"(오분류 재현 안 됨을 기대) 재확인.

## 관련 커밋

- (머지 전 — `feature/job-search-chatbot-fixes` 브랜치)

## 남은 작업

- [ ] `eval_job_search.py`를 실제 운영 모델로 최초 실행, 베이스라인 리포트 확보.
- [ ] `public_recruitment`류 3개 카테고리의 진짜 페이지네이션(`startPage=2`)은
      이번에 후보 풀 2배 넓히기로 대신했다 — `JobInfoClient.search` 인터페이스를
      더 키우는 진짜 페이지네이션은 범위 밖으로 남겨뒀다.
- [ ] `history`를 사용자 발화 원문이 아니라 구조화된 이전 조건(지역/직무)까지
      함께 넘기는 방식으로 더 정교화할지는 이번 결과를 보고 재검토.
