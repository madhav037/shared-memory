import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

test("an owner adds a member, sees the token once, grants admin, reissues their token and removes them", async ({
  page,
}) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("to-team").click();

  await page.getByTestId("new-member-id").fill("emp-7");
  await page.getByTestId("new-name").fill("Dana Dev");
  await page.getByTestId("new-github").fill("dana-seven");
  await page.getByTestId("add-member").click();

  await expect(page.getByTestId("new-member-token-value")).toContainText("smt_");
  const first = await page.getByTestId("new-member-token-value").textContent();
  const members = page.getByTestId("members");
  await expect(members).toContainText("Dana Dev");
  await expect(members).toContainText("@dana-seven");

  await page.getByTestId("actions-emp-7").click();
  await page.getByRole("menuitem", { name: "Make an admin" }).click();
  await expect(members.getByRole("row", { name: /^Dana Dev/ })).toContainText("Admin");

  await page.getByTestId("actions-emp-7").click();
  await page.getByTestId("reissue-emp-7").click();
  await expect(page.getByTestId("new-member-token-value")).not.toHaveText(first ?? "");

  await page.getByTestId("actions-emp-7").click();
  await page.getByTestId("remove-emp-7").click();
  await page.getByTestId("remove-confirm-emp-7").click();
  await expect(members.getByRole("row", { name: /^Dana Dev/ })).toContainText("removed");
});

test("an admin downloads all of the team's data as one zip, and the audit log records it", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("to-team").click();

  const downloading = page.waitForEvent("download");
  await page.getByTestId("download-export").click();
  const file = await downloading;

  expect(file.suggestedFilename()).toMatch(/shared-memory-export\.zip$/);
  const saved = await file.path();
  expect(readFileSync(saved).subarray(0, 2).toString()).toBe("PK");

  await page.getByTestId("to-audit").click();
  await expect(page.getByText("Team data downloaded").first()).toBeVisible();
});
