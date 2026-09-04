"use client";

import { useEffect, useState } from "react";

const COLD_START_DELAY_MS = 4000;

/** Render's free tier spins the backend down after ~15 minutes idle, and the
 * next request can take up to a minute while it wakes back up. A plain
 * "불러오는 중..." looks stuck/broken during that wait, so once loading has
 * dragged on a few seconds, add a note asking the user to hang on instead of
 * leaving them guessing whether something's wrong. */
export function LoadingNotice({ label = "불러오는 중..." }: { label?: string }) {
  const [showColdStartNotice, setShowColdStartNotice] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setShowColdStartNotice(true), COLD_START_DELAY_MS);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div>
      <p>{label}</p>
      {showColdStartNotice && (
        <p style={{ fontSize: 13, color: "var(--muted-text)", marginTop: 8 }}>
          서버가 잠시 쉬고 있다가 깨어나는 중일 수 있어요. 최대 1분 정도 걸릴 수 있으니 조금만 기다려주세요 🙏
        </p>
      )}
    </div>
  );
}
