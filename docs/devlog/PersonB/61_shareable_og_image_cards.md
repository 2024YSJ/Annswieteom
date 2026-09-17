# 61. 공유 가능한 OG 이미지 카드 (2026-09-16)

투표/바이럴을 위해 완성된 문서를 카카오톡/슬랙 등에 링크로 공유했을 때
브랜드 카드로 미리보기가 뜨도록 하는 기능.

## 무엇을

- `POST`/`DELETE /sessions/{id}/document/share` (소유자 전용, `FINAL` 문서만) —
  `generated_documents`에 짧은 불투명 `share_slug`를 발급/폐기
  (마이그레이션 `6fa82e770439`, nullable+unique — 대부분의 문서는 공유되지
  않으므로).
- `GET /api/v1/share/{slug}` — 완전 무인증, `SharePreviewRead`는 톤 + 대표
  문장 1~2개 + 근거등급 요약 카운트만 반환. 구조적으로
  session_id/user_id/인용 URL을 담을 필드 자체가 없어서 "가릴 것"이 애초에
  없다(스키마 설계로 유출 원천 차단).
- `services/share_preview.py`: 대표 문장 선정은 `record_backed`를
  `self_reported`보다 우선하고, `unsupported`(근거 없음) 문장은 절대
  대표작으로 뽑지 않음 — 공유 카드는 정직성 가드레일이 "얼마나 잘
  근거를 대는지"를 보여주는 용도지, 가드레일이 잡아낸 예외 케이스를
  앞세우는 자리가 아니라는 판단(문서 본문 화면에서는 그대로 노출됨).
- 프론트: 공개 읽기 전용 `/share/[slug]` 페이지 + 동적
  `opengraph-image.tsx`(`next/og`의 `ImageResponse`)로 링크 미리보기 이미지
  생성. Satori 내장 폰트에 한글 글리프가 없어서 첫 요청 시 Google Fonts에서
  Noto Sans KR을 받아 모듈 스코프에 캐시 — 페치 실패 시 500 대신 폰트 없는
  렌더링으로 완화.

## 검증

- `backend/tests/api/test_share.py` 신규(68줄)
- `next build`로 동적 라우트 등록 확인 후, 실제 프로덕션 서버를 실제 dev DB에
  붙여 `GET /api/v1/share/{slug}` 응답 형태와 OG 이미지 라우트가 실제
  1200x630 PNG(한글 정상 렌더링 포함)를 반환하는지 확인
- 마이그레이션 upgrade/downgrade/upgrade 사이클을 dev DB에 대해 검증

## 남은 작업

- [ ] 배포된 사이트에서 실제 공유 링크를 카카오톡/슬랙에 붙여 미리보기
      카드가 실제로 렌더링되는지 확인 (로컬 `next build`/서버 검증만 마침,
      메신저 언퍼얼링 자체는 미확인)

## 관련 커밋

- `c28f111` feat: add shareable OG-image cards for finalized documents (voting/virality)
