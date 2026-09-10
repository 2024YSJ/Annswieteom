"use client";

import { useEffect, useState } from "react";

import { TypingDots } from "@/components/TypingDots";

const COLD_START_DELAY_MS = 4000;

const COLD_START_NOTICE =
  "서버가 잠시 쉬고 있다가 깨어나는 중일 수 있어요. 최대 1분 정도 걸릴 수 있으니 조금만 기다려주세요 🙏";

/** Render's free tier spins the backend down after ~15 minutes idle, and the
 * next request can take up to a minute while it wakes back up. A plain
 * "불러오는 중..." looks stuck/broken during that wait, so once loading has
 * dragged on a few seconds, add a note asking the user to hang on instead of
 * leaving them guessing whether something's wrong.
 *
 * `notice` exists because one caller waits for something else entirely.
 * Document generation calls the LLM once per activity category, and on the
 * DGX Spark one category measured 83s through the tunnel — so a few
 * categories run to several minutes. Telling that user "최대 1분" would be a
 * promise we break every time. The default stays as-is for the other callers,
 * whose wait really is a Render cold start. */
export function LoadingNotice({
  label = "불러오는 중...",
  notice = COLD_START_NOTICE,
}: {
  label?: string;
  notice?: string;
}) {
  const [showColdStartNotice, setShowColdStartNotice] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setShowColdStartNotice(true), COLD_START_DELAY_MS);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div>
      {/* 라벨 자체를 TypingDots에 넘겨 점이 같은 줄에 붙게 한다. 4초 콜드스타트
          안내는 그대로 둔다 — Render 프리티어가 15분 유휴 후 잠드는 실제 문제를
          설명하는 문구이고, 이 컴포넌트를 쓰는 7개 호출부가 그 동작에 의존한다. */}
      <p style={{ margin: 0 }}>
        <TypingDots label={label} />
      </p>
      {showColdStartNotice && (
        <p style={{ fontSize: 13, color: "var(--muted-text)", marginTop: 8 }}>
          {notice}
        </p>
      )}
    </div>
  );
}
