import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  expect: {
    // 기본 5초로는 로컬에서 다단계 흐름이 못 버틴다. 이 노트북의 dev Supabase는
    // 일부러 프로덕션과 다른 리전(ap-southeast-2, 시드니)에 있어서
    // (00_shared/04_local_dev_environment.md) 요청 하나가 왕복 ~2초씩 걸린다 —
    // `POST /sessions` 단독 2.0초, `/health` 0.2초로 실측했다. 코드가 느린 게
    // 아니라 거리 때문이고, 프로덕션 피드 조회는 1.3초다.
    //
    // 5초로 두면 세션 생성·기간 저장·세션 삭제 단계가 무작위로 터져서 진짜
    // 회귀와 구분이 안 된다(실제로 session-flow/guest/sidebar 3~4개가 계속
    // 빨간 상태였고, 이 설정을 올리기 전까지 `dev`에서도 똑같이 실패했다).
    timeout: 15_000,
  },
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
