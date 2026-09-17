import { ApiError } from "./api-client";

const KNOWN_DETAILS: Record<string, string> = {
  session_not_found: "세션을 찾을 수 없습니다.",
  forbidden: "이 세션에 접근할 권한이 없습니다.",
  invalid_token: "로그인이 만료됐습니다. 다시 로그인해주세요.",
  record_not_found: "기록물을 찾을 수 없습니다.",
  unsupported_file_type: "지원하지 않는 파일 형식이에요 (txt/md/docx/hwp만 가능).",
  document_not_found: "생성된 문서가 없습니다.",
  document_not_finalized: "먼저 문서를 확정해야 내보낼 수 있습니다.",
  unsupported_format: "지원하지 않는 내보내기 형식입니다.",
  sentence_not_found: "문장을 찾을 수 없습니다.",
  no_categories_selected: "먼저 카테고리를 선택해주세요.",
  no_current_category: "진행 중인 카테고리가 없습니다.",
  no_posts_in_period: "이 공백 기간에 해당하는 게시물을 찾지 못했어요. 기간을 확인해주세요.",
  gap_period_missing: "먼저 공백 기간을 설정해주세요.",
  no_pending_question: "먼저 질문을 받아야 답변할 수 있어요. 새로고침 후 다시 시도해주세요.",
  question_not_skippable: "이 질문은 건너뛸 수 없어요. 새로고침 후 다시 시도해주세요.",
  category_review_pending: "확인 화면이 이미 대기 중이에요. 새로고침 후 다시 시도해주세요.",
  no_pending_candidates: "확인할 답변이 없어요. 새로고침 후 다시 시도해주세요.",
  invalid_candidate_index: "확인 중 오류가 발생했어요. 새로고침 후 다시 시도해주세요.",
  llm_unavailable: "AI 서버가 수리 중이예요.",
  invalid_feed_category: "잘못된 분류예요.",
  already_registered: "이미 회원가입된 계정입니다.",
  email_already_exists: "이미 가입된 이메일입니다.",
  unverified_sentences: "근거와 맞지 않는 문장이 남아 있어요. 확인 후 다시 확정해주세요.",
  gap_period_not_set: "먼저 공백 기간을 설정해주세요.",
  range_already_covered: "이미 설명된 기간이에요.",
  range_outside_gap_period: "공백 기간 밖의 구간은 채울 수 없어요.",
  registered_account_required: "이메일로 회원가입한 계정만 이용할 수 있어요.",
  demo_not_configured: "지금은 데모가 준비돼 있지 않아요.",
  demo_document_not_found: "지금은 데모가 준비돼 있지 않아요.",
  category_already_in_progress: "이미 답변을 시작한 활동은 분류를 바꿀 수 없어요.",
  invalid_category_type: "올바르지 않은 활동 종류예요.",
  category_not_found: "활동을 찾을 수 없습니다.",
};

const BY_STATUS: Record<number, string> = {
  400: "잘못된 요청입니다.",
  401: "로그인이 필요합니다.",
  403: "권한이 없습니다.",
  404: "찾을 수 없습니다.",
  409: "지금은 이 작업을 할 수 없습니다. 새로고침 후 다시 시도해주세요.",
  503: "서버가 일시적으로 응답하지 않습니다. 잠시 후 다시 시도해주세요.",
};

export function errorMessage(err: unknown, fallback = "오류가 발생했어요. 잠시 후 다시 시도해주세요."): string {
  if (err instanceof ApiError) {
    return KNOWN_DETAILS[err.detail] ?? BY_STATUS[err.status] ?? fallback;
  }
  // AbortSignal.timeout()은 ApiError가 아니라 name이 "TimeoutError"인
  // DOMException으로 거부되므로 여기서 따로 잡아야 한다 — 안 잡으면 시간
  // 초과가 일반 오류 문구로 뭉개져서 재시도해도 될 상황인지 알 수 없다.
  if (err instanceof Error && (err.name === "TimeoutError" || err.name === "AbortError")) {
    return "응답이 너무 오래 걸려서 중단했어요. 조건을 조금 더 구체적으로 적어서 다시 시도해주세요.";
  }
  return fallback;
}
