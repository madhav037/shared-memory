import { expect, test, type Page } from "@playwright/test";

import { openInContents, signInAs, teammates } from "./helpers";

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
  // Its hook before each tool named its branch and the files the tools named, but never the tool itself.
  await expect(raj.getByTestId("session-branch")).toHaveText("feature/webhook-backoff");
  await expect(raj.getByTestId("session-touched")).toContainText("src/webhooks/retry.ts");
  await expect(raj).not.toContainText("Read");
  await expect(raj).toContainText("Started");
  await expect(raj).toContainText("Last call");

  // Olive's stated none, so it shows her card in Doing, and says that is where it comes from.
  const olive = sessions.filter({ hasText: "Olive Owner" });
  await expect(olive.getByTestId("session-activity")).toHaveText("Retry failed webhooks");
  await expect(olive.getByTestId("from-card")).toBeVisible();
  await expect(olive.getByTestId("session-locks")).toContainText("src/invoices/split.ts");
  await expect(olive.getByTestId("session-branch")).toHaveCount(0);

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

/** Seconds left on a gate's wait, as the page counts it down ("4:05 left"). */
function secondsIn(left: string | null): number {
  const [minutes = NaN, seconds = NaN] = (left ?? "").replace(" left", "").split(":").map(Number);
  return minutes * 60 + seconds;
}

// Last in the file: Mira's session joins Billing here and stays, as the journeys' clock never moves.
test("a new gate and a new message appear on the Sessions page without reloading, and the gate's time left counts down", async ({
  page,
}) => {
  await openSessions(page, "Billing");
  const miraGated = page.getByTestId("gate").filter({ hasText: "Mira Maker" });
  const fromMira = page.getByTestId("message").filter({ hasText: "Mira Maker" });
  await expect(page.getByTestId("session")).toHaveCount(2);
  await expect(miraGated).toHaveCount(0);
  await expect(fromMira).toHaveCount(0);

  // Mira's coding agent states the activity Raj's session stated: hers is the later session, so she is gated.
  expect((await page.request.post(`${teammates}/collide`)).ok()).toBe(true);

  await expect(miraGated).toHaveCount(1);
  await expect(page.getByTestId("session")).toHaveCount(3);
  // Her coding agent, Copilot in VS Code, has no hooks: nothing refuses her edits, and the page says so. Raj's can be.
  const miraSession = page.getByTestId("session").filter({ hasText: "Mira Maker" });
  await expect(miraSession.getByTestId("cannot-be-gated")).toHaveText("Can’t be gated");
  await expect(page.getByTestId("session").filter({ hasText: "Raj Raiser" }).getByTestId("cannot-be-gated")).toHaveCount(0);
  const waitsForRaj = miraGated.getByTestId("gate-wait").filter({ hasText: "Raj Raiser" });
  await expect(waitsForRaj).toContainText("Adding backoff to the webhook retries");
  await expect(page.getByTestId("collision").filter({ hasText: "Mira Maker" }).first()).toContainText("Raj Raiser");
  const left = waitsForRaj.getByTestId("time-left");
  await expect(left).toHaveText(/^[0-5]:\d\d left$/);
  const first = secondsIn(await left.textContent());
  await expect.poll(async () => secondsIn(await left.textContent()), { timeout: 5000 }).toBeLessThan(first);

  // Then she messages Olive, who is signed in: it is Olive's own session's message, so she sees it.
  expect((await page.request.post(`${teammates}/message`)).ok()).toBe(true);

  await expect(fromMira.first()).toContainText("Mira Maker to you");
  await expect(fromMira.first().getByTestId("message-text")).toHaveText("Is the retry UI yours? I can take the back end.");
  // Still nothing on the page to press: it governs nothing here, and never writes memory (ADR-0009).
  await expect(page.getByTestId("sessions-page").getByRole("button")).toHaveCount(0);

  await page.screenshot({ path: test.info().outputPath("sessions-that-talk.png"), fullPage: true });
});
