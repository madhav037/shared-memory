import { expect, test } from "@playwright/test";

import { signInAs, signOut } from "./helpers";

test("a project is restricted, a member is let in, and then loses access", async ({ page }) => {
  await signInAs(page, 1, "olive");

  // Someone to let in, and a project to keep from everyone else.
  await page.getByTestId("to-team").click();
  await page.getByTestId("new-member-id").fill("emp-ray");
  await page.getByTestId("new-name").fill("Ray Reader");
  await page.getByTestId("new-github").fill("ray-reader");
  await page.getByTestId("add-member").click();
  await expect(page.getByTestId("members")).toContainText("Ray Reader");

  await page.getByTestId("to-contents").click();
  await page.getByTestId("new-project-name").fill("Vault");
  await page.getByTestId("create-project").click();
  const projectId = ((await page.getByTestId("project-id").textContent()) ?? "").trim();

  await page.getByTestId("new-access").fill("ray-reader");
  await page.getByRole("option", { name: /Ray Reader/ }).click();
  await page.getByTestId("add-access").click();
  await expect(page.getByTestId("access")).toContainText("Ray Reader");
  await page.getByTestId("restrict").click();
  await expect(page.getByTestId("restricted")).toBeVisible();

  // Ray is on the access list, so the project is theirs to read.
  await signOut(page);
  await signInAs(page, 78, "ray-reader");
  await expect(page.getByTestId("project-card").filter({ hasText: "Vault" })).toBeVisible();

  // The lead takes that access away again.
  await signOut(page);
  await signInAs(page, 1, "olive");
  await page.goto(`/projects/${projectId}/settings`);
  await page.getByTestId(`revoke-emp-ray`).click();
  await expect(page.getByTestId("access")).toContainText("Nobody has been let in yet");

  // Now Ray can neither see it listed nor open it, nor read it by its path.
  await signOut(page);
  await signInAs(page, 78, "ray-reader");
  await expect(page.getByTestId("project-card").filter({ hasText: "Vault" })).toHaveCount(0);

  await page.goto(`/projects/${projectId}`);
  await expect(page.getByTestId("folder-refused")).toContainText("is restricted");
  await page.goto(`/memory?path=projects/${projectId}/shared/conventions/anything.md`);
  await expect(page.getByTestId("memory-refused")).toContainText("is restricted");
});
