# 상단 메뉴바 겹침 버그

사용자 리포트: "상단 메뉴가 메뉴바 형태로 나타나지 않아 글자가 그 뒤 요소와 겹침."

## 원인 두 가지가 겹쳐 있었다

1. `AuthHeader.tsx`가 `position: fixed; top: 0; left: 0`만 주고 `width`/`background`가
   없었다 — 콘텐츠 폭 만큼만 좌상단에 떠 있는 상태라 "바" 모양이 아니었고, 배경이 없어
   뒤 콘텐츠 글자와 그대로 겹쳐 보였다. 어떤 페이지도 헤더 높이만큼 위쪽 여백을 확보하지
   않았던 것도 원인 — `.app-sidebar`의 `padding: 80px ...`가 유일한 보정이었는데, 이마저
   대략 짐작한 값이었다.
2. (더 근본 원인) `globals.css`의 `html, body { overflow-x: hidden }`가 `body`에도 걸려
   있었다 — 스펙상 한 축을 `visible`이 아닌 값으로 지정하면 나머지 축(`overflow-y`)이
   `auto`로 강제 승격된다. 그 결과 `body`가 `html`과는 별개의, 자체 스크롤 컨테이너가
   되어버렸다. Next.js의 네비게이션 스크롤 초기화는 `window`/`html` 스크롤만 0으로
   되돌리고 이 안쪽 `body` 스크롤은 건드리지 않는다 — 콘텐츠가 더 긴 페이지에서 스크롤한
   채로 클라이언트 사이드 네비게이션을 하면, 새 페이지에서도 `body`가 예전 스크롤 위치를
   그대로 유지해서 (고정/스티키) 헤더가 화면 밖으로 밀려나는, 재현이 간헐적인 버그였다.

## 수정
- `AuthHeader.tsx`: `position: fixed` → `position: sticky`로 바꿔 문서 흐름 안에 실제
  공간을 차지하게 했다 — 이후 어떤 페이지든 별도 보정 없이 헤더 아래부터 콘텐츠가 시작된다.
  `width: 100%`, `background: var(--background)`, `border-bottom` 추가로 실제 "바" 모양이
  되게 했다.
- `globals.css`: `overflow-x: hidden`을 `html`에만 남기고 `body`에서는 제거 — `body`가
  독립 스크롤 컨테이너가 되는 것을 막아 스크롤 모델을 단일화했다.
- `.app-sidebar`의 옛 `padding: 80px 16px 16px`(고정 헤더 보정용 추측값)를 `padding: 16px`로
  되돌림 — 이제 헤더가 흐름을 차지하므로 불필요.

## 검증
- `tsc --noEmit`, `npm run lint` 클린.
- Playwright로 실제 재현: `document.body.scrollTop`을 강제로 올려놓고 클라이언트 사이드
  네비게이션(Link 클릭)을 했을 때 수정 전에는 헤더가 화면 밖으로 밀려났고, 수정 후에는
  `window.scrollY`가 0으로 정상 리셋되고 헤더가 y=0에 그대로 남는 것 확인.
- 랜딩 페이지, 세션 페이지(데스크톱/모바일 375px)에서 헤더가 겹침 없이 바 형태로 보이는
  것 스크린샷으로 확인.
