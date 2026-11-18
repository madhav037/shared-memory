import { expect, test } from "@playwright/test";

import { openInContents, signInAs } from "./helpers";

// Raj has two sessions in Billing (tests/console_e2e_server.py): raj-backoff, active, which recall told the pnpm
// memory, and raj-docs, which stated "Writing the webhook retry docs" on docs/webhook-retries and ended. Raj is a
// member who leads nothing, so he sees only his own sessions, never Olive's.

test("a member finds their recent sessions, an ended one with its last activity, and opens one's told record", async ({
  page,
}) => {
  await signInAs(page, 2, "dana");
  await openInContents(page, "Billing");
  await page.getByTestId("to-sessions").click();
  await page.getByTestId("to-recent-sessions").click();

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Recent sessions");
  const listed = page.getByTestId("recent-session");
  await expect(listed.first()).toBeVisible();
  await expect(page.getByTestId("recent-sessions")).not.toContainText("Olive Owner");

  const docs = listed.filter({ hasText: "Writing the webhook retry docs" });
  await expect(docs).toHaveCount(1);
  await expect(docs.getByTestId("recent-session-branch")).toHaveText("docs/webhook-retries");
  await expect(docs.getByTestId("recent-session-state")).toHaveText("Ended or idle");

  const backoff = listed.filter({ hasText: "Adding backoff to the webhook retries" });
  await expect(backoff.getByTestId("recent-session-state")).toHaveText("Active");
  await expect(backoff.getByTestId("recent-session-told")).toHaveText("Told 1 memory");
  // Reading it changes nothing.
  await expect(page.locator("main button")).toHaveCount(0);

  await backoff.getByTestId("to-told").click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("What it was told");
  await expect(page.getByTestId("told-member")).toHaveText("Raj Raiser");
  await expect(page.getByTestId("told").getByTestId("told-recall")).toContainText("Use pnpm, not npm");
});
