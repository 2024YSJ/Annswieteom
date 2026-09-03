# B-3. 기록물 업로드 API + 프론트 UI

근거: 명세서 9-4절, 13절(UI 관점), 14절
선행 조건: [02_interview_state_machine_api.md](02_interview_state_machine_api.md), A의 [04_record_pipeline.md](../person_A_infra_ai/04_record_pipeline.md) (인터페이스 합의 필요)
폴더: `backend/app/api/records.py`, `frontend/app/sessions/[id]/records/`
브랜치: `feature/records-feature` (`dev`에서 분기, 완료 후 `dev`로 PR)
시점: 2주차

## 1. 기록물 API (`api/records.py`, 9-4절)

> 아래 모든 엔드포인트는 [01_auth.md](01_auth.md) 4-1절의 `get_owned_session`으로 먼저 세션 소유권을 확인한다. `{record_id}`가 붙는 엔드포인트는 추가로 그 `record`가 해당 세션 소속인지도 확인한다(다른 세션의 `record_id`를 넣으면 `404`).

- [ ] `POST /sessions/{id}/records` 🔒: 블로그 URL 등록 `{record_type: "blog_url", source_url}` → `records` insert(`parse_status='PENDING'`), `BackgroundTasks`로 A가 노출한 `record_pipeline.process_record(record_id)`([person_A_infra_ai/04_record_pipeline.md](../person_A_infra_ai/04_record_pipeline.md) 참고) 트리거
- [ ] `POST /sessions/{id}/records/upload` 🔒 (multipart): 이미지 업로드 → Supabase Storage에 저장, `storage_path` 기록, `BackgroundTasks`로 `record_pipeline.process_image_record(record_id)` 트리거
- [ ] `POST /sessions/{id}/records/text` 🔒: 텍스트 직접 붙여넣기 → `record_type='pasted_text'`로 즉시 `raw_text` 채움, `BackgroundTasks`로 `record_pipeline.process_record(record_id)` 트리거(내부적으로 파싱 단계는 건너뛰고 청킹·임베딩만 수행됨)
- [ ] `GET /sessions/{id}/records/{record_id}` 🔒: 세션+record 소속 확인 후 `parse_status` 반환 — 폴링용, 프론트가 주기적으로 호출
- [ ] `DELETE /sessions/{id}/records/{record_id}` 🔒: 세션+record 소속 확인 후 기록물 및 하위 chunk 삭제

## 1-1. 이미지 저장 경로 및 접근 권한 (사용자별 데이터 격리)

- [ ] Supabase Storage 업로드 경로를 `records/{user_id}/{session_id}/{record_id}/{filename}` 형태로 사용자·세션별로 분리 — 다른 사용자의 파일과 절대 경로가 겹치지 않게 한다
- [ ] 버킷을 **비공개(private)**로 생성하고, 프론트에 이미지를 보여줄 때는 공개 URL이 아니라 만료 시간이 있는 서명된 URL(signed URL)을 그때그때 발급해서 내려준다 — 업로드 경로를 안다고 다른 사용자가 직접 접근할 수 없도록

## 2. 비동기 파싱 트리거 구조

- [ ] FastAPI `BackgroundTasks`로 위 `process_record`/`process_image_record` 호출을 큐잉 (해커톤 규모이므로 `BackgroundTasks`로 충분 — 복잡한 메시지 큐 도입 불필요)
- [ ] `records.parse_status`를 `DONE`/`FAILED`로 갱신하는 것은 A의 함수 내부에서 처리되므로(위 1번 참고), B는 그 결과를 `GET /records/{record_id}`로 폴링해 보여주기만 하면 된다

## 3. 프론트 — 기록물 업로드 화면 (`frontend/app/sessions/[id]/records/page.tsx`)

- [ ] `RecordUploadPanel` 컴포넌트: URL 입력창 + 이미지 드래그앤드롭 + 텍스트 붙여넣기 탭
- [ ] 등록 후 `GET /records/{record_id}`를 React Query로 폴링(`refetchInterval`)해 `parse_status`가 `DONE`/`FAILED`가 될 때까지 로딩 표시
- [ ] `FAILED` 시 `parse_error` 메시지를 사용자에게 노출 (예: "비공개 게시물은 가져올 수 없어요")
- [ ] 기록물 없이 넘어가기 버튼 → `POST /sessions/{id}/records/skip` 호출

## 검증 기준 (마일스톤 3)

- [ ] 블로그 URL을 등록하면 몇 초 후 `parse_status`가 `DONE`으로 바뀌고 화면에 반영된다
- [ ] 등록한 블로그 URL의 해당 기간 게시물이 이후 [02_interview_state_machine_api.md](02_interview_state_machine_api.md)의 `interview/next` 초안 생성 시(12-1절 `record_excerpts`) 실제로 근거로 반영된다 (13-1절 6번 — 카테고리 라벨로 의미 검색된 조각이 초안 프롬프트에 투입됨)
- [ ] 이미지 업로드 시 OCR 결과가 반영된 청크가 생성된다
- [ ] 잘못된 URL이나 비공개 게시물을 등록했을 때 사용자에게 명확한 에러 메시지가 표시된다
- [ ] 다른 사용자의 세션 ID 또는 다른 세션 소속 `record_id`로 접근하면 각각 `403`/`404`가 반환된다
- [ ] 업로드된 이미지의 Storage 경로를 브라우저 주소창에 그대로 입력해도(로그인 세션 없이) 내용이 보이지 않는다 (비공개 버킷 확인)
