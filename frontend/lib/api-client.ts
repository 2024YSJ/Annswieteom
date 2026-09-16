// Barrel re-export so existing `import { sessionApi } from "@/lib/api-client"`
// call sites keep working unchanged — the actual implementation now lives
// split by domain under `./api/` (see docs/architecture.md).
export * from "./api/client";
export * from "./api/auth";
export * from "./api/sessions";
export * from "./api/records";
export * from "./api/document";
export * from "./api/feed";
export * from "./api/profile";
export * from "./api/job-search";
export * from "./api/trust";
export * from "./api/demo";
