"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { profileApi, type AttributeKey, type ProfileAttribute } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { LoadingNotice } from "@/components/LoadingNotice";
import { SensitiveConsentCard } from "@/components/SensitiveConsentCard";

const STATUS_TEXT: Record<ProfileAttribute["status"], string> = {
  inferred: "대화에서 알게 됐어요",
  confirmed: "확인됨",
  user_edited: "직접 입력",
};

function ValueInput({
  keyInfo,
  value,
  onChange,
}: {
  keyInfo: AttributeKey;
  value: string;
  onChange: (value: string) => void;
}) {
  if (keyInfo.choices.length > 0) {
    return (
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={keyInfo.label}>
        <option value="">선택</option>
        {keyInfo.choices.map((choice) => (
          <option key={choice} value={choice}>
            {choice}
          </option>
        ))}
      </select>
    );
  }
  return (
    <input
      type="text"
      value={value}
      maxLength={60}
      onChange={(e) => onChange(e.target.value)}
      placeholder={keyInfo.key === "birth_year" ? "예) 1999 또는 26살" : "직접 입력"}
      aria-label={keyInfo.label}
    />
  );
}

function AttributeChip({
  attr,
  keyInfo,
  busy,
  onConfirm,
  onDelete,
  onEdit,
}: {
  attr: ProfileAttribute;
  keyInfo: AttributeKey | undefined;
  busy: boolean;
  onConfirm: () => void;
  onDelete: () => void;
  onEdit: (value: string) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);

  if (draft !== null && keyInfo) {
    return (
      <span className="attr-chip">
        <ValueInput keyInfo={keyInfo} value={draft} onChange={setDraft} />
        <button
          type="button"
          className="btn-ghost attr-action"
          disabled={busy || !draft.trim()}
          onClick={() => {
            onEdit(draft.trim());
            setDraft(null);
          }}
        >
          저장
        </button>
        <button type="button" className="btn-ghost attr-action" onClick={() => setDraft(null)}>
          취소
        </button>
      </span>
    );
  }

  return (
    <span className="attr-chip">
      <span className="attr-label">{attr.label}</span>
      <span className={attr.status === "inferred" ? "attr-status attr-status-inferred" : "attr-status"}>
        {STATUS_TEXT[attr.status]}
      </span>
      {attr.status === "inferred" && (
        <button type="button" className="btn-ghost attr-action" disabled={busy} onClick={onConfirm}>
          맞아요
        </button>
      )}
      <button
        type="button"
        className="btn-ghost attr-action"
        disabled={busy}
        // 선택형 값은 목록에 있는 라벨 그대로라 바로 고를 수 있다. 출생연도는
        // "2000년생"으로 보이는데 서버가 숫자만 읽으므로 그대로 둬도 된다.
        onClick={() => setDraft(keyInfo?.choices.includes(attr.label) || !keyInfo?.choices.length ? attr.label : "")}
      >
        수정
      </button>
      <button type="button" className="btn-ghost attr-action attr-action-danger" disabled={busy} onClick={onDelete}>
        삭제
      </button>
      {/* 추정 근거가 된 본인의 말. "어디서 이런 걸 알았지?"에 답이 없으면 추정 저장은
       * 몰래 하는 프로파일링처럼 읽힌다. */}
      {attr.status === "inferred" && attr.evidence_text && (
        <span className="attr-evidence">&ldquo;{attr.evidence_text}&rdquo;에서 알게 됐어요</span>
      )}
    </span>
  );
}

/** 대화로 알게 된 사람 단위 정보(나이·사는 곳·학력·희망 직무 …).
 *
 * 인터뷰·구직 검색·희망사항에서 백그라운드로 추출해 **확인 없이 먼저 저장한다**
 * (2026-09-11 결정: 매번 "저장할까요?"를 물으면 대화가 끊긴다). 그 대가로 여기가
 * 보고, 맞다고 하고, 고치고, 지울 수 있는 곳이어야 한다. 지운 값은 서버가
 * 기억해 두어 다음 대화에서 다시 추정하지 않는다.
 *
 * 이 값은 맞춤 정책·공고 추천에만 쓰이고 공백기 문서(STAR 문장)에는 들어가지
 * 않는다 — 문서는 확인된 사실(confirmed_facts)만 인용한다.
 */
export function ProfileAttributesEditor({ accessToken, isGuest }: { accessToken: string; isGuest: boolean }) {
  const queryClient = useQueryClient();
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.attributes(),
    queryFn: () => profileApi.attributes(accessToken),
    retry: false,
  });

  function refresh() {
    queryClient.invalidateQueries({ queryKey: queryKeys.attributes() });
    // 맞춤 정책·공고 순서가 이 값에 달려 있다.
    queryClient.invalidateQueries({ queryKey: ["feed"] });
  }

  const add = useMutation({
    mutationFn: ({ key, value }: { key: string; value: string }) => profileApi.addAttribute(key, value, accessToken),
    onSuccess: () => {
      setNewValue("");
      refresh();
    },
  });
  const edit = useMutation({
    mutationFn: ({ id, value }: { id: string; value: string }) => profileApi.updateAttribute(id, value, accessToken),
    onSuccess: refresh,
  });
  const confirm = useMutation({
    mutationFn: (id: string) => profileApi.confirmAttribute(id, accessToken),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) => profileApi.deleteAttribute(id, accessToken),
    onSuccess: refresh,
  });

  if (isLoading) return <LoadingNotice label="알게 된 정보를 불러오는 중이에요" />;
  if (error || !data) return <p className="msg-error">{errorMessage(error)}</p>;

  const keyByName = new Map(data.keys.map((k) => [k.key, k]));
  const groups = data.keys
    .map((k) => ({ keyInfo: k, values: data.attributes.filter((a) => a.key === k.key) }))
    .filter((g) => g.values.length > 0);
  const addable = data.keys.filter((k) => !k.sensitive || data.consent.granted);
  const selectedKey = keyByName.get(newKey);
  const busy = add.isPending || edit.isPending || confirm.isPending || remove.isPending;
  const mutationError = add.error ?? edit.error ?? confirm.error ?? remove.error;

  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div>
        <h2 style={{ margin: 0, fontSize: 16 }}>나에 대해 알게 된 정보</h2>
        <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--muted-text)" }}>
          대화 중에 말씀하신 나이·사는 곳·학력 같은 정보를 맞춤 정책과 공고를 고르는 데만 쓰려고 저장해요.
          틀린 건 고치거나 지울 수 있고, 지운 정보는 다시 추정하지 않아요. 공백기 문서에는 쓰이지 않아요.
        </p>
      </div>

      {groups.length === 0 ? (
        <p className="feed-callout" style={{ margin: 0 }}>
          아직 알게 된 정보가 없어요. 대화하면서 자연스럽게 채워지고, 아래에서 직접 적어두셔도 돼요.
        </p>
      ) : (
        <ul className="attr-list">
          {groups.map(({ keyInfo, values }) => (
            <li key={keyInfo.key} className="attr-group">
              <span className="attr-key">{keyInfo.label}</span>
              <div className="attr-values">
                {values.map((attr) => (
                  <AttributeChip
                    key={attr.id}
                    attr={attr}
                    keyInfo={keyByName.get(attr.key)}
                    busy={busy}
                    onConfirm={() => confirm.mutate(attr.id)}
                    onDelete={() => remove.mutate(attr.id)}
                    onEdit={(value) => edit.mutate({ id: attr.id, value })}
                  />
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="attr-add">
        <select
          value={newKey}
          onChange={(e) => {
            setNewKey(e.target.value);
            setNewValue("");
          }}
          aria-label="추가할 항목"
        >
          <option value="">항목 선택</option>
          {addable.map((k) => (
            <option key={k.key} value={k.key}>
              {k.label}
            </option>
          ))}
        </select>
        {selectedKey && <ValueInput keyInfo={selectedKey} value={newValue} onChange={setNewValue} />}
        <button
          type="button"
          className="btn-primary"
          disabled={!selectedKey || !newValue.trim() || busy}
          onClick={() => add.mutate({ key: newKey, value: newValue.trim() })}
        >
          추가
        </button>
      </div>
      {mutationError && <p className="msg-error">{errorMessage(mutationError)}</p>}

      <SensitiveConsentCard accessToken={accessToken} consent={data.consent} isGuest={isGuest} onChanged={refresh} />
    </div>
  );
}
