import { ApiError } from "./api-client";

const KNOWN_DETAILS: Record<string, string> = {
  session_not_found: "세션을 찾을 수 없습니다.",
  forbidden: "이 세션에 접근할 권한이 없습니다.",
  invalid_token: "로그인이 만료됐습니다. 다시 로그인해주세요.",
  record_not_found: "기록물을 찾을 수 없습니다.",
  unsupported_image_type: "지원하지 않는 이미지 형식입니다 (JPEG/PNG/WEBP만 가능).",
  document_not_found: "생성된 문서가 없습니다.",
  document_not_finalized: "먼저 문서를 확정해야 내보낼 수 있습니다.",
  unsupported_format: "지원하지 않는 내보내기 형식입니다.",
  sentence_not_found: "문장을 찾을 수 없습니다.",
  no_categories_selected: "먼저 카테고리를 선택해주세요.",
  no_current_category: "진행 중인 카테고리가 없습니다.",
  no_posts_in_period: "이 공백 기간에 해당하는 게시물을 찾지 못했어요. 기간을 확인해주세요.",
  gap_period_missing: "먼저 공백 기간을 설정해주세요.",
  no_pending_question: "먼저 질문을 받아야 답변할 수 있어요. 새로고침 후 다시 시도해주세요.",
  no_pending_candidates: "확인할 답변이 없어요. 새로고침 후 다시 시도해주세요.",
  invalid_candidate_index: "확인 중 오류가 발생했어요. 새로고침 후 다시 시도해주세요.",
  llm_unavailable: "AI 서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.",
  worknet_unavailable: "채용정보를 가져오지 못했습니다. 잠시 후 다시 시도해주세요.",
  guest_session_limit_reached: "비회원은 세션을 1개까지만 만들 수 있어요. 회원가입하면 계속 이어서 쓸 수 있습니다.",
  already_registered: "이미 회원가입된 계정입니다.",
  email_already_exists: "이미 가입된 이메일입니다.",
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
  return fallback;
}
