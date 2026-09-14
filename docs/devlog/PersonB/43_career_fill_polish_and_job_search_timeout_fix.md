# 43. 근거 배지 확장, 이관 강화, 파서 테스트, 접기/펼치기, 취업정보검색 응답 실패 수정 (2026-09-14)

사용자 리포트 6건을 처리했다. 조사 결과 2건(공고/훈련 근거 표시, 블로그 파서)은
이미 구현돼 있었다 — 새로 짜지 않고 부족한 부분만 보완했다.

## 완료

### 공고·훈련에도 정책과 같은 눈에 띄는 배지
`matching.py`가 계산하는 `matched_labels`는 이미 API 응답에 있었지만
`FeedSection.tsx`가 공고/훈련 카드에서는 작은 평문(`✓ label1 · label2`)으로만
보여줬다 — 정책만 `MatchBadge`로 필(pill) 배지를 받았다(`match_tier`가 정책만
`"all"/"some"`이고 공고·훈련은 항상 `"none"`이라 배지 컴포넌트가 `null`을
반환했기 때문). `MatchBadge`를 확장해 `match_tier === "none"`이고
`matched_labels`가 있으면 라벨마다 개별 pill(`.feed-match-signal`, 정책의
옅은 합집합 색과 같은 톤)을 태그 줄에 그리도록 했다. 중복을 피하려고 카드
제목 아래의 기존 평문 줄은 정책(`match_tier !== "none"`)에만 남겼다.

### 커리어 채우기 → 취업 정보 검색 연동 강화
`draft-query-from-gap`이 confirmed_facts만 보고 초안 문장을 만들던 것에
두 가지를 더했다:
1. 이관 순간 `get_profile_extractor` 워커를 그 자리에서(백그라운드 예약이
   아니라) 호출해 희망직무/희망지역을 즉시 반영한다 — 평소엔 인터뷰 답변마다
   백그라운드로 돌지만, 이관 자체는 그 트리거가 아니었다.
2. 그렇게 최신화된 `profile_summary_lines`를 `draft_job_info_query_from_facts`에
   함께 넘겨, confirmed_facts만으로는 알 수 없는 희망직무/지역을 초안 문장에
   자연스럽게 녹이게 했다(단, "지어내지 마라" 규칙은 confirmed_facts에만 —
   프로필은 이미 확인된 정보라 예외).

"검색 결과에 근거도 함께 표시" 요구는 추가 작업이 필요 없었다 — 이관된 초안도
`/job-search/query`를 그대로 타므로, 아래 취업정보검색 수정이 곧 이관 경로의
결과 품질도 함께 올린다.

### 블로그 파서 — 이미 구현돼 있었음
`naver_blog.py`(iframe→`PostView.naver` 2단계 fetch)와 `tistory.py`(셀렉터
기반 + `generic.py` trafilatura 폴백)가 이미 있었다. 실질적 공백은
`test_tistory_parser.py`가 없었던 것뿐 — `test_naver_blog_parser.py`와 같은
패턴으로 추가했다(정상 셀렉터 2종, 폴백 2종: 셀렉터 자체가 없는 경우/셀렉터는
있지만 텍스트가 빈 경우).

### 메인 화면 카드 섹션 접기/펼치기
재사용할 기존 패턴이 없어 새로 만들었다. `FeedSection`(홈 화면 6개 카드
섹션 중 5개가 공유)의 헤더에 토글 버튼을 추가해 `useState`로 본문을 감쌌고,
`ResumeSection`(이어서 하기)에도 같은 방식을 별도로 적용했다. 상태는
`localStorage`(`feed-section-collapsed:{scope}`)에 저장 — 순수 뷰어 단
편의 기능이라 서버에 남기지 않고, 접근 불가 환경(SSR·프라이빗 창)에서도
조용히 기본값(펼침)으로 렌더링되게 읽기/쓰기 모두 try/catch로 감쌌다.

### 취업 정보 검색이 간단한 질문에 응답을 못 만드는 문제 — 원인 2건
**(a) 자기참조적 질문이 빈 카테고리로 떨어짐.** "내 맞춤 정보에 따라 취업
정보를 찾아줘"는 질문 자체에 주제어가 없어 6개 카테고리 설명 중 어디에도
안 걸리고 빈 배열로 떨어졌다 — 그 시점엔 `_profile_derived_query_params`(카테고리가
이미 정해진 뒤에만 조회 조건을 보정)에 도달도 못 하고 일반 재질문 문구만
돌아갔다. `classify_job_info_query`에 `profile_hint`(희망직무/희망지역)를
새로 넘기고, 프롬프트에 "자기참조적 질문이면 프로필을 근거로 카테고리를
폭넓게 골라라"는 지시와 예시를 추가했다.

**(b) 프론트/백엔드 시간 예산 불일치(더 치명적).** 백엔드
`_QUERY_BUDGET_SECONDS`는 2026-09-10에 DGX Spark 추론 지연 때문에 90초에서
600초로 올라갔는데, 프론트 `QUERY_TIMEOUT_MS`(105초)와 그 옆 주석("백엔드
예산 90초")은 그 변경을 못 따라갔다 — 카테고리 2-3개짜리 질문(예: "경기
북부 프로그래머...")이 105초를 넘기면 백엔드가 스킵 안내를 포함한 부분
결과를 만들기도 전에 프론트 `fetch`가 연결을 직접 끊어 "응답 없음"으로
보였다. `QUERY_TIMEOUT_MS`를 620초로 올리고 주석을 정정했다.

## 핵심 결정과 이유

**이미 구현된 것을 다시 만들지 않았다.** 계획 전 조사에서 근거 표시(2번)와
블로그 파서(4번)가 이미 구현돼 있음을 확인하고, 사용자에게 "무엇이 부족해
보였는지"를 먼저 물어 범위를 좁혔다 — 안 그러면 이미 있는 걸 다시 짜는
낭비였다.

**프로필 반영을 `extract_and_store_attributes`를 직접 부르지 않고
`get_profile_extractor` DI 훅을 통해 불렀다.** 처음엔 직접 import해서 불렀는데,
이 함수는 자기 세션(`AsyncSessionLocal`)과 `get_llm_provider()`를 직접 참조해
FastAPI의 `dependency_overrides`를 우회한다 — 테스트에서 실제 LLM 호출을
시도하게 되는 걸 뒤늦게 알아채고 DI 훅(`Depends(get_profile_extractor)`)으로
바꿨다. 이러면 프로덕션에선 그대로 동작하고 테스트에선 기존
`FakeProfileExtractor`로 자연스럽게 대체된다.

**`source_kind`를 "job_search_seed"가 아니라 기존 "job_search"로 재사용했다.**
`user_attributes.source_kind`엔 CHECK 제약(`ck_user_attributes_source_kind`)이
있어 `ATTRIBUTE_SOURCE_KINDS`에 없는 값은 그 자리에서 조용히 실패한다(호출부가
예외를 삼키므로) — 새 값을 만들 이유도 없어 이미 있는 "job_search"를 그대로 썼다.

**공고·훈련의 새 배지를 정책과 다른 색 톤으로 뒀다.** 정책의 진한 `.feed-match`는
"조건을 전부 채웠다"는 강한 신호용이다. 공고·훈련의 개별 라벨은 "이런 이유로
관련 있다"는 약한 신호 나열이라 정책의 옅은 합집합 색(`.feed-match-some`)과
같은 톤(`.feed-match-signal`)을 골라 과장되지 않게 했다.

## 검증

pytest 514개 전체 통과(신규 7개: profile_hint 전달 2종, 이관 즉시반영 1종,
detect_fact_conflicts류는 이전 devlog, 티스토리 파서 4종). 프론트
`tsc --noEmit` 통과.

**스테이징/실계정에서만 가능(자동화 불가)**:
- 공고/훈련 카드에 새 배지가 실제로 뜨는지 육안 확인.
- "커리어 채우기"→"취업 정보 검색으로 이관" 후 컴포저 초안에 희망직무/지역이
  반영되는지 확인.
- "내 맞춤 정보에 따라 취업 정보를 찾아줘", "경기 북부 프로그래머가 취직할 수
  있는 강소기업을 찾아줘" 재확인 — 실 배포 환경(느린 추론)에서만 원인 (b)가
  확실히 재현되므로 로컬보다 실계정 확인이 중요하다.
- 실제 공개 네이버 블로그/티스토리 URL로 기록물 업로드 수동 확인(체크리스트에
  남아 있던 미검증 항목).

## 관련 커밋

- (머지 전 — `feature/career-fill-flow` 브랜치, PR #75에 이어서 커밋)

## 남은 작업

- [ ] 위 스테이징 재확인 4건
- [ ] 실제 bge-m3/qwen3.5 기준 `_QUERY_BUDGET_SECONDS=600초`가 여전히 적절한
      값인지(너무 길면 사용자가 오래 기다림) — 이번엔 프론트와의 정합만
      맞췄고 절대값 자체의 재튜닝은 범위 밖.
