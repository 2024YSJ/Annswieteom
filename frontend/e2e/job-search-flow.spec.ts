import { test, expect } from "@playwright/test";

function uniqueEmail(): string {
  return `e2e-job-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

/**
 * Drives the "취업 정보 종합 검색" flow against the real local backend/DB:
 * registering with zero sessions lands on the 공백기 채우기/취업 정보 검색
 * chooser, picking 취업 정보 검색 creates a kind="job_search" session, and the
 * conversational multi-source search runs against a mocked `/job-search/query`
 * (mocked at the network layer since it needs real WorkNet keys this
 * environment doesn't have — the WorkNet clients themselves and the LLM
 * classification prompt are covered by backend unit/integration tests).
 */
test.describe("job search flow", () => {
  test("chooser -> ask a question spanning multiple categories -> results, then a follow-up question", async ({ page }) => {
    const email = uniqueEmail();
    const password = "password123";
    const composerInput = page.getByPlaceholder("메시지를 입력하세요");

    let queryCallCount = 0;
    await page.route("**/api/v1/sessions/*/job-search/query", (route) => {
      queryCallCount += 1;
      if (queryCallCount === 1) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            categories: [
              {
                category: "training_course",
                category_label: "직업훈련과정",
                results: [
                  { title: "백엔드 개발 부트캠프", subtitle: "국민내일배움카드 · 서울 강남구", meta_lines: [], detail_url: "https://work24.go.kr/course/1" },
                ],
              },
              {
                category: "promising_sme",
                category_label: "강소기업",
                results: [
                  { title: "주식회사 테스트", subtitle: "소프트웨어 개발업", meta_lines: ["지역: 서울 강남구", "주요생산품: SaaS"], detail_url: null },
                ],
              },
            ],
            clarification_question: null,
          }),
        });
      }
      // 두 번째 질문 — 애매해서 재질문이 필요한 경우를 확인
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ categories: [], clarification_question: "어떤 종류의 정보를 찾으시나요? 채용행사, 최근 공채 소식, 채용 기업 정보, 직업훈련과정, 취업 지원 프로그램, 강소기업 중에서 궁금하신 걸 말씀해주세요." }),
      });
    });

    await page.goto("/register");
    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("닉네임").fill("Job Info Search Tester");
    await page.getByLabel("비밀번호 (8자 이상)").fill(password);
    await page.getByRole("button", { name: "가입하기" }).click();
    await expect(page).toHaveURL(/\/login$/);

    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("비밀번호").fill(password);
    await page.getByRole("button", { name: "로그인" }).click();

    // Zero sessions -> chooser, picking 취업 정보 검색 creates a job_search session.
    await expect(page.getByRole("button", { name: "취업 정보 검색" })).toBeVisible();
    await page.getByRole("button", { name: "취업 정보 검색" }).click();
    await expect(page).toHaveURL(/\/sessions\/[^/]+$/, { timeout: 15000 });

    // Sidebar groups this under 취업 정보 검색, not 공백기 채우기.
    await expect(page.getByText("취업 정보 검색", { exact: true })).toBeVisible();

    // --- 첫 질문: 훈련과정 + 강소기업 두 카테고리에 동시에 걸치는 질문 ---
    await expect(page.getByText("어떤 취업 정보를 찾아드릴까요?", { exact: false })).toBeVisible();
    await composerInput.fill("이직 준비하는데 도움될 훈련과정이랑 강소기업 있어?");
    await page.getByRole("button", { name: "보내기" }).click();

    await expect(page.getByText("직업훈련과정", { exact: true })).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("백엔드 개발 부트캠프")).toBeVisible();
    await expect(page.getByText("국민내일배움카드 · 서울 강남구")).toBeVisible();
    await expect(page.getByText("강소기업", { exact: true })).toBeVisible();
    await expect(page.getByText("주식회사 테스트")).toBeVisible();
    await expect(page.getByText("지역: 서울 강남구")).toBeVisible();
    await expect(page.getByRole("link", { name: "자세히 보기" })).toHaveAttribute("href", "https://work24.go.kr/course/1");

    // 이전 질문(오른쪽 말풍선)도 대화 이력에 그대로 남아있다.
    await expect(page.getByText("이직 준비하는데 도움될 훈련과정이랑 강소기업 있어?")).toBeVisible();

    // --- 두 번째 질문: 애매한 질문이면 카테고리 대신 재질문이 뜬다 ---
    await composerInput.fill("음...");
    await page.getByRole("button", { name: "보내기" }).click();
    await expect(page.getByText("어떤 종류의 정보를 찾으시나요?", { exact: false })).toBeVisible({ timeout: 10000 });

    // 첫 질문의 결과는 화면에서 안 사라지고 계속 누적돼 있다.
    await expect(page.getByText("백엔드 개발 부트캠프")).toBeVisible();
  });
});
