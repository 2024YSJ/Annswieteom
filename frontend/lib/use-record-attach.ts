"use client";

import { useEffect, useRef, useState } from "react";
import { recordsApi, type RecordRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import type { ComposerEvent } from "@/components/ChatComposer";

/** Shared "url"/"file" ComposerEvent -> record-create wiring, used by any
 * section that lets the user attach a record — RecordsSection also handles
 * "text" events itself (there, free text means "add a text record"), but a
 * section like InterviewSection where free text means something else (an
 * interview answer) only needs this url/file half.
 */
export function useRecordAttach(
  sessionId: string,
  accessToken: string,
  composerEvent: ComposerEvent | null,
  onAttached: (record: RecordRead) => void,
) {
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const highestNonceRef = useRef(0);

  useEffect(() => {
    if (!composerEvent || composerEvent.kind === "text") return;
    const event = composerEvent;
    const nonce = event.nonce;
    highestNonceRef.current = nonce;

    async function run() {
      setError(null);
      setIsSubmitting(true);
      try {
        const record =
          event.kind === "url"
            ? await recordsApi.createBlogUrl(sessionId, event.value, accessToken)
            : await recordsApi.uploadImage(sessionId, event.file, accessToken);
        if (highestNonceRef.current !== nonce) return;
        onAttached(record);
      } catch (err) {
        if (highestNonceRef.current !== nonce) return;
        setError(errorMessage(err));
      } finally {
        if (highestNonceRef.current === nonce) setIsSubmitting(false);
      }
    }
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [composerEvent?.nonce]);

  return { error, isSubmitting };
}
