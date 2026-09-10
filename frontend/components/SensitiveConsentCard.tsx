"use client";

import Link from "next/link";
import { useMutation } from "@tanstack/react-query";

import { profileApi, type SensitiveConsent } from "@/lib/api-client";
import { errorMessage } from "@/lib/error-messages";

/** 민감정보(연소득·해당 대상·혼인) 수집 동의.
 *
 * 청년정책 중에는 한부모가정·기초생활수급자·장애인처럼 대상을 좁힌 것이 적지 않다
 * (온통청년 실측 약 13%). 그 조건을 맞춰보려면 정보가 필요하지만, 장애는 법적
 * 민감정보(건강)이고 나머지도 같은 무게라서 **먼저 묻고, 동의한 경우에만 저장한다.**
 * 동의가 없을 때 사용자가 스스로 말하면 값은 버리고 "말씀하셨다"는 표시만 남기는데,
 * 그 표시가 켜져 있으면 이 카드를 강조해 보여준다.
 *
 * 게스트는 동의할 수 없다 — 이메일도 없이 기기에 묶인 임시 계정이라, 기기를 잃으면
 * 맡긴 민감정보를 지울 방법조차 없어진다.
 */
export function SensitiveConsentCard({
  accessToken,
  consent,
  isGuest,
  onChanged,
}: {
  accessToken: string;
  consent: SensitiveConsent;
  isGuest: boolean;
  onChanged: () => void;
}) {
  const update = useMutation({
    mutationFn: (granted: boolean) => profileApi.setSensitiveConsent(granted, accessToken),
    onSuccess: onChanged,
  });

  const mentioned = consent.sensitive_mentioned && !consent.granted;

  return (
    <div className={mentioned ? "consent-card consent-card-alert" : "consent-card"}>
      <strong>
        {consent.granted ? "소득·대상 정보 활용에 동의하셨어요" : "더 정확한 혜택을 찾으려면 몇 가지 여쭤봐도 될까요?"}
      </strong>
      <p style={{ margin: 0 }}>
        연소득, 해당 대상(장애·기초생활수급·한부모가정 등), 혼인 여부는 동의하신 경우에만 저장하고
        청년정책 신청 자격을 맞춰보는 데만 써요. 동의를 철회하면 저장된 정보는 바로 삭제돼요.
      </p>
      {mentioned && (
        <p style={{ margin: 0, fontWeight: 600 }}>
          대화 중에 이런 정보를 말씀하셨는데, 동의가 없어서 저장하지 않았어요.
        </p>
      )}

      {isGuest ? (
        <p style={{ margin: 0, color: "var(--muted-text)" }}>
          회원가입한 계정에서만 동의할 수 있어요. <Link href="/register">회원가입하기</Link>
        </p>
      ) : consent.granted ? (
        <div>
          <button
            type="button"
            className="btn-ghost"
            disabled={update.isPending}
            onClick={() => {
              if (window.confirm("동의를 철회하면 저장된 소득·대상·혼인 정보가 바로 삭제돼요. 철회할까요?")) {
                update.mutate(false);
              }
            }}
          >
            동의 철회
          </button>
        </div>
      ) : (
        <div>
          <button type="button" className="btn-primary" disabled={update.isPending} onClick={() => update.mutate(true)}>
            {update.isPending ? "저장 중..." : "동의하기"}
          </button>
        </div>
      )}
      {consent.granted && (
        <p style={{ margin: 0, fontSize: 12, color: "var(--muted-text)" }}>
          위 &lsquo;항목 선택&rsquo;에서 직접 적거나, 대화 중에 말씀하시면 저장돼요.
        </p>
      )}
      {update.isError && <p className="msg-error">{errorMessage(update.error)}</p>}
    </div>
  );
}
