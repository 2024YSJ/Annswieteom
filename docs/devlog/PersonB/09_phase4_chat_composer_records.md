# Phase 4. 채팅 입력창 기록물 업로드 devlog

관련 spec: [docs/specs/phase4_chat_composer_records.md](../../specs/phase4_chat_composer_records.md)
날짜: 2026-09-03

---

원래 마일스톤 체크리스트에는 없던 항목이라 대응하는 checklist 파일이 없다. 로드맵(Phase 1~4)의 마지막 단계.

## 완료 항목

- `RecordUploadPanel.tsx`(탭 UI) 삭제, 폴링 표시 부분만 `RecordStatusRow.tsx`로 분리
- `RecordsSection.tsx` 전면 교체 — 텍스트는 입력창+보내기, URL/이미지는 첨부(📎) 버튼 팝오버, 드래그앤드롭 유지
- 백엔드/`recordsApi` 무변경 확인(기존 3개 엔드포인트 그대로 재사용)
- e2e(`session-flow.spec.ts`) 그대로 통과 확인, 실 로컬 Ollama로 텍스트/URL/이미지 세 경로 전부 수동 확인

## 핵심 결정 사항과 이유

**뷰포트 고정 입력창은 채택하지 않음.** 사용자에게 입력창의 정확한 동작(텍스트 보내기=텍스트 기록물 등록, 첨부는 URL/이미지 전용, 진행 버튼은 별개)을 먼저 확인받았고, 배치는 Phase 2/3와 동일하게 섹션 카드 안에 두는 쪽을 택했다 — 진짜 화면 하단 고정 바는 사이드바/헤더와의 레이아웃 조정이 추가로 필요해서 로드맵이 요구하는 범위를 넘어선다고 판단했다.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| 실 브라우저로 이미지 업로드를 확인하다 브라우저 콘솔에 CORS 에러(`No 'Access-Control-Allow-Origin' header`)가 뜨며 실패 | 근본 원인은 CORS가 아니었다 — 로컬 `.env`의 `SUPABASE_URL`이 비어 있어서 백엔드 `storage.upload()`가 빈 URL로 요청을 보내다 `httpx.UnsupportedProtocol` 예외로 죽었고, 그 처리되지 않은 예외 응답엔 CORS 미들웨어가 헤더를 못 붙여서 브라우저엔 CORS 에러로만 보임(실제 원인은 500) | 고칠 대상 아님 — `RecordUploadPanel` 시절에도 완전히 동일한 코드 경로(`recordsApi.uploadImage`)를 탔을 것이므로 Phase 4가 만든 회귀가 아니고, `docs/checklists/person_B_frontend_backend/03_records_feature.md`에 이미 적혀 있던 "Supabase Storage 버킷 미완성" 항목이 그대로 드러난 것. 새 컴포저 UI 자체는 이 실패를 정확히 잡아서(크래시 없이) 화면에 에러로 보여줬다는 것만 확인하고 넘어감 |

## 남은 작업

없음 — Phase 4, 그리고 이걸로 Phase 1~4 로드맵 전체 완료. 이후 UI를 더 바꾸고 싶다면 `docs/specs/phase1~4` 문서들을 참고해서 새 단계를 정의하면 된다. (별개 미완 항목: 로컬/운영 환경의 Supabase Storage 버킷 설정 — 이 devlog가 새로 발견한 게 아니라 기존에 이미 알려진 이슈.)
