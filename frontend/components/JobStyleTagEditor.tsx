"use client";

import { useState } from "react";

/** 업무 스타일 태그 편집기 — 인라인 수정 + 삭제 + "+ 태그 추가", 완전히
 * 컨트롤드 컴포넌트(값/변경 콜백만 받음). `JobSearchPreferencesSection`(확정
 * 후 재편집)과 `JobSearchInterviewSection`(최초 1회차 대화형 입력)이 같이
 * 쓴다 — 두 컴포넌트 사이에서 실제로 코드를 재사용할 가치가 있는 유일한
 * 조각이라 별도 파일로 뺐다. */
export function JobStyleTagEditor({ tags, onChange }: { tags: string[]; onChange: (tags: string[]) => void }) {
  const [newTag, setNewTag] = useState("");

  function updateTag(index: number, value: string) {
    onChange(tags.map((t, i) => (i === index ? value : t)));
  }

  function removeTag(index: number) {
    onChange(tags.filter((_, i) => i !== index));
  }

  function addTag() {
    const trimmed = newTag.trim();
    if (!trimmed) return;
    onChange([...tags, trimmed]);
    setNewTag("");
  }

  return (
    <div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {tags.map((tag, i) => (
          <div
            key={i}
            style={{ display: "flex", alignItems: "center", gap: 4, background: "var(--hover-surface)", padding: "4px 8px", borderRadius: 999 }}
          >
            <input
              value={tag}
              onChange={(e) => updateTag(i, e.target.value)}
              aria-label="업무 스타일 태그"
              style={{ border: "none", background: "transparent", width: `${Math.max(tag.length, 3)}ch`, fontSize: 13 }}
            />
            <button type="button" onClick={() => removeTag(i)} aria-label="태그 삭제" title="삭제" style={{ fontSize: 11 }}>
              ✕
            </button>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
        <input
          type="text"
          value={newTag}
          placeholder="새 태그"
          onChange={(e) => setNewTag(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              addTag();
            }
          }}
          style={{ fontSize: 13 }}
        />
        <button type="button" onClick={addTag} style={{ fontSize: 13 }}>
          + 태그 추가
        </button>
      </div>
    </div>
  );
}
