# 45. 관련성 판정에 대화 맥락이 안 실리던 버그 수정 (2026-09-15)

배포 직후 실계정으로 "간호사" 관련 4턴 대화를 테스트하다 발견: "간호사 채용
정보 알려줘" → "그중에서 서울 지역만 보여줘"에서, 지역은 맞지만 간호사와 전혀
무관한 "기술영업직" 공고가 관련 있다고 잘못 골라졌다.

## 원인

devlog 44에서 `classify_job_info_query`/`extract_job_info_query_params`에는
`history`를 넘기게 고쳤지만, 실제로 사용자에게 보여줄 항목을 최종적으로
고르는 `select_relevant_job_info_results`에는 `history`를 안 넘기고 있었다.
그 결과 "그중에서 서울 지역만 보여줘"라는 후속 질문만 단독으로 관련성 판정
프롬프트에 들어가서, "간호사"라는 직무 조건이 그 호출 안에서는 아예 존재하지
않았다 — 지역(서울)만 맞으면 뭐든 관련 있다고 판단할 수밖에 없는 구조였다.

## 수정

`select_relevant_job_info_results`에도 동일하게 `history` 파라미터를 추가하고
(`base.py`, `local_ollama.py`, `job_search.py` 배선), 프롬프트
(`select_relevant_job_info_results.jinja`)에 `[이전 대화]` 블록과 "이전
대화의 직무 조건이 이번 후속 질문에서도 여전히 유효하다"는 지시 + 정확히 이
버그 사례를 그대로 옮긴 few-shot 예시를 추가했다.

**예시 순서에 주의했다**: 기존 마지막 예시는 devlog 19에서 "약한 모델이 정답
2건 중 1건만 고르는 과교정"을 막기 위해 의도적으로 복수 선택 사례를 마지막에
둔 것이었다(`test_select_relevant_prompt_demands_exhaustive_selection`이 이걸
회귀 테스트로 고정해뒀다). 새 예시를 그 뒤에 붙였다가 이 회귀 테스트가
바로 잡아냈다 — 새 예시를 기존 마지막 예시 앞에 끼워 넣어 마지막 자리를
그대로 지켰다.

## 검증

pytest 521개 전체 통과(신규 2개: `select_relevant_job_info_results`가
history를 실제로 프롬프트에 렌더링하는지 템플릿 테스트, API 레벨에서 history가
관련성 판정 호출까지 도달하는지 라우트 테스트). 실계정 재현 테스트는 아래
20개 직업 테스트 라운드에서 같이 확인한다.

## 관련 커밋

- (머지 전 — `fix/job-search-relevance-history` 브랜치)
