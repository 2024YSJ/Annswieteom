# B-4. 문서 생성/조회/수정 API + 결과 화면

근거: 명세서 9-5절, 12절(프롬프트 연동), 14절
선행 조건: [02_interview_state_machine_api.md](02_interview_state_machine_api.md) (`confirmed_facts` 확보), A의 [02_llm_adapter_layer.md](../person_A_infra_ai/02_llm_adapter_layer.md), [06_consistency_check.md](../person_A_infra_ai/06_consistency_check.md)
폴더: `backend/app/services/document_generator.py`, `backend/app/api/document.py`, `frontend/app/sessions/[id]/result/`
브랜치: `feature/document-generation` (`dev`에서 분기, 완료 후 `dev`로 PR)
시점: 2~3주차

> 이 체크리스트는 정직성 가드레일(1-2절)이 실제 코드로 구현되는 가장 중요한 지점이다. `document_generator.py`의 함수 시그니처 자체가 `confirmed_facts` 외의 데이터를 받을 수 없게 설계돼 있어야 한다.

## 1. `document_generator.py` 구현

`LLMProvider.generate_document(facts, tone)`(10-1절, A가 구현)는 **카테고리 하나 분량**의 사실만 받아 한 번에 그 카테고리의 문장들을 만드는 저수준 함수다. `document_generator.py`는 그 위에서 **세션 전체의 카테고리를 순회하는 오케스트레이션**을 담당한다 — 이름이 같은 함수를 두 번 정의하는 게 아니라, 아래처럼 상위 함수 하나를 새로 만든다.

- [ ] 오케스트레이션 함수 작성, 예: `async def generate_full_document(session_id: UUID, tone: str) -> GeneratedDocument`
  1. 세션의 `activity_categories`를 순회
  2. 카테고리별로 `confirmed_facts`를 조회해 리스트로 구성
  3. 카테고리마다 **주입받은 `LLMProvider`(A의 `FallbackProvider`)의 `generate_document(facts=category_facts, tone=tone)`를 한 번씩 호출** (여기서만 12-2절 프롬프트가 카테고리당 1회 렌더링됨 — provider 내부 구현은 [person_A_infra_ai/02_llm_adapter_layer.md](../person_A_infra_ai/02_llm_adapter_layer.md) 참고)
  4. 반환된 `DraftDocument.sentences`(`{text, fact_indices}`)를 `generated_sentences`로 변환: `fact_indices`를 실제 `confirmed_facts.id`로 매핑해 `evidence_fact_ids`(JSONB)에 저장, `category_id` 함께 기록
  5. 각 문장 생성 직후 A의 `check_sentence_consistency()` 호출 → `consistency_check_passed` 채움
- [ ] **세션이나 카테고리 ORM 객체 전체를 `LLMProvider.generate_document()`에 넘기지 않는다** — 오직 그 카테고리의 `confirmed_facts` 리스트와 `tone` 문자열만 전달 (1-2절 정직성 가드레일: 이 경계가 "확정된 사실만 최종 생성 입력이 될 수 있다"는 원칙을 코드로 강제하는 지점이다)

## 2. 문서 생성 API (`api/document.py`, 9-5절)

> 아래 모든 엔드포인트는 [01_auth.md](01_auth.md) 4-1절의 `get_owned_session`으로 먼저 세션 소유권을 확인한다. `{sentence_id}`가 붙는 엔드포인트는 추가로 그 문장이 이 세션의 `generated_documents`에 속하는지 확인한다(다른 세션의 `sentence_id`를 넣으면 `404`) — 그렇지 않으면 사용자가 다른 사람의 문장 ID를 추측해 수정/재생성을 시도할 수 있다.

- [ ] `POST /sessions/{id}/generate` 🔒: `{tone}` → `document_generator.generate_full_document(session_id, tone)` 호출, `generated_documents`+`generated_sentences` insert, 세션 상태 `RESULT_GENERATE`→`RESULT_REVIEW`로 전환
- [ ] `GET /sessions/{id}/document` 🔒: 최신 `generated_documents` + 하위 `generated_sentences` 반환. ⚠️ `evidence_fact_ids`(UUID 배열)를 그대로 내려주면 프론트가 `EvidenceTag`를 그릴 수 없으므로, 각 문장마다 `evidence_fact_ids`를 `confirmed_facts.content`와 A의 `resolve_fact_citation(fact_id)`([person_A_infra_ai/04_record_pipeline.md](../person_A_infra_ai/04_record_pipeline.md) 8번)로 확장해 `evidence: [{fact_id, content, source_type, citation: {source_url, published_at} | null}]` 형태로 응답에 포함시킨다
- [ ] `POST /sessions/{id}/document/regenerate` 🔒: `{tone}` → 새 `version`으로 전체 재생성
- [ ] `PATCH /sessions/{id}/document/sentences/{sentence_id}` 🔒: 세션+문장 소속 확인 후 `{text}` → 사용자가 직접 수정한 문장으로 덮어씀 (이 경로는 재검증 불필요 — 사용자가 직접 쓴 것이므로 이미 "확인됨" 상태)
- [ ] `POST /sessions/{id}/document/sentences/{sentence_id}/regenerate` 🔒: 세션+문장 소속 확인 후 해당 문장만 단건 재생성
- [ ] `POST /sessions/{id}/document/finalize` 🔒: `generated_documents.status='FINALIZED'`
- [ ] `GET /sessions/{id}/export?format=txt` 🔒: 확정된 문서를 텍스트로 내보내기

## 3. 프론트 — 결과 화면 (`frontend/app/sessions/[id]/result/page.tsx`)

- [ ] `EvidenceTag` 컴포넌트: `GET /document` 응답의 `evidence` 배열을 받아 문장별 근거 배지 표시, 클릭 시 `citation`이 있으면 블로그 URL·날짜를, 없으면 "사용자 확인" 표시
- [ ] `consistency_check_passed=false`인 문장은 "확인이 더 필요한 문장"으로 시각적으로 구분 표시 (삭제하지 않고 그대로 보여줌, 12-4절)
- [ ] `ToneSlider` 컴포넌트: 담백/일반/적극 3단계 → 변경 시 `regenerate` 호출
- [ ] 문장 직접 수정 UI (인라인 편집) → `PATCH` 호출
- [ ] 문장 단위 재생성 버튼 → 단건 `regenerate` 호출
- [ ] 최종 확정 버튼 → `finalize` 호출 후 복사/내보내기 버튼 노출

## 검증 기준 (마일스톤 4)

- [ ] 카테고리 여러 개를 끝까지 진행한 뒤 생성했을 때, 각 문장에 출처(근거)가 표시된다
- [ ] confirmed_facts에 없는 내용이 섞인 문장이 나오면 `consistency_check_passed=false`로 표시되고, 화면에서 구분되어 보인다 (자동 삭제되지 않음)
- [ ] 톤을 바꿔 재생성하면 실제로 문장 어조가 달라진다
- [ ] 문장을 직접 수정하고 저장하면 재조회 시 수정된 내용이 유지된다
- [ ] 확정 후 텍스트로 내보내기하면 전체 문서가 그대로 다운로드/복사된다
- [ ] 다른 사용자의 세션 ID, 또는 다른 세션 소속 `sentence_id`로 이 절의 엔드포인트에 접근하면 각각 `403`/`404`가 반환된다
