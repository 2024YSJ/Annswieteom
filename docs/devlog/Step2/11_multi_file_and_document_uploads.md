# 38단계 — 기록물 첨부: 다중 파일 + md/txt/docx/hwp 지원

기록물 첨부는 이미지 3종(jpg/png/webp) 하나씩만 받을 수 있었다. 사용자 요청: 한 번에 여러
파일을 올릴 수 있게 하고, md/txt/docx/hwp도 읽을 수 있게 한다.

## 구현

- `records`에 `original_filename` 컬럼 추가(마이그레이션 `b3c4d5e6f7a8`) — storage_path는
  UUID 기반이라 여러 파일을 올렸을 때 목록에서 구분할 방법이 없었다.
- `record_type`에 `"document"` 추가(같은 마이그레이션에서 `ck_records_type` CHECK 제약
  drop/recreate).
- `POST /records/upload`는 여전히 파일 하나씩 받는다 — 여러 개는 **프론트가 선택된 파일마다
  반복 호출**하는 방식으로 처리(백엔드 멀티파트 리스트 처리를 새로 만들지 않음, velog 목록
  가져오기 때 이미 쓰던 "여러 개를 순차 생성 → 프론트가 한 번에 그리기" 패턴 재사용). 파일
  종류 판별은 `content_type` 대신 **확장자**로 한다 — 브라우저가 .md/.hwp에 붙이는
  content_type이 비어있거나 부정확한 경우가 흔하다.
- 새 모듈 `document_parser.py`: `.txt`/`.md`는 UTF-8→CP949→EUC-KR 순으로 디코드,
  `.docx`는 `python-docx`, `.hwp`는 **직접 구현**한 OLE(`olefile`)+zlib+레코드 파서로
  텍스트만 뽑아낸다 — 유지보수되는 hwp 파싱 pip 패키지가 마땅치 않아서(`pyhwp`류는 수년간
  방치) 새 의존성은 `olefile`(가볍고 잘 유지됨) 하나만 추가하고 나머지는 직접 짰다. 배포용
  문서/암호 보호 파일 등은 처리 못 하고 명확한 에러로 넘어간다(범위 밖으로 명시).

## 트러블슈팅

- **로컬 dev 환경에서 실제 스토리지 업로드를 검증할 수 없었다**: `backend/.env`의
  `SUPABASE_URL`이 여전히 `.env.example`의 리터럴 플레이스홀더(`your-project.supabase.co`)였다
  — DNS 조회 자체가 실패한다. pytest는 `FakeStorage`로 이 계층을 모킹하므로 지금까지 한 번도
  드러난 적이 없었다(이번 세션에서 처음으로 실제 curl 업로드를 시도하다가 발견). 이번
  기능의 버그가 아니라 기존부터 있던 로컬 환경 설정 공백 — `GEMINI_API_KEY`/`JWT_SECRET`
  플레이스홀더와 같은 종류의 문제라 메모리에 같이 기록해뒀다.
- **다중 파일 선택 시 업로드가 하나도 안 일어나는 실제 버그**: `handleFileChange`에서
  `event.target.files`(라이브 FileList)를 변수에 담아둔 뒤 `event.target.value = ""`로
  입력을 초기화했는데, 이 초기화가 이미 담아둔 FileList 자체를 그 자리에서 비워버렸다(단일
  파일 버전은 `files?.[0]`로 실제 File 객체를 바로 꺼내와서 이 문제가 없었음). `Array.from()`
  으로 먼저 복사해두는 것으로 고쳤다 — Playwright로 파일 3개를 한 번에 선택해서 업로드
  요청이 실제로 3번 순서대로 나가는 것까지 확인.

## 검증
- `document_parser.py` 유닛 테스트 7개(.txt UTF-8/CP949, .md, 실제 python-docx 왕복,
  깨진 .docx/.hwp 바이트에 대한 에러 처리, 지원 안 하는 확장자) 전부 통과.
- `test_records.py`에 확장자 기반 라우팅 테스트 2개 추가. 백엔드 전체 158개 통과.
- Playwright로 실제 브라우저에서: 파일 입력이 `multiple`을 받는지, 팝오버 라벨이 "파일
  추가"로 통합됐는지, .txt/.md/.png 3개를 한 번에 골랐을 때 실제로 3번 업로드되고 각각
  원래 파일명으로 구분되어 뜨는지 확인(업로드 엔드포인트는 위 스토리지 플레이스홀더 문제
  때문에 모킹).

## 남은 일
- 프로덕션 배포 시 `b3c4d5e6f7a8` 마이그레이션 적용 필요.
- `.hwp` 파서는 최선 노력 수준이다 — 배포용 문서, 암호 보호 파일, HWP 3.0 이하는 처리 못
  함. 실제 사용자 파일로 검증이 안 됐으므로 배포 후 실제 hwp 샘플로 확인이 필요하다.
- 로컬에서 실제 Supabase Storage 업로드를 검증하려면 `SUPABASE_URL`/`SUPABASE_SERVICE_KEY`에
  진짜 값이 필요하다(체크리스트 항목, 이전부터 미완).
