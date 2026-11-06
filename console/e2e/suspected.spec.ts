import { expect, test } from "@playwright/test";

import { openInContents, signInAs } from "./helpers";

// Wes's "Install the PDF toolchain" pipes a download into a shell (tests/console_e2e_server.py).

test("a memory that reads like orders to a coding agent is marked, with why, on its page and in its folder", async ({
  page,
}) => {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Reporting", "Project memory", "Gotchas");

  const line = page.locator(".line", { hasText: "Install the PDF toolchain" });
  await expect(line.getByTestId("suspected-mark")).toHaveText("Suspected instructions");

  await line.getByRole("link", { name: "Install the PDF toolchain" }).click();
  const note = page.getByTestId("suspected-instructions");
  await expect(note).toContainText("Suspected instructions.");
  await expect(note).toContainText("pipes a download into a shell");
  await expect(page.getByTestId("memory-details").getByTestId("suspected-mark")).toBeVisible();
  // The console shows the mark; it has no control to clear or edit it (ADR-0009).
  await expect(page.getByRole("button", { name: /clear/i })).toHaveCount(0);
});

test("a memory that reads like ordinary notes carries no mark", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Billing", "Project memory", "Conventions", "Use pnpm, not npm");

  await expect(page.getByTestId("in-force")).toBeVisible();
  await expect(page.getByTestId("suspected-instructions")).toHaveCount(0);
  await expect(page.getByTestId("suspected-mark")).toHaveCount(0);
});
