# 34단계 — 기록물 업로드를 카테고리별 순차 요청으로 전환

## 문제

기록물 업로드(`RECORD_UPLOAD`) 단계는 카테고리 선택 다음에 오면서도 카테고리와 완전히
무관하게 동작했다 — `records` 테이블에 카테고리 FK가 없고, 프론트도 세션 전체에 대해
자료를 한 번에 받는 단일 화면이었다. 인터뷰 시점에는 카테고리 라벨을 임베딩해
`record_chunks`를 의미 검색으로 매칭했는데, `docs/checklists/person_B_frontend_backend/03_records_feature.md`에
"실사례에서 검증되지 않았고 항상 generic_pattern으로만 나온다"고 적어뒀을 만큼 이 매칭은
신뢰할 수 없었다.

사용자 요청은 단순했다 — "카테고리화하고 각 카테고리에서 자료를 요청하는 것으로 하자."
이 앱은 이미 인터뷰 단계에서 `session.current_category_id`로 카테고리를 하나씩 순회하는
대화형 패턴을 갖고 있었으므로, 기록물 요청도 같은 패턴(카테고리를 순서대로 하나씩,
채팅형 UI)으로 맞추기로 했다.

## 구현

**DB**: `records.category_id`(nullable FK → `activity_categories`, `ON DELETE CASCADE`) 추가
(`d5f1a9c3e8b7_add_record_category_id.py`). nullable로 둔 건 기존 프로덕션 레코드를
백필할 방법이 없어서고, 새로 생성되는 레코드는 애플리케이션 코드가 항상 채운다.

**상태 머신**: `records/skip`이 더 이상 `RECORD_UPLOAD → INTERVIEWING` 고정 전이가 아니게
됐다 — `resolve_after_confirm()`과 대칭되는 `resolve_after_records()`를 추가해서, 다음
카테고리가 있으면 그쪽 기록물 요청으로(`RECORD_UPLOAD` 유지), 마지막이었으면 인터뷰를
시작하며 **첫 번째 카테고리로 되돌아간다** — 기록물 요청 순회 동안 `current_category_id`가
마지막 카테고리까지 옮겨가 있으므로, 인터뷰는 다시 처음부터 시작해야 하기 때문. `POST
/categories`도 카테고리 생성 직후 `current_category_id`를 첫 카테고리로 세팅하도록 바뀌었다
(전에는 이 세팅이 `records/skip` 안에만 있었다).

**레코드 생성 3종 엔드포인트**(`records`, `records/text`, `records/upload`) 모두
`category_id=session.current_category_id`를 자동으로 붙인다 — 클라이언트가 지정하는 게
아니라 서버 세션 상태에서 그대로 가져온다.

**`search_relevant_chunks`를 단순화**: 카테고리 라벨을 임베딩해 코사인 유사도로 비교하던
방식을 걷어내고, `Record.category_id == category_id`로 직접 필터링하도록 바꿨다. 레코드가
이제 카테고리에 직접 연결되므로 굳이 의미 검색이 필요 없어졌고, 애초에 이 유사도 매칭은
한 번도 제대로 작동한 적이 없었다.

**프론트 `RecordsSection`**: `InterviewSection`/`InterviewChatThread`의 카테고리 순회
패턴을 그대로 따라 재작성 — 지나간 카테고리는 라벨 + 업로드했던 자료 목록으로 압축
표시하고, 현재 카테고리만 질문 버블 + 업로드 영역 + "다음 카테고리로"(자료 있으면)/"이
카테고리 자료 없이 넘어가기"(없으면) 버튼을 보여준다. `ActivityCategoryRead`에
`records: RecordRead[]`를 추가해 새로고침해도 카테고리별 업로드 이력이 그대로 복원되게
했다(`confirmed_facts`와 같은 패턴).

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `document_client` 픽스처를 쓰는 테스트 17개가 전부 `no such table: records`로 실패 | `ActivityCategory.records` 관계를 추가하고 `GET /sessions/{id}`가 이걸 eager-load하게 되면서, 문서 생성 테스트 픽스처가 만드는 SQLite 테이블 목록에 `Record`/`RecordChunk`가 애초에 없었다는 게 처음으로 드러남(이전엔 이 관계 자체가 없어서 문제가 안 됐다) | `tests/api/conftest.py`의 `document_client` 테이블 목록에 `Record.__table__`, `RecordChunk.__table__` 추가 |
| 카테고리 2개 이상으로 `records/skip`을 한 번만 호출하던 기존 테스트 헬퍼들이 `INTERVIEWING` 대신 `RECORD_UPLOAD`에 머무름 | `records/skip`의 의미가 "전체 기록물 단계 스킵"에서 "현재 카테고리 하나만 넘기기"로 바뀐 게 당연한 결과 | `test_interview.py::_advance_to_first_category`, `test_document.py::_advance_to_result_generate`를 카테고리 개수만큼 반복 호출하도록 수정 |
| Playwright로 실제 브라우저 검증 중 `/sessions/[id]` 첫 진입이 계속 멈춤, 이후 dev 서버가 "Jest worker encountered 2 child process exceptions"를 반복 출력하며 완전히 맛이 감 | 액세스 토큰이 의도적으로 메모리에만 저장되는데(`auth-context.tsx`), 검증 스크립트가 상태 갱신을 위해 `page.reload()`를 호출해 로그인 상태를 통째로 날려버렸고, 이게 겹치면서 Turbopack 컴파일 워커가 죽어버림 | `page.reload()`를 쓰지 않고 전체 플로우(기간→카테고리→기록물)를 실제 UI 조작으로만 진행하도록 스크립트를 바꾸고, 죽어버린 dev 서버 프로세스는 재시작 |

## 실제 검증

로컬 dev DB(`annswieteom-dev`)에 마이그레이션 적용 후, curl로 상태 전이(카테고리 2개 →
기록물 요청이 하나씩 넘어가는지 → 마지막에 인터뷰가 첫 카테고리로 리셋되는지)와
`category_id` 태깅을 확인했고, Playwright로 게스트 시작부터 실제 로컬 LLM 카테고리
추출 → 기록물 카테고리별 요청 → 인터뷰 진입까지 브라우저로 끝까지 눌러봤다. 카테고리
1에 텍스트 기록물을 하나 올렸더니, 인터뷰가 그 카테고리의 첫 질문에서 AI 초안 답변에
그 기록물 내용을 실제로 반영하는 것까지 확인 — `category_id` 기반 조회가 실제로
작동한다는 뜻.

## 후속: 기록물 첨부를 그 단계 전용으로 좁히기

바로 이어서 "기록물은 그 단계에서만 첨부 가능하게 하고, 첨부 버튼은 채팅바가 아니라
'기록물 없이 넘어가기' 옆에 두자"는 요청이 왔다.

- **백엔드**: `RECORD_CREATABLE_STATUSES`를 `("RECORD_UPLOAD", "INTERVIEWING")`에서
  `("RECORD_UPLOAD",)`로 좁혔다 — 인터뷰 중에도 기록물을 추가로 붙일 수 있게 했던
  이전 설계(B-3 devlog, "레코드는 인터뷰 단계에서도 부착 가능")를 이번 요청으로 되돌린
  것. `test_records_can_still_be_attached_once_interviewing`을 정반대 기대값(409)으로
  뒤집었다.
- **프론트**: `ChatComposer`가 쥐고 있던 첨부(📎 블로그 URL/이미지) 버튼·팝오버·URL
  폼·숨은 파일 인풋 전체를 들어내 `RecordsSection`으로 옮기고, 그 자리를 "이 카테고리
  자료 없이 넘어가기"/"다음 카테고리로" 버튼 옆에 새로 만들었다. `ATTACH_ENABLED_STEPS`
  개념 자체가 없어졌다(첨부가 필요한 단계가 기록물 단계 하나뿐이라 굳이 구분할 이유가
  사라짐). `ComposerEvent`도 `"url"`/`"file"` variant를 없애고 `"text"` 하나만 남겼다.
  `InterviewSection`이 쓰던 `useRecordAttach` 훅은 유일한 소비자가 사라져서 파일째
  삭제했다.
- 채팅바(텍스트에어리어)는 별도 스타일 조정 없이 자동으로 넓어졌다 — 원래
  `flex:1`이었고 옆의 📎 버튼만 `flexShrink:0`으로 폭을 차지하던 구조라, 그 버튼을
  없애자 flexbox가 남은 폭을 텍스트에어리어에 그대로 몰아줬다.
- **트러블슈팅**: 백엔드를 `--reload` 없이 띄워둔 채로 이 변경을 검증하다가 실제
  서버가 옛 코드(인터뷰 중에도 첨부 허용)로 계속 응답하는 걸 새 동작인 줄 착각할
  뻔했다 — dev 서버를 `uvicorn ... --reload`로 재기동한 뒤에야 정상적으로 409가
  나오는 걸 확인했다. 로컬에서 코드만 고치고 이미 떠 있는 서버로 바로 검증할 땐 항상
  reload 여부부터 의심할 것.

## 남은 일

- 이 브랜치가 `dev`/`main`에 머지되면 `d5f1a9c3e8b7` 마이그레이션을 프로덕션 Supabase에도
  반드시 적용해야 한다(이전에 마이그레이션 적용을 빠뜨려 500이 났던 사고가 있었으니
  배포 직후 확인할 것).
- 로컬 LLM(`qwen2.5:3b-instruct`)이 카테고리 라벨을 추출할 때 한글 사이에 가타카나가
  섞여 나오는 걸 검증 중 목격했다(예: "아르바이트"가 "아르바イト"로) — 이번 변경과는
  무관한 기존 카테고리 추출 프롬프트/모델 품질 이슈라 범위에서 제외했다.
