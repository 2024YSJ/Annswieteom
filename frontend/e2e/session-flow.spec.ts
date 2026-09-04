import { test, expect } from "@playwright/test";

function uniqueEmail(): string {
  return `e2e-flow-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

/**
 * Drives the unified /sessions/{id} chat page — a calendar form for period,
 * a single shared ChatComposer for categories/records/interview — through
 * period -> categories -> records(skip) -> arrival at the interview section,
 * all against the real local backend/DB (none of these calls touch an LLM,
 * so this part is deterministic without a local Ollama/Gemini running).
 *
 * The two LLM-touching calls in this range, `POST categories/extract` and
 * `POST interview/ask`, are mocked — but the test stops before answering the
 * interview question. Answering it would call the *real* `interview/answer`,
 * which requires a real `pending_turn` row that only a real (unmocked)
 * `interview/ask` call would have written server-side; since that call is
 * mocked here, the DB was never actually transitioned, and a real answer
 * would 409. Simulating the rest of the loop by *also* mocking
 * `GET /sessions/{id}` was considered and rejected: every mutation in this
 * app re-syncs state via `invalidateQueries` on that same real endpoint, so
 * driving the UI forward this way would mean reimplementing the whole state
 * machine as a second, unverified copy inside the test. The state machine
 * itself is already thoroughly covered by the backend's own pytest suite
 * (unchanged in this phase) — this test's job is only to prove the new
 * unified-page wiring is correct, not to re-prove backend logic.
 *
 * `categories/extract` and `interview/ask` never mutate session state in a
 * way this test observes (the real, unmocked POST /period / POST /categories
 * calls below are what actually persists), so mocking them doesn't risk
 * desyncing real vs. mocked state the way mocking interview/answer or
 * interview/confirm would.
 */
test.describe("unified session chat flow", () => {
  test("period -> categories -> records -> interview section, on one URL", async ({ page }) => {
    const email = uniqueEmail();
    const password = "password123";

    await page.route("**/api/v1/sessions/*/categories/extract", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ suggestions: [{ category_type: "part_time", custom_label: "아르바이트" }] }),
      }),
    );

    await page.route("**/api/v1/sessions/*/interview/ask", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          category_id: "00000000-0000-0000-0000-000000000000",
          question_text: "이 아르바이트를 얼마나 자주, 어느 정도 기간 동안 하셨나요?",
          question_source: "base",
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

    // --- Period section (active): calendar date inputs, not free text ---
    await expect(page.getByText("공백기가 언제부터 언제까지였나요?", { exact: false })).toBeVisible();
    await page.getByLabel("시작일").fill("2024-01-01");
    await page.getByLabel("종료일").fill("2024-06-30");
    await page.getByRole("button", { name: "확인" }).click();

    // --- Period completed, Category section (active) ---
    await expect(page.getByText("공백기: 2024-01-01 ~ 2024-06-30")).toBeVisible();
    const composerInput = page.getByPlaceholder("메시지를 입력하세요");
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
    await expect(page.getByText("이 아르바이트를 얼마나 자주, 어느 정도 기간 동안 하셨나요?")).toBeVisible();

    // Unlike the old draft-confirm flow, the composer stays mounted through
    // the whole interview — free text answers the question, and the attach
    // (📎) button is available at any point, not gated to the records step.
    await expect(composerInput).toBeVisible();
    await expect(page.getByTitle("첨부")).toBeVisible();

    // Sidebar reflects progress without a URL change.
    await expect(page.getByText("내 세션")).toBeVisible();
    await expect(page.getByText("인터뷰 중")).toBeVisible();
  });
});
