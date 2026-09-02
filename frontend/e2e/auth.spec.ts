import { test, expect } from "@playwright/test";

function uniqueEmail(): string {
  return `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

test.describe("email/password auth", () => {
  test("register redirects to login, then login redirects home with a real access token", async ({
    page,
  }) => {
    const email = uniqueEmail();
    const password = "password123";

    await page.goto("/register");
    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("닉네임").fill("E2E Tester");
    await page.getByLabel("비밀번호 (8자 이상)").fill(password);
    await page.getByRole("button", { name: "가입하기" }).click();

    await expect(page).toHaveURL(/\/login$/);

    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("비밀번호").fill(password);

    const [loginResponse] = await Promise.all([
      page.waitForResponse(
        (res) => res.url().endsWith("/api/v1/auth/login") && res.request().method() === "POST",
      ),
      page.getByRole("button", { name: "로그인" }).click(),
    ]);

    expect(loginResponse.status()).toBe(200);
    const body = await loginResponse.json();
    expect(typeof body.access_token).toBe("string");
    expect(body.access_token.length).toBeGreaterThan(0);

    await expect(page).toHaveURL(/\/$/);
  });

  test("duplicate registration shows an inline error", async ({ page }) => {
    const email = uniqueEmail();
    const password = "password123";

    await page.goto("/register");
    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("닉네임").fill("Dup Tester");
    await page.getByLabel("비밀번호 (8자 이상)").fill(password);
    await page.getByRole("button", { name: "가입하기" }).click();
    await expect(page).toHaveURL(/\/login$/);

    await page.goto("/register");
    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("닉네임").fill("Dup Tester");
    await page.getByLabel("비밀번호 (8자 이상)").fill(password);
    await page.getByRole("button", { name: "가입하기" }).click();

    await expect(page.getByText("이미 가입된 이메일입니다.")).toBeVisible();
    await expect(page).toHaveURL(/\/register$/);
  });

  test("wrong password shows an inline error and does not navigate away", async ({ page }) => {
    const email = uniqueEmail();
    const password = "password123";

    await page.goto("/register");
    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("닉네임").fill("Wrong Pw Tester");
    await page.getByLabel("비밀번호 (8자 이상)").fill(password);
    await page.getByRole("button", { name: "가입하기" }).click();
    await expect(page).toHaveURL(/\/login$/);

    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("비밀번호").fill("totally-wrong-password");
    await page.getByRole("button", { name: "로그인" }).click();

    await expect(page.getByText("이메일 또는 비밀번호가 올바르지 않습니다.")).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);
  });
});
