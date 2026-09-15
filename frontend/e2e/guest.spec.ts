import { test, expect } from "@playwright/test";

function uniqueEmail(): string {
  return `e2e-guest-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

test.describe("guest sessions", () => {
  test("guest can start multiple sessions and sees them in the sidebar", async ({ page }) => {
    await page.goto("/");

    // 랜딩의 플로우 카드 한 번 클릭이 곧 "게스트 로그인 + 세션 생성"이다 —
    // 예전처럼 게스트 로그인 버튼을 먼저 누르는 단계는 없다. 로그인만 하고
    // 세션 생성은 리다이렉트 effect에 맡기던 구조에서 세션이 두 개 생기는
    // 경쟁이 있었기 때문에(2026-09-05), 두 요청을 한 클릭 안에서 순서대로
    // 보내도록 바꾼 것이다.
    await expect(page.getByRole("button", { name: "커리어 채우기" })).toBeVisible();
    const [createResponse] = await Promise.all([
      page.waitForResponse(
        (res) => res.url().endsWith("/api/v1/sessions") && res.request().method() === "POST",
      ),
      page.getByRole("button", { name: "커리어 채우기" }).click(),
    ]);
    expect(createResponse.status()).toBe(201);

    await expect(page).toHaveURL(/\/sessions\/[^/]+$/);
    await expect(page.getByText("커리어 채우기", { exact: true })).toBeVisible();

    // "/" no longer auto-redirects into the newest session — the main page is
    // a real home now (feed + 이어서 하기), so a returning visitor gets a card
    // back into the same session instead of being teleported there. See the
    // comment at the top of app/page.tsx for why the redirect had to go.
    await page.goto("/");
    await expect(page).toHaveURL(/\/$/);
    // 홈은 인증 확인(refresh + /auth/me) 뒤에야 세션 목록을 부르므로, 이 카드는
    // 왕복 두 번 뒤에 나타난다 — 기본 5초로는 부하가 걸린 실행에서 부족하다.
    const resumeCard = page.getByRole("link", { name: /커리어 채우기/ });
    await expect(resumeCard).toBeVisible({ timeout: 15000 });
    await resumeCard.click();
    await expect(page).toHaveURL(/\/sessions\/[^/]+$/);

    // The guest session cap was removed — the sidebar's "+" button (accessible
    // name "커리어 채우기 새로 만들기") now creates a second session for a guest
    // just like it would for a registered user.
    const [secondCreateResponse] = await Promise.all([
      page.waitForResponse(
        (res) => res.url().endsWith("/api/v1/sessions") && res.request().method() === "POST",
      ),
      page.getByRole("button", { name: "커리어 채우기 새로 만들기", exact: true }).click(),
    ]);
    expect(secondCreateResponse.status()).toBe(201);
    await expect(page).toHaveURL(/\/sessions\/[^/]+$/);
  });

  test("guest registering keeps the same session and lands on the home page logged in", async ({
    page,
  }) => {
    const email = uniqueEmail();

    await page.goto("/");
    await expect(page.getByRole("button", { name: "커리어 채우기" })).toBeVisible();
    await page.getByRole("button", { name: "커리어 채우기" }).click();
    await expect(page).toHaveURL(/\/sessions\/[^/]+$/);
    const sessionUrl = page.url();

    await page.getByRole("link", { name: "회원가입하고 저장하기" }).click();
    await expect(page).toHaveURL(/\/register$/);

    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("닉네임").fill("Upgraded Guest");
    await page.getByLabel("비밀번호 (8자 이상)").fill("password123");
    await page.getByRole("button", { name: "가입하기" }).click();

    // A guest upgrade stays logged in on the same token - no /login bounce -
    // and lands on the home page, where the session the guest already started
    // is still theirs and still reachable from "이어서 하기".
    await expect(page).toHaveURL(/\/$/, { timeout: 15000 });
    // exact: true로 헤더의 <span>만 잡는다 — 홈 히어로가 "{닉네임}님, 이어서
    // 해볼까요?"로 바뀌면서 같은 문자열을 품은 요소가 셋이 됐다.
    await expect(page.getByText("Upgraded Guest님", { exact: true })).toBeVisible();
    const sessionId = sessionUrl.split("/").pop()!;
    await expect(page.locator(`a[href="/sessions/${sessionId}"]`)).toBeVisible();
    await expect(page.getByRole("link", { name: "회원가입하고 저장하기" })).not.toBeVisible();
  });
});
