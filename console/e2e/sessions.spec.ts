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

  // Raj's earlier session ended and left a handoff note, which the page shows and never lets anyone write.
  const note = page.getByTestId("handoff-note").filter({ hasText: "Raj Raiser" });
  await expect(note).toContainText("Writing the webhook retry docs");
  await expect(note.getByTestId("handoff-done")).toHaveText("Done: The retry docs page and its examples.");
  await expect(note.getByTestId("handoff-left")).toHaveText("Left: A section on the backoff settings.");
  await expect(note).toContainText("branch docs/webhook-retries");
  await expect(note).toContainText("docs/webhooks.md");
  await expect(page.getByTestId("handoff-notes").getByRole("button")).toHaveCount(0);
  await expect(raj).toContainText("Last call");

  // Olive's stated none, so it shows her card in Doing, and says that is where it comes from.
  const olive = sessions.filter({ hasText: "Olive Owner" });
  await expect(olive.getByTestId("session-activity")).toHaveText("Retry failed webhooks");
  await expect(olive.getByTestId("from-card")).toBeVisible();
  await expect(olive.getByTestId("session-locks")).toContainText("src/invoices/split.ts");
  await expect(olive.getByTestId("session-branch")).toHaveCount(0);

  // Nothing on a session changes it: a lock and an activity move only from the session itself.
  await expect(page.getByTestId("sessions").getByRole("button")).toHaveCount(0);

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
  // Olive may reply to it (ADR-0026); nothing on a session changes it, and nothing here writes memory (ADR-0009).
  await expect(fromMira.first().getByTestId("reply")).toBeVisible();
  await expect(page.getByTestId("sessions").getByRole("button")).toHaveCount(0);

  await page.screenshot({ path: test.info().outputPath("sessions-that-talk.png"), fullPage: true });
});

// After the one above, and last: Olive's second session and Mira's second join Billing here and stay.
test("Olive refuses, then agrees to, a gate on her work and replies to a message from the page, alerted as each arrives", async ({
  page,
  context,
}) => {
  // The browser has allowed the console's alerts; each one shown is noted, so the journey can see it fired. Headless
  // Chromium reports its notification permission as denied even once granted, so the page is handed a Notification
  // that says granted and only notes each alert.
  await context.grantPermissions(["notifications"]);
  await page.addInitScript(() => {
    const shown: string[] = [];
    (window as unknown as { alertsShown: string[] }).alertsShown = shown;
    class Noted {
      static readonly permission: NotificationPermission = "granted";
      static requestPermission(): Promise<NotificationPermission> {
        return Promise.resolve("granted");
      }
      constructor(title: string) {
        shown.push(title);
      }
    }
    window.Notification = Noted as unknown as typeof Notification;
  });
  const alertsShown = () => page.evaluate(() => (window as unknown as { alertsShown: string[] }).alertsShown);
  const heard = async () => ((await (await page.request.get(`${teammates}/heard`)).json()) as { heard: string }).heard;

  await openSessions(page, "Billing");
  await expect(page.getByTestId("alerts")).toContainText("This browser alerts you");
  // The journey before this one left Mira's first session gated on Olive's first too (its activity is her card in
  // Doing, on the same webhook retries), so this one watches the wait on Olive's second session's work alone.
  const onMine = page
    .getByTestId("gate-wait")
    .filter({ hasText: "your session" })
    .filter({ hasText: "Splitting the invoice module into its own package" });
  await expect(onMine).toHaveCount(0);

  // Mira's second session states the work Olive's second session stated: hers is gated on Olive's work.
  expect((await page.request.post(`${teammates}/gate-olive`)).ok()).toBe(true);

  await expect(onMine).toHaveCount(1);
  await expect.poll(alertsShown).toContain("Mira Maker’s session waits on your work");

  await onMine.getByTestId("refuse").click();

  await expect(onMine.getByTestId("gate-refused")).toHaveText("you refused, until that session ends or goes idle");
  await expect(onMine.getByTestId("refuse")).toHaveCount(0);
  expect(await heard()).toContain("Olive Owner (E1001) refused");

  await onMine.getByTestId("agree").click();

  await expect(onMine).toHaveCount(0);
  expect(await heard()).toContain("Olive Owner (E1001) agreed");

  // Then Mira's second session asks Olive something, and she replies from the page.
  expect((await page.request.post(`${teammates}/ask-olive`)).ok()).toBe(true);
  const question = page
    .getByTestId("message")
    .filter({ hasText: "May I take the invoice tests while you split the module?" });

  await expect(question).toHaveCount(1);
  await expect.poll(alertsShown).toContain("Mira Maker sent you a message");
  await question.getByTestId("reply").click();
  await question.getByTestId("reply-text").fill("Yes, the tests are yours.");
  await question.getByTestId("reply-send").click();

  const reply = page.getByTestId("message").filter({ hasText: "Yes, the tests are yours." });
  await expect(reply).toContainText("You to Mira Maker");
  expect(await heard()).toContain("Yes, the tests are yours.");

  await page.screenshot({ path: test.info().outputPath("sessions-answered.png"), fullPage: true });
});

// Last of all: Olive's third session and Mira's third join Billing here and stay.
test("a session standing by shows whose answer it waits for, and the mark goes when the standby ends", async ({ page }) => {
  await openSessions(page, "Billing");
  const waiting = page.getByTestId("standby");
  await expect(waiting).toHaveCount(0);

  // Mira's third session is gated on the work Olive's third stated, and its coding agent stands by for Olive's answer.
  expect((await page.request.post(`${teammates}/stand-by`)).ok()).toBe(true);

  await expect(waiting).toHaveCount(1);
  await expect(waiting).toHaveText("waiting for Olive Owner’s answer");
  const mira = page.getByTestId("session").filter({ has: waiting });
  await expect(mira.getByTestId("session-activity")).toHaveText("Moving the currency formatting into one shared helper");
  await expect(mira).toContainText("Mira Maker");
  // The mark only shows: nothing on a session changes it, and nothing on the page writes memory (ADR-0009).
  await expect(page.getByTestId("sessions").getByRole("button")).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("sessions-standing-by.png"), fullPage: true });

  // Mira moves on: her next prompt ends the standby, and the next time the page asks, the mark has gone.
  const moved = await page.request.post(`${teammates}/move-on`);
  expect(((await moved.json()) as { ended: string }).ended).toBe("moved_on");

  await expect(waiting).toHaveCount(0);
  const stillActive = page.getByTestId("session").filter({ hasText: "Mira Maker" });
  await expect(stillActive.filter({ hasText: "Moving the currency formatting" })).toHaveCount(1);
});
