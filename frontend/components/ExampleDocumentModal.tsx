"use client";

import { useEffect, useRef } from "react";

/** 결과물이 어떻게 생겼는지 먼저 보여주는 예시. 실제 생성 문서를 그대로 옮긴 게
 * 아니라 예시 텍스트지만, 구조(STAR 4단락 + 문장별 근거 태그)와 근거 태그의
 * 종류는 실제 confirmed_facts.source_type 세 가지와 일치시켰다.
 *
 * 2026-09-10까지는 랜딩 맨 아래 섹션이었다. 거기서는 세션이 없는 방문자에게만,
 * 그것도 피드 세 개를 다 지나친 뒤에야 나왔다 — 정작 "공백기 채우기를 누를까"를
 * 정하는 순간에는 안 보였다. 그래서 그 카드 옆 버튼이 여는 모달로 옮겼다.
 *
 * 이 앱의 첫 모달이라 라이브러리 없이 직접 만든다(패턴 출처:
 * app/sessions/layout.tsx의 클릭 아웃사이드 오버레이). 대신 키보드/스크린리더
 * 사용자가 갇히지 않게 Escape 닫기와 포커스 이동은 직접 처리한다. */
export function ExampleDocumentModal({ onClose }: { onClose: () => void }) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // 열릴 때 포커스를 패널로 옮긴다 — 안 그러면 스크린리더가 계속 랜딩
    // 페이지를 읽고 있어서 모달이 열린 줄 모른다. 닫을 때 트리거 버튼으로
    // 되돌리는 건 호출부(page.tsx)가 한다.
    panelRef.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);

    // 뒤 페이지가 같이 스크롤되면 모달을 닫았을 때 엉뚱한 위치에 가 있다.
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      {/* 패널 안쪽 클릭이 배경까지 올라가면 문서를 읽으려고 누른 순간 닫힌다. */}
      <div
        ref={panelRef}
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="example-doc-title"
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-head">
          <h2 id="example-doc-title">
            <span aria-hidden>📄</span> 이렇게 만들어집니다
          </h2>
          <button type="button" className="modal-close" onClick={onClose} aria-label="예시 닫기">
            ✕
          </button>
        </div>

        <div className="modal-body">
          <p className="modal-lead">모든 문장에 근거가 붙습니다.</p>

          <article className="doc-preview">
            <div className="doc-bar">
              <span className="doc-bar-title">데이터 분석 직무 경력기술서 — 2025.03 ~ 2025.09</span>
              <span className="doc-bar-meta">TONE: 담백 · v2</span>
            </div>

            <div className="doc-body">
              {EXAMPLE_STAR.map((block) => (
                <div key={block.label} className="doc-star">
                  <span className="doc-star-label">{block.label}</span>
                  <p>{block.text}</p>
                  <div className="doc-evidence">
                    {block.evidence.map((e) => (
                      <span key={e.text} className={e.cited ? "chip chip-cite" : "chip"}>
                        {e.text}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <div className="doc-foot">
              <span aria-hidden>🔒</span>
              <span>
                <b>없는 경력은 만들지 않습니다.</b> 직접 &ldquo;맞다&rdquo;고 확인한 사실에만 문장이 붙습니다.
              </span>
            </div>
          </article>
        </div>
      </div>
    </div>
  );
}

const EXAMPLE_STAR = [
  {
    label: "Situation",
    text: "퇴사 후 6개월간 데이터 분석 직무로의 전환을 준비하며, 통계와 SQL 기초를 처음부터 다시 쌓아야 하는 상황이었습니다.",
    evidence: [
      { text: "사용자 확인 · 공백기 6개월", cited: false },
      { text: "사용자 확인 · 직무 전환 목표", cited: false },
    ],
  },
  {
    label: "Task",
    text: "실무에서 바로 쓸 수 있는 수준까지 SQL·Python 분석 역량을 끌어올리고, 결과물을 외부에 공개해 검증받는 것을 목표로 삼았습니다.",
    evidence: [{ text: "사용자 확인 · 학습 목표", cited: false }],
  },
  {
    label: "Action",
    text: "매주 공공데이터를 하나씩 골라 분석 노트를 작성해 블로그에 21편을 연재했고, SQLD 자격증을 취득했으며, 스터디 5인의 코드 리뷰를 진행했습니다.",
    evidence: [
      { text: "기록물 인용 · 블로그 21편", cited: true },
      { text: "기록물 인용 · SQLD 합격증", cited: true },
      { text: "사용자 확인 · 스터디 운영", cited: false },
    ],
  },
  {
    label: "Result",
    text: "연재 글의 누적 조회수는 1만 2천 회를 넘었고, 마지막 프로젝트는 실제 지원 포트폴리오로 제출해 서류 전형을 통과했습니다.",
    evidence: [
      { text: "기록물 인용 · 블로그 통계", cited: true },
      { text: "사용자 수정 · 서류 통과", cited: false },
    ],
  },
];
