import { test, expect } from "@playwright/test";

function uniqueEmail(): string {
  return `e2e-guest-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

test.describe("guest sessions", () => {
  test("guest can start exactly one session and sees it in the sidebar", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("button", { name: /게스트로 시작하기/ })).toBeVisible();

    const [createResponse] = await Promise.all([
      page.waitForResponse(
        (res) => res.url().endsWith("/api/v1/sessions") && res.request().method() === "POST",
      ),
      page.getByRole("button", { name: /게스트로 시작하기/ }).click(),
    ]);
    expect(createResponse.status()).toBe(201);

    await expect(page).toHaveURL(/\/sessions\/[^/]+$/);
    await expect(page.getByText("내 세션")).toBeVisible();

    // A guest is already logged in now (with one session) - going back to "/"
    // silently resumes that same session (no button to click through) rather
    // than offering to start a new one.
    await page.goto("/");
    await expect(page).toHaveURL(/\/sessions\/[^/]+$/);

    // The sidebar's own "+ 새 세션" button is the only remaining path to
    // attempt a second session, and that's what should hit the guest limit.
    await page.getByRole("button", { name: "+ 새 세션" }).click();
    await expect(
      page.getByText("비회원은 세션을 1개까지만 만들 수 있어요. 회원가입하면 계속 이어서 쓸 수 있습니다."),
    ).toBeVisible();
  });

  test("guest registering keeps the same session and lands on the home page logged in", async ({
    page,
  }) => {
    const email = uniqueEmail();

    await page.goto("/");
    await page.getByRole("button", { name: /게스트로 시작하기/ }).click();
    await expect(page).toHaveURL(/\/sessions\/[^/]+$/);
    const sessionUrl = page.url();

    await page.getByRole("link", { name: "회원가입하고 저장하기" }).click();
    await expect(page).toHaveURL(/\/register$/);

    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("닉네임").fill("Upgraded Guest");
    await page.getByLabel("비밀번호 (8자 이상)").fill("password123");
    await page.getByRole("button", { name: "가입하기" }).click();

    // A guest upgrade stays logged in on the same token - no /login bounce -
    // and lands back on the very same session (the home page auto-resumes
    // whatever session already exists rather than offering a fresh one).
    await expect(page).toHaveURL(/\/sessions\/[^/]+$/, { timeout: 15000 });
    expect(page.url()).toBe(sessionUrl);
    await expect(page.getByText("Upgraded Guest님")).toBeVisible();
    await expect(page.getByRole("link", { name: "회원가입하고 저장하기" })).not.toBeVisible();
  });
});
