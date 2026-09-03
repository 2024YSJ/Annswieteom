# Phase 4 — 채팅 입력창 기록물 업로드

Claude-Desktop형 UI 재설계 로드맵의 마지막 단계. [Phase 3](phase3_ai_category_extraction.md)까지 완료된 뒤, 기록물(블로그 URL·이미지·텍스트) 업로드를 탭+폼으로 나뉜 별도 패널에서 채팅 입력창 + 첨부(클립) 버튼 방식으로 옮긴다. **백엔드는 전혀 안 건드린다** — 기존 `recordsApi` 3개 엔드포인트를 그대로 재사용.

## 목표

1. 입력창에 메모를 적고 "보내기"를 누르면 기존 "텍스트 붙여넣기" 기록물로 등록
2. 첨부(📎) 버튼으로 블로그 URL 또는 이미지를 추가(기존 URL 폼/이미지 드롭존과 동일한 동작, 자리만 이동)
3. `RecordsSection.tsx` 하나만 바뀌고 오케스트레이터·다른 섹션은 무수정

## 범위 결정: 뷰포트 고정 입력창은 채택 안 함

Claude Desktop처럼 화면 맨 아래 고정된 입력창도 고려했지만, 채택하지 않았다. 사이드바 폭·좌상단 `AuthHeader`와의 z-index/여백 조정까지 새로 설계해야 해서 "업로드 방식을 첨부 버튼으로 이동"이라는 로드맵 문구가 요구하는 범위를 넘어선다고 판단했다. 대신 `RecordsSection`의 active 카드 안에(Phase 2/3에서 이미 확립된 "섹션 카드 안에 폼을 넣는" 패턴 그대로) 채팅 입력창 스타일의 컨트롤을 배치했다.

## 컴포넌트 재구성

- `RecordUploadPanel.tsx`(탭 UI 전체)를 삭제하고, 폴링 표시 부분만 `RecordStatusRow.tsx`로 분리해 남겼다 — 이 컴포넌트의 역할이 "업로드 폼 전체"에서 "개별 기록물 상태 한 줄 표시"로 완전히 바뀌어서 이름도 그에 맞게 바꿨다.
- `RecordsSection.tsx`가 텍스트/URL/이미지 등록 로직을 전부 직접 들고 있게 됐다(예전엔 `RecordUploadPanel`에 위임). 첨부 버튼 클릭 시 작은 팝오버로 "블로그 URL 추가"/"이미지 추가"를 고르고, URL은 인라인 폼이 펼쳐지고 이미지는 바로 파일 선택창이 뜬다. 드래그앤드롭으로 이미지를 올리는 것도 그대로 유지했다(컨트롤 영역 전체가 드롭존).
- Phase 2에서 넣었던 `onRecordsChange` 콜백(자식→부모로 기록물 개수를 올려보내던 것)은 삭제 — 이제 `RecordsSection`이 `recordIds`를 직접 들고 있어서 필요 없어졌다.

## 검증 중 발견한 것(버그 아님)

실 로컬 Ollama로 텍스트/URL/이미지 세 경로를 전부 수동으로 확인했다. 텍스트와 URL은 정상 동작했고, 이미지 업로드는 CORS 에러로 실패했다 — 원인을 추적해보니 로컬 개발 `.env`의 `SUPABASE_URL`이 비어 있어서 백엔드의 `storage.upload()`가 빈 URL로 요청을 보내다 처리되지 않은 예외로 죽고, 그 예외 응답에 CORS 헤더가 안 실려서 브라우저엔 CORS 에러로 보인 것이었다. `RecordUploadPanel` 시절에도 완전히 동일한 `recordsApi.uploadImage` 호출을 거쳤을 것이므로 Phase 4가 만든 문제가 아니라, `docs/checklists/person_B_frontend_backend/03_records_feature.md`에 이미 "Supabase Storage 버킷이 아직 실제로 준비 안 됨"이라고 적혀 있던 그 미완 항목이 그대로 드러난 것뿐이다. 새 컴포저 UI 자체는 실패를 정확히 잡아서 화면에 에러 메시지로 보여줬다(크래시 없음) — UI 로직은 의도대로 동작.

## 의도적으로 처리하지 않은 것

- 뷰포트 고정 입력창(위 참고)
- 다른 단계까지 입력창 스타일로 통일하는 것 — Phase 4는 기록물 업로드 한정
- 기록물 삭제 UI 추가(`recordsApi.remove`는 있지만 어느 화면에서도 아직 안 씀)
- 로컬 개발 환경의 Supabase Storage 설정(빈 `SUPABASE_URL`) — 인프라 이슈이고 이미 기존 체크리스트에 기록된 별개 미완 항목

## 로드맵 마무리

Phase 1~4로 계획했던 재설계가 전부 끝났다. 각 단계의 상세 설계는 `docs/specs/phase1_guest_sessions_and_sidebar.md` ~ `phase4_chat_composer_records.md`에, 진행 기록은 `docs/devlog/PersonB/06`~`09`에 남아 있다. 이후 UI를 더 바꾸고 싶다면 이 네 문서를 참고해서 새 단계를 정의하면 된다.
