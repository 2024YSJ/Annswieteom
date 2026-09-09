"use client";

import { usePathname } from "next/navigation";

/** 파비콘(app/icon.png)은 Flaticon 무료 라이선스로 받은 아이콘이라, 쓰는 쪽에서
 * 제작자 표기를 노출하는 게 라이선스 조건이다. 그래서 문서 안 어딘가가 아니라
 * 실제 서비스 화면에 둔다 — layout.tsx에서 렌더된다.
 *
 * 단, 세션 대화 화면에서는 그리지 않는다. 그 화면은 "화면 높이 - 헤더"로 높이를
 * 고정하고 입력창을 바닥에 붙이는데, 그 아래 푸터가 더 붙으면 문서 전체가
 * 뷰포트보다 푸터 높이만큼 길어진다. 그러면 새 메시지로 스크롤할 때 창까지 같이
 * 밀려서 대화 맨 윗부분이 sticky 헤더 뒤로 숨는다. 대신 같은 표기를 세션
 * 사이드바 맨 아래(app/sessions/layout.tsx)에 둬서, 서비스 화면에서도 표기가
 * 사라지지 않게 했다.
 *
 * 목업(docs/design/landing-mockup.html)의 푸터에는 이용약관·문의 같은 링크가
 * 있었지만, 아직 없는 페이지로 가는 죽은 링크를 만들지 않으려고 표기와
 * 저작권 줄만 남겼다. */
export function SiteFooter() {
  const pathname = usePathname();
  if (pathname?.startsWith("/sessions")) return null;

  return (
    <footer
      style={{
        // body가 flex column + min-height 100%라, marginTop: auto면 내용이
        // 짧은 페이지에서도 푸터가 화면 아래에 붙는다.
        marginTop: "auto",
        borderTop: "1px solid var(--border)",
        padding: "28px 24px 44px",
        fontSize: 12.5,
        lineHeight: 1.6,
        color: "var(--muted-text)",
      }}
    >
      <div
        style={{
          maxWidth: 1080,
          margin: "0 auto",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <IconAttribution />
        <span>© {new Date().getFullYear()} 안 쉬었음</span>
      </div>
    </footer>
  );
}

/** 세션 사이드바에서도 같은 표기를 쓰기 때문에 따로 빼뒀다. */
export function IconAttribution() {
  return (
    <span>
      아이콘 제작:{" "}
      <a
        href="https://www.flaticon.com/kr/free-icons/-"
        title="침대가 없다 아이콘"
        target="_blank"
        rel="noopener noreferrer"
        style={{ textDecoration: "underline", textUnderlineOffset: 3 }}
      >
        침대가 없다 아이콘 제작자: juicy_fish - Flaticon
      </a>
    </span>
  );
}
