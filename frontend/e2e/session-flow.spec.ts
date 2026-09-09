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
  test("AI가 활동을 못 찾아도 화면이 멈추지 않고 직접 입력으로 진행할 수 있다", async ({ page }) => {
    // 2026-09-09 프로덕션에서 "잘 모르겠어"라고 답하자 화면이 먹통이 됐다.
    // 백엔드는 정상 200으로 빈 배열을 주는데(프롬프트가 "못 찾겠으면 빈 배열"이라고
    // 지시한다) 프론트에 그 분기가 없어서, 보낸 문장도 안 남고 안내도 안 뜨고
    // 목록도 안 그려져 화면이 입력 전과 완전히 같았다.
    const email = uniqueEmail();
    const password = "password123";

    await page.route("**/api/v1/sessions/*/categories/extract", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ suggestions: [] }),
      }),
    );

    await page.goto("/register");
    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("닉네임").fill("Empty Extract");
    await page.getByLabel("비밀번호 (8자 이상)").fill(password);
    await page.getByRole("button", { name: "가입하기" }).click();
    await expect(page).toHaveURL(/\/login$/);

    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("비밀번호").fill(password);
    await page.getByRole("button", { name: "로그인" }).click();

    await page.getByRole("button", { name: "공백기 채우기" }).click();
    await expect(page).toHaveURL(/\/sessions\/[^/]+$/, { timeout: 15000 });

    await page.getByLabel("시작일").fill("2024-01-01");
    await page.getByLabel("종료일").fill("2024-06-30");
    await page.getByRole("button", { name: "확인" }).click();
    await expect(page.getByText("공백기: 2024-01-01 ~ 2024-06-30")).toBeVisible();

    await page.getByPlaceholder("메시지를 입력하세요").fill("잘 모르겠어");
    await page.getByRole("button", { name: "보내기" }).click();

    // 1) 보낸 문장이 말풍선으로 남는다 — 접수됐다는 신호.
    await expect(page.getByText("잘 모르겠어", { exact: true })).toBeVisible({ timeout: 10000 });
    // 2) 빈 결과 안내가 뜬다.
    await expect(page.getByText("구체적인 활동이 잘 안 잡혔어요", { exact: false })).toBeVisible();
    // 3) 막다른 길이 아니다 — 직접 입력으로 빠져나갈 수 있다.
    await page.getByRole("button", { name: "직접 입력할게요" }).click();
    const manualInput = page.locator('input[type="text"]').first();
    await manualInput.fill("독학");
    await page.getByRole("button", { name: "확인" }).click();
    await expect(page.getByText("선택한 활동: 독학")).toBeVisible({ timeout: 10000 });
  });

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
          draft_answer: "주로 저녁 시간대에, 주 3~4회 정도 근무했던 것 같아요.",
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

    // A freshly registered user has no sessions yet, so the landing page
    // offers the 공백기 채우기/일자리 찾기 choice instead of auto-creating —
    // this flow exercises 공백기 채우기.
    await expect(page.getByRole("button", { name: "공백기 채우기" })).toBeVisible();
    await page.getByRole("button", { name: "공백기 채우기" }).click();
    await expect(page).toHaveURL(/\/sessions\/[^/]+$/, { timeout: 15000 });

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
    await expect(page.getByText("선택한 활동: 아르바이트")).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("button", { name: "이 카테고리 자료 없이 넘어가기" })).toBeVisible();
    await page.getByRole("button", { name: "이 카테고리 자료 없이 넘어가기" }).click();

    // --- Records completed, Interview section (active) ---
    // Longer timeout: this step chains a real skip-records call, a session
    // status transition, and a session-context refetch against the real
    // backend/DB, which can run past the default 5s assertion window.
    await expect(page.getByText("기록물 업로드를 완료했어요.")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("▸ 아르바이트")).toBeVisible();
    await expect(page.getByText("이 아르바이트를 얼마나 자주, 어느 정도 기간 동안 하셨나요?")).toBeVisible();

    // Unlike the old draft-confirm flow, the composer stays mounted through
    // the whole interview — free text answers the question. The attach (📎)
    // control itself lives only in RecordsSection (gated to that step, per
    // Phase 4's "move attach control off the shared composer"), so it isn't
    // expected here.
    await expect(composerInput).toBeVisible();

    // The composer arrives pre-filled with the AI's draft answer (editable,
    // not just a placeholder) and a tag marking it as a suggestion.
    await expect(composerInput).toHaveValue("주로 저녁 시간대에, 주 3~4회 정도 근무했던 것 같아요.");
    await expect(page.getByText("AI가 미리 써봤어요", { exact: false })).toBeVisible();

    // Sidebar reflects progress without a URL change.
    await expect(page.getByText("공백기 채우기", { exact: true })).toBeVisible();
    await expect(page.getByText("인터뷰 중")).toBeVisible();
  });
});
