import type { SentenceRead } from "@/lib/api-client";

/** 문장 하나가 무엇에 기대고 있는지 한 줄로. "검증 통과"와 "내가 직접 썼음"을
 * 구분하는 게 요점이다 — 서버는 사용자가 고쳐 쓴 문장도
 * consistency_check_passed=true로 두므로(본인이 쓴 말은 정의상 확인된 사실),
 * 그 true를 임베딩 검증 결과처럼 보여주면 거짓말이 된다.
 *
 * ResultSection.tsx의 로컬 함수였던 것을 이 파일로 추출했다 — 원클릭 데모
 * 페이지(app/demo/page.tsx)의 read-only 렌더링도 같은 배지 문구를 써야 하고,
 * 두 곳으로 갈라지면 나중에 한쪽만 고치는 버그가 난다.
 */
export function sentenceBadge(sentence: SentenceRead): string {
  if (sentence.edited_by_user) return "✎ 직접 작성";
  if (sentence.evidence_grade === "record_backed") return "🔗 기록물로 뒷받침됨";
  if (sentence.evidence_grade === "unsupported") return "· 인용된 근거 없음";
  return "· 본인 진술";
}
