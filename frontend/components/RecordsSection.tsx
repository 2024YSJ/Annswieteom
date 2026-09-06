"use client";

import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { recordsApi, sessionApi, type ActivityCategoryRead, type RecordRead } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { CATEGORY_LABELS } from "@/lib/session-routes";
import { ChatBubble } from "@/components/ChatBubble";
import { RecordStatusRow } from "@/components/RecordStatusRow";
import type { ComposerEvent } from "@/components/ChatComposer";

function categoryLabel(category: ActivityCategoryRead): string {
  return category.custom_label ?? CATEGORY_LABELS[category.category_type];
}

export function RecordsSection({
  sessionId,
  accessToken,
  mode,
  categories,
  currentCategoryId,
  composerEvent,
}: {
  sessionId: string;
  accessToken: string;
  mode: "completed" | "active";
  categories: ActivityCategoryRead[];
  currentCategoryId: string | null;
  composerEvent: ComposerEvent | null;
}) {
  const queryClient = useQueryClient();
  // Records created in this render session, keyed by the category they were
  // requested under — merged with `category.records` (from the backend) so a
  // just-uploaded record shows immediately without waiting for a refetch,
  // while a page reload still shows everything via `category.records`.
  const [newRecordIdsByCategory, setNewRecordIdsByCategory] = useState<Record<string, string[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSkipping, setIsSkipping] = useState(false);
  const highestNonceRef = useRef(0);

  // The record-attach (📎 blog URL / image) control — only relevant here,
  // since records are only attachable during this step (2026-09-06), unlike
  // the shared ChatComposer's free-text box which every step uses.
  const [isAttachMenuOpen, setIsAttachMenuOpen] = useState(false);
  const [isUrlFormOpen, setIsUrlFormOpen] = useState(false);
  const [urlDraft, setUrlDraft] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  function addRecord(record: RecordRead) {
    if (!record.category_id) return;
    setNewRecordIdsByCategory((prev) => ({
      ...prev,
      [record.category_id!]: [...(prev[record.category_id!] ?? []), record.id],
    }));
    queryClient.setQueryData(queryKeys.record(sessionId, record.id), record);
  }

  function addRecords(records: RecordRead[]) {
    records.forEach(addRecord);
  }

  useEffect(() => {
    if (mode !== "active" || !composerEvent) return;
    const nonce = composerEvent.nonce;
    highestNonceRef.current = nonce;

    async function run() {
      setError(null);
      setIsSubmitting(true);
      try {
        const record = await recordsApi.createText(sessionId, composerEvent!.value, accessToken);
        if (highestNonceRef.current !== nonce) return;
        addRecord(record);
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

  if (mode === "completed") {
    return (
      <>
        <ChatBubble side="left">
          카테고리별로 자료가 있으면 알려달라고 요청드렸어요. 없어도 괜찮다고 안내했어요.
        </ChatBubble>
        <ChatBubble side="right">기록물 업로드를 완료했어요.</ChatBubble>
      </>
    );
  }

  async function uploadImage(file: File) {
    setError(null);
    setIsSubmitting(true);
    try {
      const record = await recordsApi.uploadImage(sessionId, file, accessToken);
      addRecord(record);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function submitUrl(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (urlDraft.trim().length === 0) return;
    setError(null);
    setIsSubmitting(true);
    try {
      const records = await recordsApi.createBlogUrl(sessionId, urlDraft, accessToken);
      addRecords(records);
      setUrlDraft("");
      setIsUrlFormOpen(false);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // allow re-selecting the same file later
    setIsAttachMenuOpen(false);
    if (!file) return;
    uploadImage(file);
  }

  async function handleAdvance() {
    setError(null);
    setIsSkipping(true);
    try {
      await sessionApi.skipRecords(sessionId, accessToken);
      await queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsSkipping(false);
    }
  }

  const currentCategory = categories.find((c) => c.id === currentCategoryId);
  if (!currentCategory) return null;

  const visibleCategories = categories
    .slice()
    .sort((a, b) => a.order_index - b.order_index)
    .filter((c) => c.order_index <= currentCategory.order_index);

  function recordIdsFor(category: ActivityCategoryRead): string[] {
    const fromBackend = category.records.map((r) => r.id);
    const fresh = newRecordIdsByCategory[category.id] ?? [];
    return [...fromBackend, ...fresh.filter((id) => !fromBackend.includes(id))];
  }

  const currentRecordIds = recordIdsFor(currentCategory);

  return (
    <>
      {visibleCategories.map((category) => {
        const recordIds = recordIdsFor(category);
        const isCurrent = category.id === currentCategoryId;

        if (!isCurrent) {
          return (
            <div key={category.id} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ fontSize: 13, color: "var(--muted-text)", fontWeight: "bold" }}>
                ▸ {categoryLabel(category)}
              </div>
              {recordIds.length > 0 ? (
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {recordIds.map((id) => (
                    <RecordStatusRow key={id} sessionId={sessionId} recordId={id} accessToken={accessToken} />
                  ))}
                </ul>
              ) : (
                <p style={{ fontSize: 13, color: "var(--muted-text)", margin: 0 }}>자료 없이 넘어감</p>
              )}
            </div>
          );
        }

        return (
          <div key={category.id} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ fontSize: 13, color: "var(--muted-text)", fontWeight: "bold" }}>
              ▸ {categoryLabel(category)}
            </div>
            <ChatBubble side="left">
              <span aria-live="polite">
                {categoryLabel(category)}에 대한 자료(블로그 글, 자격증 이미지, 메모)가 있으면 알려주세요. 없어도 괜찮아요.
              </span>
            </ChatBubble>

            {currentRecordIds.length > 0 && (
              <ChatBubble side="left">
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {currentRecordIds.map((id) => (
                    <RecordStatusRow key={id} sessionId={sessionId} recordId={id} accessToken={accessToken} />
                  ))}
                </ul>
                <p style={{ fontSize: 13, color: "var(--muted-text)", marginTop: 8, marginBottom: 0 }}>
                  모든 자료의 처리가 완료된 후 다음으로 넘어가시기를 권고드립니다.
                </p>
              </ChatBubble>
            )}

            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                const file = e.dataTransfer.files?.[0];
                if (file) uploadImage(file);
              }}
            >
              {error && <p style={{ color: "crimson" }}>{error}</p>}
              <div style={{ display: "flex", gap: 8, alignItems: "center", position: "relative" }}>
                <button type="button" onClick={handleAdvance} disabled={isSkipping || isSubmitting}>
                  {isSkipping ? "진행 중..." : currentRecordIds.length > 0 ? "다음 카테고리로" : "이 카테고리 자료 없이 넘어가기"}
                </button>
                <button
                  type="button"
                  onClick={() => setIsAttachMenuOpen((v) => !v)}
                  disabled={isSubmitting}
                  title="첨부"
                  aria-label="첨부"
                >
                  📎
                </button>

                {isAttachMenuOpen && (
                  <div
                    style={{
                      position: "absolute",
                      bottom: "100%",
                      left: 0,
                      marginBottom: 4,
                      background: "var(--surface-strong)",
                      color: "var(--surface-strong-text)",
                      border: "1px solid var(--border-strong)",
                      borderRadius: 8,
                      padding: 4,
                      display: "flex",
                      flexDirection: "column",
                      zIndex: 1,
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => {
                        setIsUrlFormOpen(true);
                        setIsAttachMenuOpen(false);
                      }}
                    >
                      블로그 URL 추가
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        fileInputRef.current?.click();
                        setIsAttachMenuOpen(false);
                      }}
                    >
                      이미지 추가
                    </button>
                  </div>
                )}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  onChange={handleFileChange}
                  disabled={isSubmitting}
                  style={{ display: "none" }}
                />
              </div>

              {isUrlFormOpen && (
                <form onSubmit={submitUrl} style={{ display: "flex", gap: 8, marginTop: 8 }}>
                  <input
                    type="url"
                    required
                    autoFocus
                    placeholder="https://blog.naver.com/..."
                    value={urlDraft}
                    onChange={(e) => setUrlDraft(e.target.value)}
                    style={{ flex: 1, minWidth: 0 }}
                  />
                  <button type="submit" disabled={isSubmitting}>
                    등록
                  </button>
                  <button type="button" onClick={() => setIsUrlFormOpen(false)}>
                    취소
                  </button>
                </form>
              )}
            </div>
          </div>
        );
      })}
    </>
  );
}
