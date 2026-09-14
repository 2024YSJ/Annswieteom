"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { profileApi } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";
import { queryKeys } from "@/lib/query-keys";
import { LoadingNotice } from "@/components/LoadingNotice";

const MAX_CHARS = 1000;

const PLACEHOLDER =
  "예) 반도체 장비 쪽 일을 찾고 있어요. 경기 남부에서 통근 가능한 곳이면 좋겠고, 신입도 받아주는 곳이면 좋겠어요.";

/** 사용자가 직접 쓰는 "맞춤 정보".
 *
 * 맞춤 공고 정렬은 인터뷰 답변 원문에서만 만들어졌다. 그래서 공백기 정리를
 * 아직 안 한 사용자는 **정렬을 조종할 수단이 전혀 없었다** — 결과가 마음에 안
 * 들어도 인터뷰를 처음부터 하는 것 말고는 방법이 없었다(2026-09-10 요청).
 *
 * 저장 즉시 임베딩을 다시 계산하지는 않는다. 로컬 Ollama 호출이 수 초씩 걸려서
 * 저장 버튼이 그만큼 멈춰 보이기 때문이고, 다음 맞춤 공고 조회가 지문 변화를
 * 감지해 백그라운드로 갱신한다. 그래서 저장 직후 안내에 "다음에 보실 때"라고
 * 적어 둔다 — 바로 안 바뀌는 걸 침묵으로 두면 저장이 안 된 줄 안다.
 */
export function PreferenceEditor({ accessToken }: { accessToken: string }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<string | null>(null);
  const [justSaved, setJustSaved] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.preferences(),
    queryFn: () => profileApi.preferences(accessToken),
    retry: false,
  });

  const save = useMutation({
    mutationFn: (text: string) => profileApi.savePreferences(text, accessToken),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.preferences(), saved);
      // 맞춤 공고를 다시 물어보게 해서, 다음 렌더에 백그라운드 재계산이 걸린다.
      queryClient.invalidateQueries({ queryKey: ["feed"] });
      setJustSaved(true);
    },
  });

  if (isLoading) return <LoadingNotice label="맞춤 정보를 불러오는 중이에요" />;
  if (error) return <p className="msg-error">{errorMessage(error)}</p>;

  // 초안을 effect로 동기화하지 않고 파생시킨다 — draft가 null이면 아직 아무것도
  // 타이핑하지 않았다는 뜻이라 서버 값을 그대로 보여주면 된다. effect로 setState를
  // 하면 렌더 한 번을 더 태우고 lint(react-hooks/set-state-in-effect)에도 걸린다.
  const value = draft ?? data?.wish_text ?? "";
  const dirty = data != null && value.trim() !== data.wish_text.trim();

  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div>
        <h2 style={{ margin: 0, fontSize: 16 }}>맞춤 정보</h2>
        <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--muted-text)" }}>
          어떤 일을 찾고 있는지 적어두시면 맞춤 공고를 그 내용에 맞춰 골라드려요. 커리어 채우기를 아직 안
          하셨어도 괜찮아요.
        </p>
      </div>

      <textarea
        value={value}
        onChange={(e) => {
          setDraft(e.target.value.slice(0, MAX_CHARS));
          setJustSaved(false);
        }}
        placeholder={PLACEHOLDER}
        rows={4}
        aria-label="맞춤 정보"
        style={{ resize: "vertical", width: "100%" }}
      />

      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <button
          type="button"
          className="btn-primary"
          onClick={() => save.mutate(value.trim())}
          disabled={save.isPending || !dirty}
        >
          {save.isPending ? "저장 중..." : "저장"}
        </button>
        <span style={{ fontSize: 12, color: "var(--muted-text)" }}>
          {value.length}/{MAX_CHARS}
        </span>
        {save.isError && <span className="msg-error">{errorMessage(save.error)}</span>}
        {justSaved && !dirty && (
          <span style={{ fontSize: 13, color: "var(--muted-text)" }}>
            저장했어요. 맞춤 공고는 다음에 보실 때 이 내용에 맞춰 정렬돼요.
          </span>
        )}
      </div>
    </div>
  );
}
