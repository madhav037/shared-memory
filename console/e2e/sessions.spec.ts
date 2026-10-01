import { expect, test, type Page } from "@playwright/test";

import { openInContents, signInAs } from "./helpers";

async function openSessions(page: Page, project: string) {
  await signInAs(page, 1, "olive");
  await openInContents(page, project);
  await page.getByTestId("to-sessions").click();
  await expect(page.getByTestId("sessions-page")).toBeVisible();
}

test("a project's Sessions page lists its active sessions, their activity and the files they hold", async ({ page }) => {
  await openSessions(page, "Billing");

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Sessions");
  const sessions = page.getByTestId("session");
  await expect(sessions).toHaveCount(2);

  // Raj's session stated its activity and holds a file.
  const raj = sessions.filter({ hasText: "Raj Raiser" });
  await expect(raj.getByTestId("session-agent")).toHaveText("Claude Code");
  await expect(raj).toContainText("billing-api");
  await expect(raj.getByTestId("session-activity")).toHaveText("Adding backoff to the webhook retries");
  await expect(raj.getByTestId("from-card")).toHaveCount(0);
  await expect(raj.getByTestId("session-locks")).toContainText("src/webhooks/backoff.ts");
  await expect(raj).toContainText("Started");
  await expect(raj).toContainText("Last call");

  // Olive's stated none, so it shows her card in Doing, and says that is where it comes from.
  const olive = sessions.filter({ hasText: "Olive Owner" });
  await expect(olive.getByTestId("session-activity")).toHaveText("Retry failed webhooks");
  await expect(olive.getByTestId("from-card")).toBeVisible();
  await expect(olive.getByTestId("session-locks")).toContainText("src/invoices/split.ts");

  // The page changes nothing: there is nothing on it to press.
  await expect(page.getByTestId("sessions-page").getByRole("button")).toHaveCount(0);

  await page.screenshot({ path: test.info().outputPath("sessions.png"), fullPage: true });
});

test("a project with no active sessions says so", async ({ page }) => {
  await openSessions(page, "Reporting");

  await expect(page.getByTestId("no-sessions")).toContainText("No session is active in Reporting right now.");
  await expect(page.getByTestId("session")).toHaveCount(0);
});

test("the board leads to the project's sessions", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Billing");
  await page.getByTestId("to-board").click();

  await page.getByRole("link", { name: "Sessions" }).click();

  await expect(page.getByTestId("session")).toHaveCount(2);
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the Sessions page reads without scrolling sideways", async ({ page }) => {
    await signInAs(page, 1, "olive");
    await page.getByTestId("open-contents").click();
    await page.getByRole("dialog", { name: "Contents" }).locator(".tree-row", { hasText: "Billing" }).first().click();
    await page.getByTestId("to-sessions").click();

    const raj = page.getByTestId("session").filter({ hasText: "Raj Raiser" });
    await expect(raj.getByTestId("session-activity")).toBeVisible();
    await expect(raj.getByTestId("session-locks")).toContainText("src/webhooks/backoff.ts");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);

    await page.screenshot({ path: test.info().outputPath("sessions-phone.png"), fullPage: true });
  });
});
