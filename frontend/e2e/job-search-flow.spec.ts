import { test, expect } from "@playwright/test";

function uniqueEmail(): string {
  return `e2e-job-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

/**
 * Drives the 일자리 찾기 flow against the real local backend/DB: registering
 * with zero sessions lands on the 공백기 채우기/일자리 찾기 chooser, picking
 * 일자리 찾기 creates a kind="job_search" session, and the preferences step
 * (free-text extract -> tag edit -> confirm) runs for real. The external
 * 워크넷 search call is mocked at the network layer (`job-search/search`),
 * since it needs a real WORKNET_API_KEY this environment doesn't have —
 * everything up to triggering that call goes through the real app.
 */
test.describe("job search flow", () => {
  test("chooser -> job_search session -> preferences confirm -> mocked results", async ({ page }) => {
    const email = uniqueEmail();
    const password = "password123";

    await page.route("**/api/v1/sessions/*/job-search/preferences/extract", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          salary_min: null,
          salary_max: null,
          location: "서울",
          education_level: null,
          career_years: null,
          work_style_tags: ["재택 가능"],
        }),
      }),
    );

    await page.route("**/api/v1/sessions/*/job-search/search", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "JOB_RESULTS_REVIEW",
          linked_gap_session_id: null,
          preferences: { salary_min: null, salary_max: null, location: "서울", education_level: null, career_years: null, work_style_tags: ["재택 가능"] },
          last_searched_at: new Date().toISOString(),
          results: [
            {
              source: "worknet",
              external_id: "K1",
              title: "백엔드 개발자",
              company: "테스트회사",
              salary_text: "연봉 3500",
              location: "서울",
              education_requirement: "학력무관",
              career_requirement: "경력무관",
              work_type: "정규직",
              url: "https://work24.go.kr/1",
              fit: true,
              reason: "희망 근무지와 일치합니다",
            },
          ],
        }),
      }),
    );

    await page.goto("/register");
    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("닉네임").fill("Job Search Tester");
    await page.getByLabel("비밀번호 (8자 이상)").fill(password);
    await page.getByRole("button", { name: "가입하기" }).click();
    await expect(page).toHaveURL(/\/login$/);

    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("비밀번호").fill(password);
    await page.getByRole("button", { name: "로그인" }).click();

    // Zero sessions -> chooser, picking 일자리 찾기 creates a job_search session.
    await expect(page.getByRole("button", { name: "일자리 찾기" })).toBeVisible();
    await page.getByRole("button", { name: "일자리 찾기" }).click();
    await expect(page).toHaveURL(/\/sessions\/[^/]+$/, { timeout: 15000 });

    // Sidebar groups this under 일자리 찾기, not 공백기 채우기.
    await expect(page.getByText("일자리 찾기", { exact: true })).toBeVisible();
    await expect(page.getByText("조건 입력")).toBeVisible();

    // --- Preferences step (active): free text -> extracted tag ---
    await expect(page.getByText("어떤 조건의 일자리를 찾고 계신가요?", { exact: false })).toBeVisible();
    const composerInput = page.getByPlaceholder("메시지를 입력하세요");
    await composerInput.fill("재택 가능한 곳이면 좋겠고, 서울에서 일하고 싶어요.");
    await page.getByRole("button", { name: "보내기" }).click();

    // Extracted tag appears as an editable chip. A controlled <input>'s live
    // value is a DOM property, not reflected back to the `value` HTML
    // attribute, so `input[value=...]` can't find it — assert via
    // toHaveValue on the labeled tag input instead (React controlled-input
    // caveat, not Playwright-specific).
    const tagInputs = page.getByLabel("업무 스타일 태그");
    await expect(tagInputs).toHaveCount(1, { timeout: 10000 });
    await expect(tagInputs.nth(0)).toHaveValue("재택 가능");

    // Add one more tag manually before confirming — the "확인 단계" CRUD
    // requirement applies here too, same as CategorySection's suggestion list.
    await page.getByPlaceholder("새 태그").fill("빠른 성장");
    await page.getByRole("button", { name: "+ 태그 추가" }).click();
    await expect(tagInputs).toHaveCount(2);
    await expect(tagInputs.nth(1)).toHaveValue("빠른 성장");

    await page.getByRole("button", { name: "확인" }).click();

    // --- Results (mocked search) ---
    await expect(page.getByText("백엔드 개발자")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("테스트회사")).toBeVisible();
    await expect(page.getByText("적합", { exact: true })).toBeVisible();
  });
});
