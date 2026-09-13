import { test, expect } from "@playwright/test";

function uniqueEmail(): string {
  return `e2e-menu-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

/**
 * The sidebar's per-session "..." menu consolidates rename/delete and adds
 * "취업 정보 검색으로 이관" (migrate to job info search, 커리어 채우기 세션에만).
 * `POST /job-search/draft-query-from-gap` is mocked (it calls a real LLM
 * otherwise, same reasoning as job-search-flow.spec.ts's other LLM mocks).
 */
test.describe("sidebar session menu", () => {
  test("rename via menu, migrate a gap-fill session to job info search with a prefilled draft, then delete", async ({ page }) => {
    const email = uniqueEmail();
    const password = "password123";

    await page.route("**/api/v1/sessions/*/job-search/draft-query-from-gap", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ draft_query: "카페 아르바이트 경험이 있는데 관련 직업훈련과정 알려줘" }),
      }),
    );

    await page.goto("/register");
    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("닉네임").fill("Menu Tester");
    await page.getByLabel("비밀번호 (8자 이상)").fill(password);
    await page.getByRole("button", { name: "가입하기" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("비밀번호").fill(password);
    await page.getByRole("button", { name: "로그인" }).click();

    await page.getByRole("button", { name: "커리어 채우기" }).click();
    await expect(page).toHaveURL(/\/sessions\/[^/]+$/, { timeout: 15000 });

    const menuButton = page.getByRole("button", { name: "더보기" });
    await expect(menuButton).toBeVisible();

    // --- 이름 변경 ---
    await menuButton.click();
    await expect(page.getByRole("menuitem", { name: "취업 정보 검색으로 이관" })).toBeVisible();
    await page.getByRole("menuitem", { name: "이름 변경" }).click();
    const titleInput = page.locator("aside li input[type='text']").first();
    await titleInput.fill("내 첫 공백기 세션");
    await titleInput.press("Enter");
    await expect(page.getByText("내 첫 공백기 세션")).toBeVisible({ timeout: 10000 });

    // --- 취업 정보 검색으로 이관 ---
    await menuButton.click();
    await page.getByRole("menuitem", { name: "취업 정보 검색으로 이관" }).click();
    await expect(page).toHaveURL(/\/sessions\/[^/]+$/, { timeout: 15000 });
    await expect(page.getByText("취업 정보 검색", { exact: true })).toBeVisible();
    // 새로 만들어진 job_search 세션의 컴포저에 초안 질문이 미리 채워져 있다.
    await expect(page.getByPlaceholder("메시지를 입력하세요")).toHaveValue(
      "카페 아르바이트 경험이 있는데 관련 직업훈련과정 알려줘",
      { timeout: 10000 },
    );

    // job_search 세션의 메뉴에는 "이관" 옵션이 없다(gap_fill 전용) — 사이드바에
    // 이제 세션이 2개(원본 커리어 채우기 + 새 취업 정보 검색)라 상태 라벨
    // 텍스트로 그 행을 특정한다(그룹 제목 <h2>는 <li> 밖이라 안 겹침).
    const jobSearchRow = page.locator("li").filter({ hasText: "취업 정보 검색" });
    await jobSearchRow.getByRole("button", { name: "더보기" }).click();
    await expect(page.getByRole("menuitem", { name: "취업 정보 검색으로 이관" })).not.toBeVisible();

    // --- 삭제 ---
    const jobSearchUrl = page.url();
    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("menuitem", { name: "삭제" }).click();
    // 삭제 후엔 이 job_search 세션 URL을 벗어난다(남아있는 커리어 채우기
    // 세션으로 자동 리다이렉트되는지, 홈에 머무는지는 이 테스트의 관심사가
    // 아니라 URL이 바뀌었다는 것만 확인한다).
    await expect(page).not.toHaveURL(jobSearchUrl, { timeout: 10000 });
    await expect(page.getByText("카페 아르바이트 경험이 있는데")).not.toBeVisible();
  });
});
