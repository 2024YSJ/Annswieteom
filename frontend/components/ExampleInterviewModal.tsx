"use client";

import { useEffect, useRef } from "react";
import { ChatBubble } from "@/components/ChatBubble";

/** "커리어 채우기"를 누르기 전에, 실제 대화가 어떻게 흘러가는지 미리 보여주는
 * 예시. ExampleDocumentModal이 "결과가 어떻게 생겼는지"를 보여준다면, 이건
 * "그 결과를 얻으려면 뭘 물어보는지"를 보여준다 — 특히 "딱히 떠오르는 경력이
 * 없어요"라고 답해도 AI가 후속 질문(followup)으로 파고들어 구체화한다는 점이
 * 클릭 전에는 전혀 안 보였다.
 *
 * ExampleDocumentModal과 같은 모달 뼈대(패턴 출처: 그 파일, 원래는
 * app/sessions/layout.tsx의 클릭 아웃사이드 오버레이)를 그대로 쓰고, 본문만
 * InterviewChatThread가 실제 대화에 쓰는 ChatBubble로 교체했다. */
export function ExampleInterviewModal({ onClose }: { onClose: () => void }) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panelRef.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        ref={panelRef}
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="example-qa-title"
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-head">
          <h2 id="example-qa-title">
            <span aria-hidden>💬</span> 이렇게 물어봅니다
          </h2>
          <button type="button" className="modal-close" onClick={onClose} aria-label="예시 닫기">
            ✕
          </button>
        </div>

        <div className="modal-body">
          <p className="modal-lead">떠오르는 게 없어도 괜찮아요. AI가 질문을 이어가며 함께 구체화해요.</p>

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {EXAMPLE_QA.map((turn, index) => (
              <ChatBubble key={index} side={turn.side}>
                {turn.text}
              </ChatBubble>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

const EXAMPLE_QA: { side: "left" | "right"; text: string }[] = [
  { side: "left", text: "이 기간 동안 하신 일이 있다면 편하게 말씀해 주세요. 알바, 공부, 자격증, 혹은 딱히 한 게 없어도 괜찮아요." },
  { side: "right", text: "음... 딱히 한 게 없어요. 그냥 쉬었어요." },
  { side: "left", text: "완전히 손을 놓진 않으셨을 텐데요 — 그 사이 자격증 공부나 짧은 알바, 관심 가는 분야를 찾아본 적은 없으셨나요?" },
  { side: "right", text: "아 맞다, 운전면허 따고 엑셀 자격증도 하나 땄어요." },
  { side: "left", text: "좋아요! 그건 언제 취득하셨고, 취업 준비랑 관련이 있었나요?" },
  { side: "right", text: "2025년 5월에 땄고, 사무직 지원할 때 도움 될 것 같아서 준비했어요." },
];
