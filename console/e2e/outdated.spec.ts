import { expect, test } from "@playwright/test";

import { openInContents, signInAs } from "./helpers";

// No coding agent has used Wes's "Reports render through wkhtmltopdf" for 61 days (tests/console_e2e_server.py).

test("a memory no coding agent has used for long says it is possibly outdated, on its page and in its folder", async ({
  page,
}) => {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Reporting", "Project memory", "Conventions");

  const line = page.locator(".line", { hasText: "Reports render through wkhtmltopdf" });
  await expect(line.getByTestId("outdated-mark")).toHaveText("Possibly outdated");

  await line.getByRole("link", { name: "Reports render through wkhtmltopdf" }).click();
  const outdated = page.getByTestId("possibly-outdated");
  await expect(outdated).toContainText("Possibly outdated.");
  await expect(outdated).toContainText("No coding agent has recalled or read it since");
  await expect(outdated).toContainText("If it no longer holds, retire it here.");
  await expect(page.getByTestId("memory-details").getByTestId("outdated-mark")).toBeVisible();
  await expect(page.getByTestId("retire")).toBeVisible();

  // Looking at it here is no use of it: it says so again on the next visit.
  await page.reload();
  await expect(page.getByTestId("possibly-outdated")).toBeVisible();
});

test("a memory in use says nothing of the kind", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Billing", "Project memory", "Conventions", "Use pnpm, not npm");

  await expect(page.getByTestId("in-force")).toBeVisible();
  await expect(page.getByTestId("possibly-outdated")).toHaveCount(0);
  await expect(page.getByTestId("last-used")).not.toHaveText("Not yet");
});
