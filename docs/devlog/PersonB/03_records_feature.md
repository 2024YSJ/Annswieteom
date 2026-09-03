# B-3. 기록물 업로드 API devlog

체크리스트: `docs/checklists/person_B_frontend_backend/03_records_feature.md`
날짜: 2026-09-03
브랜치: `feature/records-feature` (`dev`에서 분기)

---

## 완료 항목

- `POST /sessions/{id}/records` (블로그 URL), `POST /sessions/{id}/records/text` (텍스트 붙여넣기), `POST /sessions/{id}/records/upload` (이미지 multipart), `GET /sessions/{id}/records/{record_id}` (폴링), `DELETE /sessions/{id}/records/{record_id}` (`app/api/records.py`)
- 세 생성 엔드포인트 모두 `session.status == "RECORD_UPLOAD"`를 요구(8-2절: 이 액션은 상태를 유지하는 반복 가능 액션이라 `require_simple_transition`이 안 맞아서, 같은 상태를 요구만 하는 `orchestrator.require_status()`를 새로 추가)
- `app/services/storage.py`: Supabase Storage REST API를 `httpx`로 직접 감싼 `SupabaseStorage` (upload/download/delete/create_signed_url) — `supabase` SDK를 새 의존성으로 추가하지 않고 이미 있는 httpx로 처리
- 이미지 업로드 경로를 `records/{user_id}/{session_id}/{record_id}{ext}`로 격리(1-1절), 삭제 시 storage 객체도 best-effort로 함께 삭제
- 허용 확장자 밖 이미지(`image/jpeg`, `image/png`, `image/webp` 외)는 업로드 단계에서 즉시 `400`
- 테스트 7개 추가 (`tests/api/test_records.py`) — 생성/폴링/이미지 격리/상태 위반 409/타인 세션 403·타 세션 record_id 404/삭제 시 storage 정리까지 확인. 전체 스위트 49개 통과

## 핵심 결정 사항과 이유

**A의 record_pipeline과의 인터페이스 두 곳을 고쳤다** (체크리스트가 "인터페이스 합의 필요"라고 표시해둔 지점): 실제로 이 엔드포인트를 연결해보니 두 개의 불일치가 있었다.
1. `records.record_type`의 실제 DB 제약(`app/models/record.py`, 마이그레이션에도 반영됨)은 `('blog_url', 'image', 'text')`인데, A의 `pipeline.py::_fetch_text`는 `record.record_type == "pasted_text"`를 검사하고 있었다 — 명세서 6-7절 표에 있는 옛 이름을 그대로 옮겨써서 실제 스키마와 어긋난 것. 텍스트 붙여넣기 기록물은 영원히 `_fetch_text`의 분기를 못 타고 빈 `source_url`로 블로그 파서 쪽으로 새는 버그였다. `"text"`로 고쳤다.
2. `ocr.py::extract_text_from_image`가 `Path(image_path).read_bytes()`로 **로컬 파일 시스템 경로**를 직접 읽고 있었는데, 이건 Storage를 전혀 안 쓰는 구현이었다(체크리스트 1-1절이 요구하는 비공개 버킷/사용자별 경로 격리와 맞물릴 수 없는 구조). OCR 함수 시그니처를 `(image_bytes: bytes, mime_type: str)`로 바꿔 스토리지 방식과 완전히 분리하고, 실제 바이트를 가져오는 책임은 `pipeline.py::process_image_record`가 `storage.download(record.storage_path)`로 지도록 옮겼다.

**Supabase 공식 SDK 대신 httpx로 Storage REST를 직접 호출**: `requirements.txt`에 이미 httpx가 있고(LLM 어댑터가 씀), Storage REST API 자체가 업로드/다운로드/삭제/서명 URL 발급 네 가지뿐이라 새 SDK를 추가할 이유가 없었다. `get_storage()` DI 훅으로 감싸서(`get_llm_provider`/`get_chunk_search`와 같은 패턴) 테스트에서 `FakeStorage`(인메모리 dict)로 갈아끼울 수 있게 했다 — 실제 Supabase 계정 없이도 전체 업로드→OCR→삭제 흐름을 테스트할 수 있다.

**생성 엔드포인트는 배경 작업 함수를 `Depends()`로 주입받는다** (`get_process_record`/`get_process_image_record`): A의 `process_record`/`process_image_record`는 자체적으로 `AsyncSessionLocal()`을 여는 함수라, `get_db`를 오버라이드해도 백그라운드 작업은 여전히 진짜 `DATABASE_URL`에 붙으려 한다. B-2의 `get_chunk_search`에서 이미 겪은 문제와 같은 패턴이라 같은 해법을 그대로 적용했다.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `app.main` 임포트 자체가 `AssertionError: Status code 204 must not have a response body`로 실패 (records.py를 건드리기 전, `dev` 그대로도 재현됨) | `sessions.py`/`records.py`가 `from __future__ import annotations`를 쓰는 상태에서 `-> None` 리턴 타입을 단 204 라우트가 있으면, FastAPI가 문자열화된 `"None"` 애노테이션을 `typing.ForwardRef`로 평가하는 과정에서 `typing._type_check`가 이를 `NoneType`(클래스, truthy)으로 바꿔버려 "response_model이 있다"고 오판 — 이 정확한 FastAPI/타이핑 상호작용은 이번 세션의 Python 3.13 venv에서만 나타났고, B-2 검증 때는 안 걸렸던 걸로 보인다(버전 조합 차이) | `delete_session`(`sessions.py`)과 `delete_record`(`records.py`) 둘 다 `-> None` 애노테이션을 제거(동작은 동일, 순수 타입 힌트 문제) |
| `test_me_without_token_returns_401` / `test_logout_requires_authentication`이 `403 != 401`로 실패 | `HTTPBearer(auto_error=True)`는 Authorization 헤더가 아예 없을 때 FastAPI가 자체적으로 403을 던진다 — `get_current_user`에 도달하기도 전. 명세서 9-1절은 헤더 누락이든 위조든 구분 없이 401을 요구 | `core/deps.py`: `HTTPBearer(auto_error=False)`로 바꾸고 `credentials is None`일 때 직접 401을 던지도록 수정 |
| `test_delete_record_removes_it_and_its_storage_object`가 `no such table: record_chunks`로 실패 | `Record.chunks` 관계가 `cascade="all, delete-orphan"`이라 레코드 삭제 시 SQLAlchemy가 `record_chunks`를 lazy-load — B-2 devlog의 `records`/`generated_documents` 테이블 문제와 완전히 같은 패턴 | `tests/api/conftest.py`의 `records_client` 픽스처가 만드는 테이블 목록에 `RecordChunk.__table__` 추가 (빈 테이블로 존재하기만 하면 됨, pgvector 컬럼도 SQLite에서 문제없이 생성됨) |
| `pip install -r requirements.txt`가 `google-genai==2.21.0`과 `httpx==0.27.2`의 의존성 충돌로 실패(신규 venv에서 처음부터 재현) | A-3(임베딩 파이프라인, 커밋 `60a1c52`)에서 `google-genai`를 추가할 때 `httpx` 상한을 안 맞춰줌 — `google-genai==2.21.0`은 `httpx>=0.28.1` 요구 | `requirements.txt`의 `httpx` 핀을 `0.28.1`로 올림 |

## 테스트 전략

`tests/api/conftest.py`에 `records_client` 픽스처 추가 — `session_client`와 같은 in-memory SQLite 패턴에 더해 `get_process_record`/`get_process_image_record`/`get_storage`를 페이크로 오버라이드한다. `FakeStorage`는 인메모리 dict라 실제 네트워크 호출이 없고, 페이크 파이프라인 함수는 실제로 DB에 `parse_status="DONE"`을 써서 생성→(가짜)파싱→폴링까지 한 번의 요청-응답 사이클(Starlette TestClient는 BackgroundTasks를 응답 반환 전에 동기 실행) 안에서 검증 가능하다.

## 남은 작업

- 프론트 `frontend/app/sessions/[id]/records/page.tsx` (체크리스트 3절) — 아직 프론트에 로그인/회원가입 화면 외에 세션 플로우 페이지가 하나도 없어서(기간 입력, 카테고리 선택 등), 기록물 업로드 화면만 따로 붙이면 실제 브라우저로 끝까지 눌러볼 수가 없다. `person_B_frontend_backend/05_frontend_routes_components.md`(마일스톤 5)에서 전체 라우트를 한 번에 잡을 때 함께 진행하는 편이 나아 보인다.
- Supabase Storage는 실제 계정/버킷으로 아직 검증 안 함(비공개 버킷 생성, `create_signed_url` 실제 호출) — `SUPABASE_URL`/`SUPABASE_SERVICE_KEY`가 실 `.env`에 있는지 확인하고 실제 이미지 업로드 1건으로 검증 필요
- 이번에 겪은 204/401/httpx 이슈들이 이 세션의 venv(Python 3.13, 여러 버전이 뒤섞여 있던 상태)에 특히 취약했던 것들이라, 다른 팀원 PC에서 `pip install -r requirements.txt`로 새로 설치했을 때도 안전한지 한 번 더 확인하면 좋다.
