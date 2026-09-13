# 40. 임베딩 기반 직무 유사도 매칭 — 공고/훈련/정책 확장 (2026-09-13)

devlog 39(텍스트 매칭)의 리콜 손실을 bge-m3 임베딩 코사인 유사도로 보완했다. 실제
계정 검증에서 "백엔드 프로그래머"가 캐시된 강소기업 공고의 "소프트웨어 개발" 문구를
못 잡는 게 확인돼(어휘는 다르지만 의미는 같음) 착수했다. 사용자 요청으로 맞춤
공고뿐 아니라 맞춤 직업훈련·맞춤 지원 정책에도 같은 방식을 확장했다.

## 완료

### 신규 테이블
`feed_item_occupation_embeddings`(제목만 임베딩 — `FeedItemEmbedding`의
embed_text=제목+부제+메타는 지역·회사명·날짜가 직무 신호를 희석해서 별도로 뒀다),
`user_occupation_embeddings`(`UserProfileEmbedding`과 달리 지문/개수/시각 삼종 검사
없이 `source_text` 등가 비교만 — desired_job이 한 줄짜리 고정 문자열이라 과설계
방지). 마이그레이션 `d2a6f19e4b73`(head `c7d1e5a9f2b4`에서 분기, 확인 완료).

### 백그라운드 계산
- 아이템: `ingest.py`에 `_embed_occupation_pending` 신설, `_embed_pending`과 같은
  배치·락(`_EMBED_LOCK` 공유)·에러관용 패턴, `item.title`만 임베딩.
- 사용자: `services/feed/occupation_adapter.py` 신규 — `profile_adapter.py`에
  안 얹은 이유는 그쪽이 다루는 게 완전히 다른 성격(커지는 문답 블록)의 데이터라서다.

### 정렬 로직 (`matching.py`)
`_vector_distances`를 `embedding_cls` 파라미터로 일반화해 두 벡터 테이블 모두에
재사용:
- **공고**: 벡터가 있으면 코사인 거리, 없으면 기존 텍스트 점수 — 측정된 신호가
  항상 추측보다 우선하도록 2단계 정렬 키.
- **훈련**: 지역이 여전히 1순위(통학 문제), 그다음 직무 벡터, 그다음 기존 프로필
  벡터. 순수 추가라 회귀 없음.
- **정책**: 티어는 절대 안 바뀐다(`score_item`이 desired_job을 안 봄) — 같은 티어
  안에서만 직무 벡터가 순서를 가른다.

### 검증
pytest 498개 통과(신규 21개: matching 3, occupation_adapter 11, ingest 3, feed API 4).
SQLite에는 pgvector가 없어 실제 코사인 거리는 `matching._vector_distances`를
monkeypatch로 스텁해 정렬 로직만 검증했다 — 실제 bge-m3 벡터가 의미적으로 타당한
결과를 내는지는 스테이징/운영에서만 확인 가능하다(기존 `e7a1c93d5b20` 마이그레이션도
같은 한계를 이미 인정함).

## 핵심 결정과 이유

**title만 임베딩하고 embed_text 전체는 안 썼다.** 기존 `FeedItemEmbedding`을 그대로
재사용하지 않고 새 테이블을 판 이유 — embed_text는 지역·날짜·회사명이 섞여 있어
직무 신호를 희석한다. 이건 애초에 오늘 고친 버그(맞춤 공고가 지역만 보고 직무를
못 봄)와 같은 근본 원인이라, 같은 실수를 새 기능에서 반복하지 않으려 별도 텍스트를
골랐다.

**`UserOccupationEmbedding`에 `UserProfileEmbedding`류의 지문/개수/시각 검사를
안 뒀다.** desired_job은 사용자가 손으로 고칠 때만 바뀌는 한 줄짜리 문자열이다 —
자라는 텍스트 블록(문답 아카이브)을 위해 설계된 삼종 검사를 그대로 가져오면 과설계다.
`source_text` 문자열 등가 비교로 충분하다.

**정책 티어는 절대 안 바꿨다.** 온통청년 정책엔 직무 자격조건 자체가 없다(스펙
문서에 이미 명시) — 직무 벡터가 아무리 가까워도 `some` 티어 정책이 `all` 티어
정책을 앞지르면 신청 자격이 없는 걸 앞세우는 꼴이 된다. 회귀 테스트로 이 경계를
명시적으로 고정했다(`test_rank_tiered_never_lets_occupation_cross_a_tier_boundary`).

**공고 랭킹에서 벡터가 항상 텍스트 추측보다 우선한다.** 벡터가 아직 없는(백필 전)
항목이 완벽한 텍스트 일치라도 벡터 매칭 항목보다 뒤로 밀리는 대가가 있지만, 다음
`refresh_feed()`에서 해소되는 일시적 현상이고 오늘(벡터 자체가 없던 상태)보다
나빠지지 않는다.

**`OCCUPATION_VECTOR_LABEL_THRESHOLD = 0.35`는 추정치다.** 실제 bge-m3 코사인 거리
분포를 스테이징에서 관찰한 뒤 조정해야 한다 — 지금은 라벨 표시 여부에만 영향을
주고 정렬 자체(연속값 거리 비교)는 이 임계값과 무관하게 정확하다.

## 관련 커밋

- (PR 머지 후 채움)

## 남은 작업

- [ ] `alembic upgrade head`를 실제 Postgres+pgvector에 적용, 두 신규 테이블 생성 확인
- [ ] `refresh_feed()` 한 번 돌려서 `feed_item_occupation_embeddings` 백필 확인,
      기존 `_embed_pending`(락 공유)이 느려지지 않는지 확인
- [ ] 오늘 검증에 쓴 실제 계정(희망직무=백엔드 프로그래머)으로 `/feed/jobs/recommended`
      재확인 — "소프트웨어 개발" 공고가 이번엔 상위로 오는지가 이 작업의 성공 기준
- [ ] `/feed/trainings/recommended`·`/feed/policies/recommended`도 같은 계정으로
      확인 — 지역이 여전히 직무보다 우선하는지(훈련), 티어 경계가 안 깨지는지(정책)
- [ ] 실제 코사인 거리 분포를 보고 `OCCUPATION_VECTOR_LABEL_THRESHOLD` 조정
- [ ] Ollama 임베딩 호출량이 2배(제목 임베딩 추가)로 늘어난 게 `OLLAMA_GATE` 경합에
      영향을 주는지 운영 로그로 확인
