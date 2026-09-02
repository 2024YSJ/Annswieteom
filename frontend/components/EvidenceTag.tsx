"use client";

import { useState } from "react";
import type { EvidenceRead } from "@/lib/api-client";

const SOURCE_LABELS: Record<EvidenceRead["source_type"], string> = {
  user_confirmed: "사용자 확인",
  user_edited: "사용자 수정",
  record_cited: "기록물 인용",
};

function EvidenceDetail({ evidence }: { evidence: EvidenceRead }) {
  return (
    <div style={{ background: "#fff", border: "1px solid #ddd", borderRadius: 6, padding: 8, fontSize: 13 }}>
      <div style={{ color: "#666" }}>{evidence.content}</div>
      {evidence.citation ? (
        <div style={{ marginTop: 4 }}>
          {evidence.citation.source_url && (
            <a href={evidence.citation.source_url} target="_blank" rel="noopener noreferrer">
              {evidence.citation.source_url}
            </a>
          )}
          {evidence.citation.published_at && <span style={{ color: "#999" }}> ({evidence.citation.published_at})</span>}
        </div>
      ) : (
        <div style={{ marginTop: 4, color: "#999" }}>사용자 확인</div>
      )}
    </div>
  );
}

export function EvidenceTag({ evidence }: { evidence: EvidenceRead[] }) {
  const [openId, setOpenId] = useState<string | null>(null);

  if (evidence.length === 0) return null;

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
      {evidence.map((e) => (
        <div key={e.fact_id}>
          <button
            type="button"
            onClick={() => setOpenId(openId === e.fact_id ? null : e.fact_id)}
            style={{
              fontSize: 11,
              background: e.source_type === "record_cited" ? "#e6f4ea" : "#eef2ff",
              color: e.source_type === "record_cited" ? "#1a7f37" : "#3b4bd6",
              border: "none",
              borderRadius: 999,
              padding: "2px 8px",
              cursor: "pointer",
            }}
          >
            {SOURCE_LABELS[e.source_type]}
          </button>
          {openId === e.fact_id && (
            <div style={{ marginTop: 4 }}>
              <EvidenceDetail evidence={e} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
