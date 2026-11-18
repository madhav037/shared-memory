import { expect, test } from "@playwright/test";

import { openInContents, signInAs } from "./helpers";

// Raj's session in Billing was briefed, then recall added "Use pnpm, not npm" to its prompt
// (tests/console_e2e_server.py). Olive is the team's owner, so she may read what any session was told.

test("an admin opens a session's told record from the Sessions page and reads its briefing and recall", async ({
  page,
}) => {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Billing");
  await page.getByTestId("to-sessions").click();

  const raj = page.getByTestId("session").filter({ hasText: "Raj Raiser" });
  await raj.getByTestId("to-told").click();

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("What it was told");
  await expect(page.getByTestId("told-member")).toHaveText("Raj Raiser");
  await expect(page.locator("main")).toContainText("What they typed is never kept.");

  const told = page.getByTestId("told");
  await expect(told.getByTestId("told-briefing")).toHaveCount(1);
  await expect(told.getByTestId("told-briefing")).toContainText("`raj-backoff`");
  const recall = told.getByTestId("told-recall").filter({ hasText: "Use pnpm, not npm" });
  await expect(recall).toBeVisible();
  // The briefing comes first, then the recall, in the order the session was told them.
  await expect(told.locator("> li").first()).toHaveAttribute("data-testid", "told-briefing");
  // What Raj typed never reaches the page.
  await expect(page.locator("main")).not.toContainText("which package manager");
  // Reading it changes nothing.
  await expect(page.locator("main button")).toHaveCount(0);

  await recall.getByRole("link", { name: "Use pnpm, not npm" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Use pnpm, not npm");
});
