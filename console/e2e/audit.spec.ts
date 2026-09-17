import { expect, test } from "@playwright/test";

const fakeGitHub = "http://127.0.0.1:8124";

test("the owner signs in and finds that sign-in in the audit log", async ({ page }) => {
  await page.request.post(`${fakeGitHub}/as-account`, { data: { id: 1, login: "olive" } });

  await page.goto("/");
  await page.getByTestId("sign-in").click();
  await page.getByTestId("to-audit").click();

  const rows = page.getByTestId("audit-table").locator("tbody tr");
  await expect(rows.first()).toContainText("E1001");
  await expect(rows.first()).toContainText("signed in");

  await page.getByTestId("filter-kind").fill("sign_in_refused");

  await expect(page.getByTestId("audit-empty")).toBeVisible();
});
