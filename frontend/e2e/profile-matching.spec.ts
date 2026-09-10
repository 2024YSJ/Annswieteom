import { test, expect, type Page } from "@playwright/test";

function uniqueEmail(): string {
  return `e2e-profile-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

async function registerAndLogin(page: Page): Promise<void> {
  const email = uniqueEmail();
  const password = "password123";
  await page.goto("/register");
  await page.getByLabel("이메일").fill(email);
  await page.getByLabel("닉네임").fill("Profile Tester");
  await page.getByLabel("비밀번호 (8자 이상)").fill(password);
  await page.getByRole("button", { name: "가입하기" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("이메일").fill(email);
  await page.getByLabel("비밀번호").fill(password);
  await page.getByRole("button", { name: "로그인" }).click();
  await expect(page).toHaveURL(/\/$/);
}

async function addAttribute(page: Page, keyLabel: string, value: string): Promise<void> {
  await page.getByLabel("추가할 항목").selectOption({ label: keyLabel });
  await page.getByLabel(keyLabel, { exact: true }).selectOption(value);
  await page.getByRole("button", { name: "추가", exact: true }).click();
  await expect(page.locator(".attr-chip", { hasText: value })).toBeVisible();
}

test.describe("profile attributes and tiered policy matching", () => {
  test("attributes entered on /archive drive the 맞춤 정책 section", async ({ page }) => {
    await registerAndLogin(page);

    await page.goto("/archive");
    await expect(page.getByRole("heading", { name: "나에 대해 알게 된 정보" })).toBeVisible({ timeout: 15000 });
    // 아직 대화도 입력도 없으면 빈 안내가 나온다.
    await expect(page.getByText("아직 알게 된 정보가 없어요.")).toBeVisible();

    await addAttribute(page, "거주지", "수원");
    await addAttribute(page, "취업 상태", "미취업자");
    await expect(page.locator(".attr-chip", { hasText: "수원" })).toContainText("직접 입력");

    // 민감정보 동의: 동의 전에는 "해당 대상" 항목을 고를 수 없다.
    const keySelect = page.getByLabel("추가할 항목");
    await expect(keySelect.locator("option", { hasText: "해당 대상" })).toHaveCount(0);
    await page.getByRole("button", { name: "동의하기" }).click();
    await expect(page.getByText("소득·대상 정보 활용에 동의하셨어요")).toBeVisible();
    await expect(keySelect.locator("option", { hasText: "해당 대상" })).toHaveCount(1);

    // 철회하면 되돌아간다(확인 대화상자 수락).
    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: "동의 철회" }).click();
    await expect(page.getByText("더 정확한 혜택을 찾으려면 몇 가지 여쭤봐도 될까요?")).toBeVisible();

    // 메인의 맞춤 정책 — 속성이 있으므로 조건 매칭된 목록이 와야 한다.
    const [feedResponse] = await Promise.all([
      page.waitForResponse(
        (res) => res.url().includes("/api/v1/feed/policies/recommended") && res.request().method() === "GET",
        { timeout: 30000 },
      ),
      page.goto("/"),
    ]);
    expect(feedResponse.status()).toBe(200);
    const feed = await feedResponse.json();
    expect(feed.personalized).toBe(true);

    await expect(page.getByRole("heading", { name: /맞춤 지원 정책/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: /맞춤 직업훈련/ })).toBeVisible();
    // 정책 캐시에 자격조건이 채워져 있으면(수집 이후) 교집합 카드가 맨 앞에 배지와 함께 나온다.
    const tiers: string[] = feed.items.map((item: { match_tier: string }) => item.match_tier);
    if (tiers.includes("all")) {
      expect(tiers[0]).toBe("all");
      await expect(page.getByText(/조건 \d+개 모두 일치/).first()).toBeVisible();
    }
    // 교집합이 합집합보다 앞선다.
    const firstSome = tiers.indexOf("some");
    const lastAll = tiers.lastIndexOf("all");
    if (firstSome !== -1 && lastAll !== -1) expect(lastAll).toBeLessThan(firstSome);
  });
});
