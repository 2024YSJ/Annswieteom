import { request } from "./client";
import type { DocumentRead } from "./document";

/** 완전 무인증 — 원클릭 데모 모드. 로그인/게스트 로그인 전혀 거치지 않는다. */
export const demoApi = {
  getDocument: () => request<DocumentRead>("/api/v1/demo/document"),
};
