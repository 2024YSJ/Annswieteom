"use client";

import { useState } from "react";
import type { ActivityCategoryRead, BasedOnRead, ConfirmedFactRead, FactCandidateRead } from "@/lib/api-client";
import { CATEGORY_LABELS } from "@/lib/session-routes";
import { ChatBubble } from "@/components/ChatBubble";
import { TypingDots } from "@/components/TypingDots";

/** One answer can be split into several confirmed facts (extract_facts found
 * more than one thing in it) — grouping consecutive facts that share the same
 * source question avoids repeating the question bubble once per fact, which
 * otherwise reads as the interview asking the same question over and over
 * (reported as looking like a bug, 2026-09-05). */
function groupFactsByQuestion(facts: ConfirmedFactRead[]): { questionText: string; facts: ConfirmedFactRead[] }[] {
  const sorted = facts.slice().sort((a, b) => a.created_at.localeCompare(b.created_at));
  const groups: { questionText: string; facts: ConfirmedFactRead[] }[] = [];
  for (const fact of sorted) {
    const questionText = fact.source_question_text ?? "질문";
    const lastGroup = groups[groups.length - 1];
    if (lastGroup && lastGroup.questionText === questionText) {
      lastGroup.facts.push(fact);
    } else {
      groups.push({ questionText, facts: [fact] });
    }
  }
  return groups;
}

function BasedOnBadge({ basedOn }: { basedOn: BasedOnRead }) {
  if (basedOn.type === "record") {
    return (
      <span style={{ fontSize: 12, background: "var(--cite-surface)", color: "var(--cite-text)", padding: "2px 8px", borderRadius: 999 }}>
        📎 내 기록물 근거 ({basedOn.excerpts.length}건)
      </span>
    );
  }
  return null;
}

export interface CandidateDraft {
  candidate: FactCandidateRead;
  finalText: string;
  wasEdited: boolean;
  include: boolean;
  /** True for a row the user added themselves (2026-09-06) — the AI's
   * original candidate list may have missed an item (e.g. splitting "공모전"
   * into sub-activities), and excluding rows alone can never grow the count
   * back up, only shrink it. Starts the row in edit mode since there's no
   * AI-drafted text to show. */
  isManual?: boolean;
}

/** 카테고리 끝 확인(2026-09-11)의 화면 상태 — 질문별 묶음마다 편집 가능한 행들. */
export interface CategoryReviewDraft {
  categoryId: string;
  categoryLabel: string;
  groups: {
    turnId: string;
    questionText: string;
    answerText: string;
    factType: string;
    rows: CandidateDraft[];
  }[];
}

type RowPatch = Partial<Omit<CandidateDraft, "candidate">>;

export function InterviewChatThread({
  categories,
  currentCategoryId,
  questionText,
  pendingAnswerText,
  candidates,
  onUpdateCandidate,
  onAddCandidate,
  onSubmit,
  review,
  onUpdateReviewRow,
  onAddReviewRow,
  onSubmitReview,
  isSubmitting,
  isWaitingForAnswer,
}: {
  categories: ActivityCategoryRead[];
  currentCategoryId: string | null;
  questionText: string | null;
  /** The answer just sent, echoed immediately (before the server round-trip
   * finishes) so sending never looks like the input vanished — cleared once
   * candidates take over, but left in place if the request errors. */
  pendingAnswerText?: string | null;
  /** "여러 활동 있나요?" 구조 질문의 즉시 확인 카드 — 일반 답변에는 쓰이지 않는다. */
  candidates: CandidateDraft[] | null;
  onUpdateCandidate: (index: number, patch: RowPatch) => void;
  /** Appends a new, empty, user-authored row to the review list — the only
   * way to grow the list beyond what the AI proposed (excluding a row can
   * only shrink it). */
  onAddCandidate: () => void;
  onSubmit: () => void;
  review: CategoryReviewDraft | null;
  onUpdateReviewRow: (groupIndex: number, rowIndex: number, patch: RowPatch) => void;
  onAddReviewRow: (groupIndex: number) => void;
  onSubmitReview: () => void;
  isSubmitting: boolean;
  /** True while the just-submitted answer is being processed by the AI —
   * local models can take a while, so this renders a visible "생각 중" bubble
   * instead of leaving the question looking frozen. */
  isWaitingForAnswer?: boolean;
}) {
  // A category the interview split into sub-categories (parent_category_id
  // on some other row points at it) becomes a container — it's never
  // interviewed directly (see interview_confirm's activity_breakdown branch),
  // so it never has confirmed_facts of its own and must be hidden even if it
  // briefly matches currentCategoryId right at the split.
  const parentIds = new Set(categories.map((c) => c.parent_category_id).filter((id): id is string => id !== null));

  function sortKey(c: ActivityCategoryRead): [number, number] {
    if (!c.parent_category_id) return [c.order_index, -1];
    const parent = categories.find((p) => p.id === c.parent_category_id);
    return [parent?.order_index ?? c.order_index, c.order_index];
  }

  // Only categories that have at least one confirmed fact or answered turn,
  // or are the one currently being interviewed, are shown — categories not
  // reached yet stay invisible (the AI doesn't preview future questions).
  const visibleCategories = categories
    .filter((c) => !parentIds.has(c.id))
    .slice()
    .sort((a, b) => {
      const [aParent, aOwn] = sortKey(a);
      const [bParent, bOwn] = sortKey(b);
      return aParent - bParent || aOwn - bOwn;
    })
    .filter((c) => c.confirmed_facts.length > 0 || (c.draft_turns ?? []).length > 0 || c.id === currentCategoryId);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {visibleCategories.map((category) => (
        <div key={category.id} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ fontSize: 13, color: "var(--muted-text)", fontWeight: "bold" }}>
            ▸ {category.custom_label ?? CATEGORY_LABELS[category.category_type]}
          </div>
          {groupFactsByQuestion(category.confirmed_facts).map((group) => (
            <div key={group.facts[0].id} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <ChatBubble side="left">{group.questionText}</ChatBubble>
              {group.facts.map((fact) => (
                <ChatBubble key={fact.id} side="right" label="확인됨">
                  {fact.content}
                </ChatBubble>
              ))}
            </div>
          ))}

          {/* 답했지만 아직 카테고리 끝 확인 전인 턴 — 대화 기록일 뿐 "확인됨"이 아니다. */}
          {(category.draft_turns ?? []).map((turn) => (
            <div key={turn.turn_id} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <ChatBubble side="left">{turn.question_text}</ChatBubble>
              {turn.answer_text && <ChatBubble side="right">{turn.answer_text}</ChatBubble>}
            </div>
          ))}

          {review && review.categoryId === category.id && (
            <CategoryReviewCard
              review={review}
              onUpdateRow={onUpdateReviewRow}
              onAddRow={onAddReviewRow}
              onSubmit={onSubmitReview}
              isSubmitting={isSubmitting}
            />
          )}

          {category.id === currentCategoryId && questionText && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }} aria-live="polite">
              <ChatBubble side="left">{questionText}</ChatBubble>

              {pendingAnswerText && <ChatBubble side="right">{pendingAnswerText}</ChatBubble>}

              {isWaitingForAnswer && (
                <ChatBubble side="left">
                  <TypingDots label="답변을 정리하고 다음 질문을 준비하고 있어요" />
                </ChatBubble>
              )}

              {candidates !== null && (
                <>
                  {candidates.length === 0 && (
                    <p style={{ fontSize: 13, color: "var(--muted-text)" }}>
                      이 답변에서는 특별히 뽑아낼 내용이 없었어요. 그냥 다음으로 넘어가거나, 다시 답해 주세요.
                    </p>
                  )}
                  {candidates.map((draft, index) => (
                    <CandidateRow
                      key={index}
                      index={index}
                      draft={draft}
                      onUpdate={(patch) => onUpdateCandidate(index, patch)}
                    />
                  ))}
                  <div style={{ display: "flex", gap: 8 }}>
                    <button type="button" disabled={isSubmitting} onClick={onAddCandidate} style={{ fontSize: 13 }}>
                      + 새 항목 추가
                    </button>
                    <button type="button" disabled={isSubmitting} onClick={onSubmit}>
                      다음
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/** 카테고리 질문이 끝나면 한 번 보여주는 종합 확인 — 질문별로 뽑은 사실을 고치고·빼고·
 * 더한 뒤 "모두 맞아요, 다음으로" 한 번으로 확정한다. 사실이 하나도 안 뽑힌 질문도
 * 묶음은 보여줘서 직접 추가할 수 있게 한다. */
function CategoryReviewCard({
  review,
  onUpdateRow,
  onAddRow,
  onSubmit,
  isSubmitting,
}: {
  review: CategoryReviewDraft;
  onUpdateRow: (groupIndex: number, rowIndex: number, patch: RowPatch) => void;
  onAddRow: (groupIndex: number) => void;
  onSubmit: () => void;
  isSubmitting: boolean;
}) {
  return (
    <div
      aria-live="polite"
      style={{ display: "flex", flexDirection: "column", gap: 16, border: "1px solid var(--border)", borderRadius: 12, padding: 16 }}
    >
      <div>
        <p style={{ margin: 0, fontWeight: "bold" }}>{review.categoryLabel}에서 정리한 내용이에요</p>
        <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--muted-text)" }}>
          맞는지 확인해 주세요. 확인한 내용만 문서에 쓰여요. 틀린 건 고쳐 쓰고, 빼고 싶은 건 제외하세요.
        </p>
      </div>

      {review.groups.map((group, groupIndex) => (
        <div key={group.turnId} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <p style={{ margin: 0, fontSize: 13, color: "var(--muted-text)" }}>Q. {group.questionText}</p>
          {group.rows.length === 0 && (
            <p style={{ margin: 0, fontSize: 13, color: "var(--muted-text)" }}>
              이 답변에서는 정리된 내용이 없어요. 필요하면 직접 추가해 주세요.
            </p>
          )}
          {group.rows.map((row, rowIndex) => (
            <CandidateRow
              key={rowIndex}
              index={rowIndex}
              draft={row}
              onUpdate={(patch) => onUpdateRow(groupIndex, rowIndex, patch)}
            />
          ))}
          <div>
            <button type="button" disabled={isSubmitting} onClick={() => onAddRow(groupIndex)} style={{ fontSize: 13 }}>
              + 항목 추가
            </button>
          </div>
        </div>
      ))}

      <div>
        <button type="button" disabled={isSubmitting} onClick={onSubmit}>
          모두 맞아요, 다음으로
        </button>
      </div>
    </div>
  );
}

function CandidateRow({
  draft,
  onUpdate,
}: {
  index: number;
  draft: CandidateDraft;
  onUpdate: (patch: Partial<Omit<CandidateDraft, "candidate">>) => void;
}) {
  // A freshly-added manual row starts empty with nothing sensible to display
  // read-only, so it opens straight into edit mode instead of showing a
  // blank paragraph the user would have to know to click "고쳐 쓰기" on.
  const [isEditing, setIsEditing] = useState(draft.isManual === true);
  const [editText, setEditText] = useState(draft.finalText);

  // Reset the edit box whenever this row's underlying candidate text changes
  // externally (a new question's candidate reusing the same row index) —
  // "adjust state during render" instead of an effect, same idiom this
  // component used previously for resetting the single-draft edit box.
  const [lastSeenText, setLastSeenText] = useState(draft.finalText);
  if (draft.finalText !== lastSeenText) {
    setLastSeenText(draft.finalText);
    setEditText(draft.finalText);
  }

  return (
    <div
      style={{
        background: "var(--surface)",
        color: "var(--surface-text)",
        padding: 12,
        borderRadius: 12,
        opacity: draft.include ? 1 : 0.5,
      }}
    >
      <div style={{ marginBottom: 8, display: "flex", gap: 8, alignItems: "center" }}>
        <BasedOnBadge basedOn={draft.candidate.based_on} />
      </div>
      {isEditing ? (
        <textarea
          rows={3}
          value={editText}
          onChange={(e) => setEditText(e.target.value)}
          placeholder={draft.isManual ? "내용을 입력하세요" : undefined}
          style={{ width: "100%" }}
        />
      ) : (
        <p style={{ margin: 0 }}>{draft.finalText}</p>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        {isEditing ? (
          <button
            type="button"
            disabled={editText.trim().length === 0}
            onClick={() => {
              onUpdate({ finalText: editText, wasEdited: true, include: true });
              setIsEditing(false);
            }}
          >
            수정 완료
          </button>
        ) : (
          <>
            <button type="button" onClick={() => setIsEditing(true)}>
              고쳐 쓰기
            </button>
            <button type="button" onClick={() => onUpdate({ include: !draft.include })}>
              {draft.include ? "제외하기" : "포함하기"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
