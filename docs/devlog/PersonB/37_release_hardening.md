# 37. 릴리스 검증 보고서 반영 (2026-09-12)

2026-09-12 게스트 6세션 검증(운영 사이트, `feature/remove-composer-prefill` 직후)에서 나온
문제를 코드로 반영했다. 근본 원인이 확정된 건(Spark CUDA 크래시, PersonA devlog 10) 앱
쪽에서 유효한 완화책만 넣었고, 진행률 표시 재도입처럼 최근 결정(devlog 34)과 충돌하는
항목은 제외했다. 후속 질문 프롬프트 튜닝은 성격이 달라 별도 작업으로 미뤘다.

## 완료

### P0 — 실패 시 사용자 노출 줄이기

- [x] **LLM 호출 재시도 1회** (`backend/app/services/llm/local_ollama.py`): `_generate`가
      `_generate_once`를 감싸고, `LLMUnavailableError`가 나면 4초 대기 후 한 번만 재시도한다.
      타임아웃(`_TimedOutRequest`)은 재시도하지 않는다 — 이미 240초를 다 쓴 것이므로
      다시 걸어도 소용없다.
- [x] **요청 직렬화** (`app/services/llm/ollama_gate.py`, 신규): 생성·임베딩 호출이
      `asyncio.Semaphore(1)`을 공유한다. 크래시 자체를 막지는 못해도, 우리 쪽 요청끼리
      겹치지 않게 해서 크래시 한 번이 죽이는 요청을 최대 1개로 줄인다(실측: 순차 8.3% →
      동시 3건 33.3% — 동시성이 실패율을 증폭시켰다).
- [x] **인터뷰 답변 실패에 재시도 버튼** (`frontend/components/InterviewSection.tsx`):
      실패한 답변은 `pendingAnswerText`에 그대로 남아 있었지만(기존 동작) 재전송 수단이
      없었다. `JobSearchChatPage`의 "다시 시도"와 같은 패턴을 추가했다.
- [x] **"여러 활동 있나요?" 0건 응답 자동 진행**: 후보가 빈 배열로 오면 사용자가 "다음"을
      누르지 않아도 자동으로 빈 확인을 제출한다.

### P1 — 고용24 파이프라인: 장애와 "결과 없음" 구분

- [x] **로깅 추가** (`job_info_client.py`, `job_search.py`): 이 파일들에 `logging`이 아예
      없어서, 검증 중 마주친 고용24 전면 장애를 API 응답만으로는 진단할 수 없었다. `_get`/
      `_check_error`의 오류 변환 지점과 `job_search.py`의 skip 지점에 카테고리명 + 오류
      종류/상태코드만 남긴다. **URL·authKey는 절대 로깅하지 않는다**(기존 코드가 이미 이
      이유로 `raise_for_status()` 대신 수동 상태 체크를 쓰고 있었다 — 그 관례를 그대로 따랐다).
- [x] **`training_course`의 전면 장애를 구분 가능하게**: 4개 하위 엔드포인트가 전부
      실패하면(그날의 고용24 점검처럼) 예전엔 조용히 빈 목록으로 바뀌어 "결과 없음"과
      구분이 안 됐다. `_safe()`가 성공 여부를 함께 반환하도록 바꾸고, 모든 시도(좁게 →
      지역만 → 무조건, 최대 3단계)에서 단 하나도 성공하지 못하면 다시 던져 다른 5개
      카테고리처럼 `skipped_category_labels`로 분류되게 했다.

### P1 — 프론트 상태 관리

- [x] **로그아웃 후 이전 사용자 흔적 제거**: `queryKeys.sessions()`가 전역 키라 로그아웃해도
      세션 목록 캐시가 안 지워졌다 — `AuthHeader.handleLogout`에서 `removeQueries`로 지운다.
      `page.tsx`의 히어로 조건도 `!!user`를 함께 봐서 이중으로 막는다.
- [x] **사이드바 로딩/오류/빈 상태 구분**: `useSessionsList()`에서 `isLoading`/`isError`를
      받아 "불러오는 중...", "불러오지 못했어요", "세션이 없습니다."를 따로 보여준다.
      Render 콜드스타트(최대 약 80초) 동안 세션이 삭제된 것처럼 보이던 문제를 고친다.

### P2 — 조사만 (코드 변경 없음)

**질문: 검증 중 왜 랜딩 페이지엔 고용24 데이터가 떠 있는데 대화형 검색은 0건이었나?**

`services/feed/sources/worknet_source.py`(랜딩)와 `services/job_pipeline/job_info_client.py`
(대화형 검색)를 대조해 원인을 확인했다:

- 랜딩은 **DB에 쌓인 캐시**(`FeedItem` 테이블)를 보여준다. `WorknetFeedSource.fetch`가
  주기적으로(`feed_refresh_ttl_seconds`, 기본 6시간) `job_info_client`의 같은 함수를
  호출해 갱신하지만, 실패하면 로그만 남기고(`feed: source %s failed`) **기존 행을
  건드리지 않는다** — 즉 장애 중 갱신 시도는 조용히 실패하고, 장애 시작 **이전**의
  마지막 성공 스냅샷이 계속 보인다.
- 대화형 검색(`job_search.py`)은 질문마다 **매번 실시간으로** 같은 함수를 호출한다 —
  캐시가 없다.

**결론: 버그가 아니라 캐시 대 실시간의 당연한 결과다.** 다만 장애 중에는 사용자에게
"랜딩엔 있는데 검색하면 없다"는 혼란스러운 경험이 된다. 대화형 검색이 실시간 호출
실패 시 같은 피드 캐시로 폴백할지는 **검색 결과의 신선도 보장을 낮추는 제품 결정**이라
이번 범위에서 빼고 사용자 판단으로 남긴다.

## 핵심 결정과 이유

**중복 사실 제거는 시도했다가 되돌렸다.** `_review_read`에서 카테고리 안의 정확히 같은
`content` 문자열을 첫 등장만 남기고 빼려 했는데, 기존 테스트
`test_followup_budget_caps_ai_questions_but_never_skips_a_fixed_one`이 "후속 질문 3개가
똑같은 텍스트를 답해도 확정 사실 3개가 각각 나와야 한다"를 명시적으로 검증하고 있어
정면으로 충돌했다(테스트 하네스가 `FakeLLMProvider.extract_facts`의 기본 동작상 여러
턴에 같은 placeholder 텍스트를 재사용하기 때문이기도 하다). fact_type 단위로 좁혀도 이
테스트는 여전히 깨진다. 근본 원인(후속 질문이 앞 질문과 사실상 같은 걸 물어 사용자가
같은 답을 반복하게 만드는 것)은 이미 별도 작업(프롬프트 튜닝)으로 미루기로 한 항목과
같으므로, 검토된 대안 없이 기존 검증된 동작을 깨면서까지 밀어붙이지 않았다. **되돌렸다
— 근본 원인 작업 때 다시 본다.**

**직렬화 테스트를 만들다 제 테스트 스텁의 버그를 하나 잡았다(참고용 기록).** 처음
`asyncio.Semaphore`가 동작하지 않는 것처럼 보이는 실패(`max=3`)를 봤는데, 프로덕션
코드가 아니라 테스트 스텁이 원인이었다 — `_collect_stream`은 `done:true`를 보면 즉시
`break`하는데, 이때 async generator는 안 닫히고(GC 전까지) `yield` 뒤에 있던 카운터
감소 코드가 실행되지 않아, "동시 진입 수" 카운터가 절대 안 줄어드는 단조증가 카운터가
되어 있었다. `asyncio.Semaphore` 자체와 실제 세마포어 사용 코드는 처음부터 정상이었다
— 여러 단계로 좁혀가며 재현한 뒤에야 확인했다. 카운터 감소를 `yield` **앞**으로 옮겨
고쳤다.

## 관련 커밋

- `bdc871f` — fix: harden app against Ollama crash and clean up interview/job-search UX gaps ([PR #67](https://github.com/2024YSJ/Annswieteom/pull/67))

## 남은 작업

- [ ] 후속 질문 프롬프트 튜닝(자기성찰형 질문 쏠림) — 별도 작업. 여기서 되돌린 중복 사실
      제거도 이때 함께 재검토
- [ ] 대화형 검색의 캐시 폴백 여부 — 제품 결정 필요
- [ ] Spark `OLLAMA_FLASH_ATTENTION=0` 적용 확인(PersonA devlog 10)
