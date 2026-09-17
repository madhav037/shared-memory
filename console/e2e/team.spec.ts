import { expect, test } from "@playwright/test";

test("an owner adds a member, sees the token once, grants admin and removes them", async ({ page }) => {
  await page.request.post("http://127.0.0.1:8124/as-account", { data: { id: 1, login: "olive" } });

  await page.goto("/");
  await page.getByTestId("sign-in").click();
  await page.getByTestId("to-team").click();

  await page.getByTestId("new-employee-id").fill("emp-7");
  await page.getByTestId("new-name").fill("Dana Dev");
  await page.getByTestId("new-github").fill("dana-seven");
  await page.getByTestId("add-member").click();

  await expect(page.getByTestId("new-member-token-value")).toContainText("smt_");
  const members = page.getByTestId("members");
  await expect(members).toContainText("Dana Dev");
  await expect(members).toContainText("@dana-seven");

  await page.getByTestId("actions-emp-7").click();
  await page.getByRole("menuitem", { name: "Make an admin" }).click();
  await expect(members.getByRole("row", { name: /Dana Dev/ })).toContainText("admin");

  await page.getByTestId("actions-emp-7").click();
  await page.getByTestId("remove-emp-7").click();
  await expect(members.getByRole("row", { name: /Dana Dev/ })).toContainText("removed");
});
