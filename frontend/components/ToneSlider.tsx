"use client";

import type { Tone } from "@/lib/api-client";

const TONES: { value: Tone; label: string }[] = [
  { value: "plain", label: "담백" },
  { value: "neutral", label: "일반" },
  { value: "assertive", label: "적극" },
];

export function ToneSlider({ value, onChange, disabled }: { value: Tone; onChange: (tone: Tone) => void; disabled?: boolean }) {
  return (
    <div style={{ display: "flex", gap: 8 }}>
      {TONES.map((t) => (
        <button
          key={t.value}
          type="button"
          disabled={disabled || value === t.value}
          onClick={() => onChange(t.value)}
          style={{ fontWeight: value === t.value ? "bold" : "normal" }}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
