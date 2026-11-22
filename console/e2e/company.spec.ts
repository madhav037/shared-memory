import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

test("an owner adds a member, sees the token once, grants admin, reissues their token and removes them", async ({
  page,
}) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("to-company").click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^Company \S+$/);

  await page.getByTestId("new-member-id").fill("emp-7");
  await page.getByTestId("new-name").fill("Dana Dev");
  await page.getByTestId("new-github").fill("dana-seven");
  await page.getByTestId("add-member").click();

  await expect(page.getByTestId("new-member-token-value")).toContainText("smt_");
  const first = await page.getByTestId("new-member-token-value").textContent();
  const members = page.getByTestId("members");
  await expect(members).toContainText("Dana Dev");
  await expect(members).toContainText("@dana-seven");
  await expect(page.getByTestId("verified-email-emp-7")).toHaveText("no verified email · signs in with GitHub");

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
  await expect(page.getByTestId("member-places")).toContainText(/places used|no member cap/);
});

test("an owner adds a member by email, sees it unverified, changes it and clears it", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("to-company").click();

  await expect(page.getByLabel("Email or GitHub username")).toBeVisible();
  await page.getByTestId("new-member-id").fill("emp-8");
  await page.getByTestId("new-name").fill("Eli Eng");
  await page.getByTestId("new-github").fill("eli@example.com");
  await page.getByTestId("add-member").click();

  await expect(page.getByTestId("new-member-token-value")).toContainText("smt_");
  await expect(page.getByTestId("verified-email-emp-8")).toHaveText("eli@example.com · unverified");

  await page.getByTestId("actions-emp-8").click();
  await page.getByTestId("change-email-emp-8").click();
  await page.getByLabel("Email (empty to clear)").fill("eli.eng@example.com");
  await page.getByTestId("members").getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("verified-email-emp-8")).toHaveText("eli.eng@example.com · unverified");

  await page.getByTestId("actions-emp-8").click();
  await page.getByTestId("change-email-emp-8").click();
  await page.getByLabel("Email (empty to clear)").fill("");
  await page.getByTestId("members").getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("verified-email-emp-8")).toHaveCount(0);
});

test("an admin downloads all of the company's data as one zip, and the audit log records it", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("to-company").click();

  const downloading = page.waitForEvent("download");
  await page.getByTestId("download-export").click();
  const file = await downloading;

  expect(file.suggestedFilename()).toMatch(/shared-memory-export\.zip$/);
  const saved = await file.path();
  expect(readFileSync(saved).subarray(0, 2).toString()).toBe("PK");

  await page.getByTestId("to-audit").click();
  await expect(page.getByText("Company data downloaded").first()).toBeVisible();
});

test("the old address of the members page opens the Company page", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.goto("/team");

  await expect(page).toHaveURL(/\/company$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^Company \S+$/);
});
