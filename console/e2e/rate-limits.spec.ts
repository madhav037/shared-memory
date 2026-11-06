import { expect, test } from "@playwright/test";

import { signInAs, signOut } from "./helpers";

test("an admin changes the rate limits on the Team page, a member sees them read-only, and the audit log shows the change", async ({
  page,
}) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("to-team").click();

  const section = page.getByTestId("rate-limits");
  await expect(section.getByTestId("limit-token")).toHaveText("120 calls a minute");
  await expect(section.getByTestId("limit-console")).toHaveText("300 calls a minute");
  await expect(section.getByTestId("limit-address")).toHaveText("30 calls a minute");

  await section.getByTestId("rate-limit-token").fill("90");
  await section.getByTestId("save-rate-limits").click();
  await expect(section.getByTestId("rate-limits-saved")).toBeVisible();
  await expect(section.getByTestId("limit-token")).toHaveText("90 calls a minute");

  // A reload shows what the server keeps, not what the form remembered.
  await page.reload();
  await expect(page.getByTestId("limit-token")).toHaveText("90 calls a minute");

  await page.getByTestId("to-audit").click();
  const changed = page.getByTestId("audit-table").locator("tbody tr", { hasText: "Rate limits changed" });
  await expect(changed.first()).toContainText("Olive Owner");
  await expect(changed.first()).toContainText("90 a minute per personal token");

  // Raj is a plain member: he sees the numbers, with nothing to change them by.
  await signOut(page);
  await signInAs(page, 2, "dana");
  await page.getByTestId("to-team").click();
  await expect(page.getByTestId("limit-token")).toHaveText("90 calls a minute");
  await expect(page.getByTestId("rate-limit-token")).toHaveCount(0);
  await expect(page.getByTestId("save-rate-limits")).toHaveCount(0);

  // And the server refuses him if he asks anyway.
  const refused = await page.request.post("/api/rate-limits", {
    headers: { "X-Shared-Memory-Console": "1" },
    data: { on: false, token_per_minute: 1000, console_per_minute: 300, address_per_minute: 30 },
  });
  expect(refused.status()).toBe(403);
});
