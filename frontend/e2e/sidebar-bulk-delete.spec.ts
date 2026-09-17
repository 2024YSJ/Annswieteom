import { test, expect } from "@playwright/test";

function uniqueEmail(): string {
  return `e2e-bulk-delete-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

/**
 * 사이드바 각 그룹(커리어 채우기 / 취업 정보 검색)은 "선택" 모드에서 여러
 * 세션을 체크박스로 골라 한 번에 삭제할 수 있다. 여기선 커리어 채우기
 * 그룹만 검증한다 — 취업 정보 검색 그룹도 같은 SessionGroup 컴포넌트를
 * 쓰므로 로직은 동일하다.
 */
test.describe("sidebar bulk delete", () => {
  test("select mode: check all sessions in a group and delete them together", async ({ page }) => {
    const email = uniqueEmail();
    const password = "password123";

    await page.goto("/register");
    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("닉네임").fill("Bulk Delete Tester");
    await page.getByLabel("비밀번호 (8자 이상)").fill(password);
    await page.getByRole("button", { name: "가입하기" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await page.getByLabel("이메일").fill(email);
    await page.getByLabel("비밀번호").fill(password);
    await page.getByRole("button", { name: "로그인" }).click();

    await page.getByRole("button", { name: "커리어 채우기" }).click();
    await expect(page).toHaveURL(/\/sessions\/[^/]+$/, { timeout: 15000 });

    await page.getByRole("button", { name: "커리어 채우기 새로 만들기" }).click();
    await expect(page).toHaveURL(/\/sessions\/[^/]+$/, { timeout: 15000 });

    await page.getByRole("button", { name: "여러 세션 선택" }).click();
    await page.getByRole("checkbox", { name: "전체 선택" }).check();

    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: /선택 삭제/ }).click();

    await expect(page.getByText("세션이 없습니다.")).toBeVisible({ timeout: 10000 });
  });
});
