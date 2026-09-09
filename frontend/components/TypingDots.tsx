"use client";

/** 메신저식 "입력 중" 말줄임표. AI 응답을 기다리는 모든 채팅 구간이 이걸 쓴다.
 *
 * 예전에는 대기 표시가 세 갈래로 제각각이었다 — 카테고리는 "찾는 중..." 맨텍스트
 * 버블, 인터뷰는 muted span, 취업정보/결과는 LoadingNotice. 게다가 전부 정적
 * 텍스트라 말풍선이 툭 생겼다 툭 사라져서 화면이 끊겨 보였다(2026-09-09 피드백).
 * 점이 계속 움직이면 "멈춘 게 아니라 기다리는 중"이라는 게 눈으로 읽힌다.
 *
 * 애니메이션 자체는 globals.css의 `.typing-dots`에 있다 — 이 저장소의 채팅
 * 컴포넌트는 인라인 스타일 + CSS 변수를 쓰지만 `@keyframes`만은 인라인으로
 * 불가능하고, 그 선례가 `.bubble-tip`/`bubble-bob`이다.
 *
 * label은 화면에도 보이고 스크린 리더에도 읽힌다. 점만 있으면 시각적으로는
 * 충분해도 "무엇을 기다리는 중인지"가 사라진다.
 */
export function TypingDots({ label }: { label?: string }) {
  return (
    <span
      role="status"
      aria-live="polite"
      style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "var(--muted-text)" }}
    >
      {label && <span>{label}</span>}
      <span className="typing-dots" aria-hidden>
        <span className="typing-dot" />
        <span className="typing-dot" />
        <span className="typing-dot" />
      </span>
    </span>
  );
}
