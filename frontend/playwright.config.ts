import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: 0,
  // 이 스펙들은 전부 한 대의 백엔드(+ 한 대의 Next dev 서버)를 함께 쓴다. 기본값
  // 대로 병렬로 돌리면 그 하나를 두고 경쟁해서, 개별로는 통과하는 테스트가
  // 무작위로 타임아웃한다(실제로 auth/guest/session-flow가 조합에 따라 번갈아
  // 실패했다). 전체가 1.5분이라 병렬로 얻을 게 거의 없으므로 직렬로 고정한다.
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    screenshot: "only-on-failure",
  },
});
