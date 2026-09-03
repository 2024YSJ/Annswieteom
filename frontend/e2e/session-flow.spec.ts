import { test, expect } from "@playwright/test";

function uniqueEmail(): string {
  return `e2e-flow-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

/**
 * Drives the unified /sessions/{id} chat page — now with a single shared
 * ChatComposer for period/categories/records — through period -> categories
 * -> records(skip) -> arrival at the interview section, all against the real
 * local backend/DB (none of these calls touch an LLM, so this part is
 * deterministic without a local Ollama/Gemini running).
 *
 * The two LLM-touching calls in this range, `POST period/extract` and
 * `POST categories/extract`, are mocked — but the test stops before clicking
 * "확인" on the interview draft. Confirming a fact would call the *real*
 * `interview/confirm`, which requires a real `pending_draft` row that only a
 * real (unmocked) `interview/next` call would have written server-side; since
 * that call is mocked here, the DB was never actually transitioned, and a
 * real confirm would 409. Simulating the rest of the loop by *also* mocking
 * `GET /sessions/{id}` was considered and rejected: every mutation in this
 * app re-syncs state via `invalidateQueries` on that same real endpoint, so
 * driving the UI forward this way would mean reimplementing the whole state
 * machine as a second, unverified copy inside the test. The state machine
 * itself is already thoroughly covered by the backend's own pytest suite
 * (unchanged in this phase) — this test's job is only to prove the new
 * unified-page wiring is correct, not to re-prove backend logic.
 *
 * `period/extract` and `categories/extract` never mutate session state
 * server-side (nothing is persisted until the real, unmocked POST
 * /period / POST /categories calls below), so mocking them doesn't risk
 * desyncing real vs. mocked state the way mocking interview/next would.
 */
test.describe("unified session chat flow", () => {
  test("period -> categories -> records -> interview section, on one URL", async ({ page }) => {
    const email = uniqueEmail();
    const password = "password123";

    await page.route("**/api/v1/sessions/*/period/extract", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ start_date: "2024-01-01", end_date: "2024-06-30" }),
      }),
    );

    await page.route("**/api/v1/sessions/*/categories/extract", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ suggestions: [{ category_type: "part_time", custom_label: "아르바이트" }] }),
      }),
    );

    await page.route("**/api/v1/sessions/*/interview/next", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          step: "FREQ_DRAFT",
          category_id: "00000000-0000-0000-0000-000000000000",
          ai_draft: "이 활동을 주 3회 정도 하신 것으로 보여요.",
          based_on: { type: "generic_pattern", excerpts: [] },
        }),
      }),
    );

    await page.goto("/register");
    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("닉네임").fill("Flow Tester");
    await page.getByLabel("비밀번호 (8자 이상)").fill(password);
    await page.getByRole("button", { name: "가입하기" }).click();
    await expect(page).toHaveURL(/\/login$/);

    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("비밀번호").fill(password);
    await page.getByRole("button", { name: "로그인" }).click();
    await expect(page).toHaveURL(/\/$/);

    await page.getByRole("button", { name: "새로 시작하기" }).click();
    await expect(page).toHaveURL(/\/sessions\/[^/]+$/);

    const composerInput = page.getByPlaceholder("메시지를 입력하세요");

    // --- Period section (active) ---
    await expect(page.getByText("공백기가 언제부터 언제까지였나요?", { exact: false })).toBeVisible();
    await composerInput.fill("작년 1월부터 6월까지요");
    await page.getByRole("button", { name: "보내기" }).click();
    await expect(page.getByText("다음 기간으로 이해했어요: 2024-01-01 ~ 2024-06-30", { exact: false })).toBeVisible();
    await page.getByRole("button", { name: "확인" }).click();

    // --- Period completed, Category section (active) ---
    await expect(page.getByText("공백기: 2024-01-01 ~ 2024-06-30")).toBeVisible();
    await composerInput.fill("편의점에서 6개월 정도 아르바이트를 했어요.");
    await page.getByRole("button", { name: "보내기" }).click();
    await expect(page.locator('input[type="text"]').first()).toHaveValue("아르바이트");
    await page.getByRole("button", { name: "확인" }).click();

    // --- Category completed, Records section (active) ---
    await expect(page.getByText("선택한 활동: 아르바이트")).toBeVisible();
    await expect(page.getByRole("button", { name: "기록물 없이 넘어가기" })).toBeVisible();
    await page.getByRole("button", { name: "기록물 없이 넘어가기" }).click();

    // --- Records completed, Interview section (active) ---
    await expect(page.getByText("기록물 업로드를 완료했어요.")).toBeVisible();
    await expect(page.getByText("▸ 아르바이트")).toBeVisible();
    await expect(page.getByText("이 활동을 주 3회 정도 하신 것으로 보여요.")).toBeVisible();
    await expect(page.getByRole("button", { name: "맞아요, 이대로 확인" })).toBeVisible();

    // The shared composer is gone once there's no more free-text step active.
    await expect(composerInput).not.toBeVisible();

    // Sidebar reflects progress without a URL change.
    await expect(page.getByText("내 세션")).toBeVisible();
    await expect(page.getByText("인터뷰 중")).toBeVisible();
  });
});
