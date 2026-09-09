# 채팅창과 갈리는 지점을 실제로 작동하게 만들기

관련 spec: 없음(16~19와 동일하게 체크리스트 밖 항목)
날짜: 2026-09-09

---

## 배경

"클로드 같은 대화형 LLM에 직접 물어보는 것과 이 서비스의 차이가 무엇이고, 그 차이를 만들려면 백엔드에서 무엇을 고쳐야 하는가"를 먼저 조사했다. 코드를 훑어본 결론은 냉정했다.

**품질 경쟁에서는 진다.** 인터뷰는 카테고리 유형별 고정 질문 4~5개 + AI 후속 질문 최대 3개이고, 그것도 로컬 14b(dev는 3b) 모델이 돌린다. 클로드 창을 열면 무제한·문맥 기반의 더 나은 인터뷰를 받는다. "AI 인터뷰어"를 강점으로 내세우면 이길 수 없다.

**구조적으로만 이길 수 있다.** 채팅창이 원리적으로 못 하는 게 여섯 가지 있었다: (1) 문장별 출처 체인이 DB에 남는다, (2) 생성물을 기계적으로 사후 검증한다, (3) 개인 기록물이 재사용 가능한 자산으로 쌓인다, (4) 공백기 중 무엇을 아직 안 물었는지 추적한다, (5) 공공데이터 API에 접근한다, (6) 계정에 축적된다.

그런데 조사해보니 **(1)과 (5)만 실제로 작동하고 있었다.** 나머지는 스키마와 인프라만 깔려 있고 코드 경로가 없거나, 표시만 하고 아무것도 집행하지 않는 상태였다. 이번 작업은 새 기능을 붙인 게 아니라 **이미 만들어둔 해자를 켜는 일**에 가깝다.

## 완료 항목

### A. 벡터 검색이 꺼져 있던 것 (해자 3)

`search_relevant_chunks`는 카테고리에 붙은 청크를 `ORDER BY created_at LIMIT 5`로 자르는 게 전부였다. 임베딩 파이프라인도 ivfflat 인덱스(`cf08f92b1e47_init_schema.py:129`)도 다 있는데 `record_chunks.embedding`을 읽는 코드가 저장소 어디에도 없었다(`<=>`/`cosine_distance` grep 0건). **긴 블로그 글은 질문이 무엇이든 늘 앞쪽 청크만 근거로 올라왔다.**

- `search_relevant_chunks(session_id, category_id, query_text=None, top_k, embedding_provider=None)` — 3단 폴백: 벡터 검색 → 카테고리 작성순 → 세션 전체. 세션 전체 폴백을 넣은 이유는 사용자가 기록물을 '엉뚱한' 카테고리에 붙이는 일이 흔하기 때문이다(다른 데서 온 근거 하나가 근거 없음보다 낫다).
- 벡터 질의 실패(pgvector 없음/차원 불일치/임베딩 provider 다운)는 전부 조용히 작성순으로 내려간다 — 사용자가 잃는 건 근거 정렬 품질이지 인터뷰 턴 자체가 아니어야 한다.
- **`interview_ask`의 순서를 뒤집었다.** 예전엔 컨텍스트를 먼저 만들고 질문을 정했다. 이제 질문을 먼저 정하고 그 문구를 검색어로 넘긴다. 이 순서가 아니면 검색어가 존재할 수 없다. 후속 질문(질문 생성 자체가 컨텍스트를 요구)만 카테고리 이름으로 한 번 검색한 뒤 질문을 만들고, 만들어진 질문으로 다시 검색한다.
- 인터뷰 중 기록물 첨부를 다시 허용(`RECORD_CREATABLE_STATUSES`에 `INTERVIEWING` 추가). 2026-09-06에 막았던 결정을 뒤집은 것 — 기록물이 쓸모 있어지는 시점은 질문을 받은 뒤("아, 이건 블로그에 써뒀는데")이고, 벡터 검색이 켜진 지금은 방금 올린 기록물이 바로 다음 턴의 근거로 잡힌다.
- `GET /sessions/{id}/records/uncited` — 올렸는데 한 번도 인용되지 않은 청크. 채팅창이 원리적으로 못 던지는 질문("이거 올리셨는데 아직 아무 데도 안 쓰였어요")의 데이터 원천이다.

### B. 가드레일이 표시만 하고 집행하지 않던 것 (해자 2)

정합성 검사 결과는 노란 배지로 보이기만 했고 확정도 내보내기도 그대로 통과했다. **근거와 맞지 않는 문장이 그대로 이력서에 복사돼 나갈 수 있었다.**

- `evaluate_sentence_consistency()` → `ConsistencyResult(passed, score)`. 예전엔 bool만 남기고 유사도를 버려서, 실패한 문장이 0.54였는지 0.11이었는지 구분이 안 됐다 — `settings.consistency_threshold` 튜닝에 필요한 데이터가 애초에 존재하지 않았다. `generated_sentences.consistency_score` 컬럼 추가.
- `POST /document/finalize`가 검사에 걸린 문장이 남아 있으면 409로 막고, **어떤 문장인지 목록으로** 돌려준다. `{"acknowledge_unverified": true}`로 다시 호출하면 통과 — 판단은 사용자 몫이지만 모르고 지나칠 수는 없게.
- `generated_sentences.edited_by_user` 추가. 사용자가 고쳐 쓴 문장도 `consistency_check_passed=True`인 건 유지했지만(본인이 쓴 말은 정의상 확인된 사실이다 — 04_document_generation.md 2절), 그 True를 "임베딩 검증 통과"와 같은 배지로 보여주면 거짓말이 되므로 출처를 구분한다.
- `evidence_grade` (`record_backed` / `self_reported` / `unsupported`) — 문장이 인용한 사실들의 `source_type`에서 파생. 채용담당자 입장에서 검증 가능한 문장과 본인 진술뿐인 문장을 구분하는, 이 서비스가 팔 수 있는 유일한 명분이다.

### C. 이름값을 못 하고 있던 것 (해자 4)

**"공백기 채우기" 서비스가 공백기가 얼마나 채워졌는지 계산할 수 없었다.** `gap_periods`에 전체 시작/끝만 있고 활동 쪽에는 날짜가 전혀 없었다.

- `activity_categories.period_start / period_end / period_source` 추가. `period_source`는 `ai_inferred | user_set` — 사용자가 직접 넣은 값은 이후 LLM 추정이 덮어쓰지 않는다.
- 새 LLM 능력 `extract_activity_period(category_label, facts, gap_start, gap_end)` + `activity_period.jinja`. 단서가 없으면 반드시 null(공백기 전체를 베껴 쓰지 말라고 명시). 공유 헬퍼 `clamp_activity_period()`가 공백기 밖으로 삐져나간 추정치를 자르고, 아예 안 겹치면 추정을 버린다.
- **카테고리가 끝날 때가 아니라 `frequency`/`context` 사실이 확정되는 즉시** 유추한다. 그래야 후속 질문 예산과 커버리지가 인터뷰 도중에 의미를 갖는다.
- `app/services/coverage.py` — 구간 병합/뺄셈. 병행한 활동을 두 번 세지 않고(`merge_ranges`), 30일 미만 틈은 보고하지 않는다(월 단위 단서에서 유추된 데이터의 해상도 문제이지 실제 공백이 아니다).
- `GET /sessions/{id}/coverage`, `PATCH /sessions/{id}/categories/{id}/period`, `POST /sessions/{id}/coverage/fill`(빈 구간 전용 카테고리를 만들고 인터뷰를 거기로 옮긴다).
- `orchestrator.followup_budget(category)` — 6개월 이상 활동은 후속 질문 예산 3 → 5. 6개월을 통째로 쓴 활동과 2주짜리를 똑같이 3턴으로 끊는 건 공백기를 실제로 메우고 있는 쪽에 시간을 덜 주는 셈이다.

### D~F. 근거의 생존, 계정 축적, 버전

- **`interview_answers` 테이블** (작업 중 사용자 요청: "이메일로 등록된 사용자 별로 문답 결과를 저장하는 것으로 하자"). 사용자가 실제로 타이핑한 답변 원문은 지금까지 **어디에도 저장되지 않았다** — `extract_facts`가 요약한 짧은 사실 문장만 `confirmed_facts`에 남고 원문은 `pending_turn`을 스쳐 사라졌다. 이 테이블은 `user_id`에 직접 매달리고 `session_id`는 SET NULL이라 세션을 지워도 계정에 남는다.
- `GET /me/answers`(+`/summary`, `DELETE /me/answers/{id}`) — 이메일 등록 계정 전용. 게스트 세션에서 남긴 기록도 같은 user 행에 저장되므로, 회원가입으로 승격되는 순간(`auth.py`의 게스트 승격) 그대로 이어진다.
- 내보내기: `format=md` 추가, `citations=true`로 근거 부록(출처 URL + 게시일). 예전엔 문장 텍스트만 뱉어서 **인터뷰 내내 모은 출처가 복사-붙여넣기 한 번에 전부 증발했다.**
- `GET /sessions/{id}/documents` — 버전 목록. `regenerate`는 예전 버전을 version+1로 쌓아왔는데 정작 최신 1건 말고는 꺼내볼 방법이 없었다.

## 핵심 결정 사항과 이유

**차별화의 축을 "더 나은 AI 인터뷰"에서 "검증 가능한 경력 기록 시스템"으로 옮겼다.** 전자는 모델 체급 싸움이라 구조적으로 진다. 후자는 스키마가 이미 다 깔려 있었고 코드 경로만 없었다.

**활동 기간은 `confirmed_facts`에 넣지 않았다.** LLM이 유추한 값이라 정직성 가드레일의 "사용자가 확인한 사실"이 아니다. 카테고리 메타데이터로 두고 `period_source`로 출처를 구분한다 — 커버리지 계산과 화면 표시에만 쓰이고 생성 문서에 인용될 경로가 없다. `interview_answers`도 같은 이유로 문서 생성 입력에서 제외된다(생성 함수는 여전히 `confirmed_facts`만 받는다).

**빈 구간 채우기는 사용자가 명시적으로 호출해야 한다.** 인터뷰가 스스로 카테고리를 만들어내면 무한정 늘어날 수 있어서, 서버는 빈 구간과 질문 문구를 계산해 내려주기만 하고 카테고리 생성은 `POST /coverage/fill`이라는 별도 호출로 분리했다.

**finalize 차단의 기본값을 "막음"으로 뒀다.** `acknowledge_unverified`가 기본 False라 모르고 지나치는 경로가 없다. 사용자가 검토한 뒤 그대로 두겠다고 하면 통과시킨다.

**사용자 편집 문장의 `consistency_check_passed`는 True를 유지했다.** 재검증으로 바꾸면 04_document_generation.md 2절의 결정("본인이 쓴 말은 정의상 확인된 사실")을 뒤집는 것이 된다. 문제는 판정값이 아니라 **표시**였으므로 `edited_by_user` 플래그로 구분하고 점수는 무효화했다.

## 트러블슈팅

**SQLite가 `ON DELETE SET NULL`을 강제하지 않는다.** 세션을 지워도 `interview_answers.session_id`가 그대로 남아 테스트가 깨졌다(`PRAGMA foreign_keys` 기본 OFF). PRAGMA를 켜는 대신 `Session.interview_answers` 관계를 **delete cascade 없이** 추가했다 — SQLAlchemy가 부모 삭제 시 FK를 NULL로 UPDATE하므로 DB 종류와 무관하게 같은 결과가 보장된다.

**`session_client` 픽스처에 `generated_sentences` 테이블이 없었다.** 세션 삭제가 `ActivityCategory.generated_sentences`(cascade all, delete-orphan)를 lazy-load하는데 테이블이 없어 터졌다. 기존 픽스처가 이미 쓰던 "행은 없어도 테이블은 있어야 한다" 패턴에 맞춰 추가.

**`regenerate_sentence`에서 점수를 옛 문장으로 계산할 뻔했다.** 리팩터링 중 `evaluate_sentence_consistency`를 `sentence.text = new_sentence.text` **앞**에 두어, 새 문장이 아니라 교체 전 문장을 검사하고 있었다. 순서를 되돌렸다.

## 검증

- 백엔드 pytest **181 → 239개 통과**. 신규: 커버리지 로직 12개, 커버리지 API 9개, 계정 문답 아카이브 10개, 가드레일/근거등급/내보내기/버전 11개, 청크 검색 8개, 인터뷰 검색·기간 유추 6개.
- 기존 테스트 3개는 **의도한 동작 변경**이라 갱신했다: 인터뷰 중 기록물 첨부 허용 2개, `chunk_search` 시그니처 변경 1개.
- 마이그레이션 `d8c1b4a70f22`: 오프라인 SQL로 컴파일 확인 후 dev Supabase에 실제 적용 완료.
- 프론트: `tsc --noEmit` / `eslint` / `next build --webpack` 전부 클린. (`next build` 기본 Turbopack은 이 PC의 Application Control 정책이 네이티브 SWC 바이너리를 막아 실패한다 — 이번 변경과 무관한 기존 환경 문제.)

## 남은 작업

- **벡터 검색을 실 데이터로 확인하지 않았다.** SQLite 테스트는 폴백 경로만 검증한다(pgvector 연산자가 없으므로 벡터 질의는 항상 실패해 작성순으로 내려간다). 실제 pgvector에서 코사인 정렬이 기대대로 동작하는지, 그리고 그 결과 근거 품질이 실제로 좋아지는지는 실 Supabase + 실 임베딩으로 블로그 글 하나를 넣고 확인해야 한다.
- `extract_activity_period`의 실 LLM 품질 미확인. 로컬 dev 모델(`qwen2.5:3b-instruct`)로는 "단서가 없으면 null"을 얼마나 지키는지 신뢰하기 어렵다 — 지키지 못하면 커버리지가 낙관적으로 부풀려진다. 18번 devlog의 관련성 판단과 같은 종류의 미검증 항목이다.
- `MIN_REPORTABLE_GAP_DAYS`(30일)와 `LONG_ACTIVITY_DAYS`(180일)는 근거 있는 추정치일 뿐 실제 샘플로 조정하지 않았다. `consistency_score`를 이제 저장하므로 임계값 튜닝(A-6에서 남겨둔 과제)은 데이터가 쌓이는 대로 가능해졌다.
- `GET /me/answers`를 실제로 쓰는 화면이 아직 없다 — 새 세션 시작 시 "예전에 이렇게 답하셨어요"로 제안하는 UI가 붙어야 계정 축적이 사용자에게 의미를 갖는다.
- 커버리지 UI(빈 구간 표시 + 채우기 버튼) 미구현. 백엔드 엔드포인트만 있는 상태다.
