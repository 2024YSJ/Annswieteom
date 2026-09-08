import { test, expect, type Page } from "@playwright/test";

function uniqueEmail(): string {
  return `e2e-job-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

/** 다음 preferences/extract 호출이 이 suggestion을 반환하도록(한 번만 유효 —
 * 매 턴마다 다시 등록) 라우트를 갱신한다. */
async function mockNextExtract(page: Page, suggestion: Record<string, unknown>) {
  await page.route("**/api/v1/sessions/*/job-search/preferences/extract", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        desired_keyword: null,
        salary_min: null,
        salary_max: null,
        location: null,
        education_level: null,
        career_years: null,
        work_style_tags: [],
        ...suggestion,
      }),
    }),
  );
}

/**
 * Drives the 일자리 찾기 flow against the real local backend/DB: registering
 * with zero sessions lands on the 공백기 채우기/일자리 찾기 chooser, picking
 * 일자리 찾기 creates a kind="job_search" session, and the first-time
 * conversational Q&A (6 fixed questions, one at a time, mirroring 공백기
 * 채우기's interview) runs for real. The external 워크넷 search call is
 * mocked at the network layer (`job-search/search`), since it needs a real
 * WORKNET_API_KEY this environment doesn't have.
 */
test.describe("job search flow", () => {
  test("chooser -> guided Q&A -> confirm summary -> reopen edit -> mocked results", async ({ page }) => {
    const email = uniqueEmail();
    const password = "password123";
    const composerInput = page.getByPlaceholder("메시지를 입력하세요");
    const answerInput = page.getByLabel("답변 수정");

    await page.route("**/api/v1/sessions/*/job-search/search", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "JOB_RESULTS_REVIEW",
          linked_gap_session_id: null,
          // 확정된 값 그대로 — 이 mock 응답이 그대로 쿼리 캐시를 덮어쓰므로
          // (JobSearchResultsSection), 실제로 확정된 값과 다르게 적어두면
          // "검색 후 preferences가 줄어든 것처럼" 보이는 테스트 자체의
          // 오탐이 생긴다(과거에 실제로 겪었던 버그).
          preferences: {
            desired_keyword: "백엔드 개발",
            salary_min: 3000,
            salary_max: 4000,
            location: "서울",
            education_level: "학력무관",
            career_years: null,
            work_style_tags: ["재택 가능", "빠른 성장"],
          },
          completed_fields: ["keyword", "location", "salary", "education", "career", "work_style"],
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

    // --- Q1: 직무/분야 (keyword) ---
    await expect(page.getByText("어떤 직무나 분야의 일자리를 찾고 계신가요?", { exact: false })).toBeVisible();
    await mockNextExtract(page, { desired_keyword: "백엔드 개발" });
    await composerInput.fill("백엔드 개발 쪽 일을 하고 싶어요.");
    await page.getByRole("button", { name: "보내기" }).click();
    await expect(answerInput).toHaveValue("백엔드 개발", { timeout: 10000 });
    await page.getByRole("button", { name: "다음" }).click();

    // --- Q2: 근무지 (location) ---
    await expect(page.getByText("어느 지역에서 근무하고 싶으신가요?", { exact: false })).toBeVisible();
    await mockNextExtract(page, { location: "서울" });
    await composerInput.fill("서울에서 일하고 싶어요.");
    await page.getByRole("button", { name: "보내기" }).click();
    await expect(answerInput).toHaveValue("서울", { timeout: 10000 });
    await page.getByRole("button", { name: "다음" }).click();

    // --- Q3: 급여 (salary) — 숫자 두 칸짜리 위젯 ---
    await expect(page.getByText("희망하시는 급여 수준이", { exact: false })).toBeVisible();
    await mockNextExtract(page, { salary_min: 3000, salary_max: 4000 });
    await composerInput.fill("3000에서 4000만원 정도요.");
    await page.getByRole("button", { name: "보내기" }).click();
    await expect(page.getByLabel("최소(만원)")).toHaveValue("3000", { timeout: 10000 });
    await expect(page.getByLabel("최대(만원)")).toHaveValue("4000");
    await page.getByRole("button", { name: "다음" }).click();

    // --- Q4: 학력 (education) ---
    await expect(page.getByText("학력 조건이 있으신가요?", { exact: false })).toBeVisible();
    await mockNextExtract(page, { education_level: "학력무관" });
    await composerInput.fill("학력은 안 봐도 돼요.");
    await page.getByRole("button", { name: "보내기" }).click();
    await expect(answerInput).toHaveValue("학력무관", { timeout: 10000 });
    await page.getByRole("button", { name: "다음" }).click();

    // --- Q5: 경력 (career) — "건너뛰기"로 스킵 경로도 확인 ---
    await expect(page.getByText("관련 경력이 몇 년 정도 되시나요?", { exact: false })).toBeVisible();
    await page.getByRole("button", { name: "특별히 없어요 / 건너뛰기" }).click();
    await expect(page.getByLabel("답변 수정")).toHaveValue("");
    await page.getByRole("button", { name: "다음" }).click();

    // --- Q6: 업무 스타일 (work_style) — 태그, 마지막 질문 ---
    await expect(page.getByText("선호하는 업무 스타일이나 근무 조건이 있으신가요?", { exact: false })).toBeVisible();
    await mockNextExtract(page, { work_style_tags: ["재택 가능"] });
    await composerInput.fill("재택 가능한 곳이면 좋겠어요.");
    await page.getByRole("button", { name: "보내기" }).click();
    const tagInputs = page.getByLabel("업무 스타일 태그");
    await expect(tagInputs).toHaveCount(1, { timeout: 10000 });
    await expect(tagInputs.nth(0)).toHaveValue("재택 가능");
    // 확인 단계 CRUD: AI 제안 위에 사용자가 태그를 하나 더 추가할 수 있다.
    await page.getByPlaceholder("새 태그").fill("빠른 성장");
    await page.getByRole("button", { name: "+ 태그 추가" }).click();
    await expect(tagInputs).toHaveCount(2);
    await page.getByRole("button", { name: "다음" }).click();

    // --- 6개 다 답하면 완료 요약 화면으로 전환 ---
    await expect(page.getByText("찾는 직무/분야: 백엔드 개발")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("희망 근무지: 서울")).toBeVisible();
    await expect(page.getByText("희망 급여: 3000 ~ 4000")).toBeVisible();
    await expect(page.getByText("학력: 학력무관")).toBeVisible();
    await expect(page.getByText("선호 스타일: 재택 가능, 빠른 성장")).toBeVisible();
    // 경력은 건너뛰었으므로(null) 요약에 아예 안 나온다.
    await expect(page.getByText("경력:", { exact: false })).not.toBeVisible();

    // --- 확정 후에도 입력창은 살아있고, "조건 수정하기"로 재편집 가능 ---
    await expect(page.getByRole("button", { name: "조건 수정하기" })).toBeVisible();
    await expect(composerInput).toBeVisible();
    await page.getByRole("button", { name: "조건 수정하기" }).click();
    await expect(page.getByLabel("찾는 직무/분야")).toHaveValue("백엔드 개발");
    await expect(tagInputs).toHaveCount(2);

    // "취소"는 아무것도 저장하지 않고 요약 화면으로 되돌아간다.
    await page.getByRole("button", { name: "취소" }).click();
    await expect(page.getByText("찾는 직무/분야: 백엔드 개발")).toBeVisible();

    // --- Results (mocked search) ---
    await expect(page.getByText("백엔드 개발자")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("테스트회사")).toBeVisible();
    await expect(page.getByText("적합", { exact: true })).toBeVisible();
  });
});
