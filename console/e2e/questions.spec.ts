import { expect, test } from "@playwright/test";

import { openInContents, signInAs } from "./helpers";

// Kai wrote "Report exports are CSV" and "Reports keep 13 months of history" in Reporting, and Raj has asked about
// the first (tests/console_e2e_server.py).
const RAJS_QUESTION = "Do the finance exports follow this too?";

test("a member reading another member's memory asks its author a question and sees it in the thread", async ({
  page,
}) => {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Reporting", "Project memory", "Conventions", "Reports keep 13 months of history");

  const questions = page.getByTestId("questions");
  await expect(questions).toContainText("An answer never changes the memory");
  await questions.getByTestId("ask").click();
  await questions.getByTestId("ask-send").click();
  await expect(questions).toContainText("Write the question first.");

  const asked = "Does the 13 months count from each run or from the first one?";
  await questions.getByTestId("ask-text").fill(asked);
  await questions.getByTestId("ask-send").click();

  const thread = questions.getByTestId("question").filter({ hasText: asked });
  await expect(thread).toContainText("Olive Owner asked");
  await expect(thread.getByTestId("question-state")).toHaveText("Open");

  // It is kept, not only shown: the thread is there on the next visit too.
  await page.reload();
  await expect(page.getByTestId("questions").getByTestId("question").filter({ hasText: asked })).toBeVisible();
});

test("a member answers a question waiting for them from the front page, and the thread shows it answered", async ({
  page,
}) => {
  await signInAs(page, 80, "kai");

  const waiting = page.getByTestId("questions-waiting").getByTestId("question-waiting").filter({ hasText: RAJS_QUESTION });
  await expect(waiting).toContainText("Raj Raiser asked");
  await waiting.getByTestId("question-waiting-link").click();

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Report exports are CSV");
  const thread = page.getByTestId("questions").getByTestId("question").filter({ hasText: RAJS_QUESTION });
  await expect(thread.getByTestId("question-state")).toHaveText("Open");
  // Kai wrote it: there is no one for him to ask.
  await expect(page.getByTestId("questions").getByTestId("ask")).toHaveCount(0);

  const answer = "Yes: finance reads them into its own sheets.";
  await thread.getByTestId("answer").click();
  await thread.getByTestId("answer-text").fill(answer);
  await thread.getByTestId("answer-send").click();

  await expect(thread.getByTestId("question-answer")).toContainText(answer);
  await expect(thread.getByTestId("question-answer")).toContainText("Kai Keeper answered");
  await expect(thread.getByTestId("question-state")).toHaveText("Answered");
  // The memory itself is as it was: answering changes none of it.
  await expect(page.getByTestId("memory-body")).toContainText("Every report exports as CSV with a header row");

  await page.goto("/");
  await expect(page.getByTestId("member-menu")).toBeVisible();
  await expect(page.getByTestId("question-waiting").filter({ hasText: RAJS_QUESTION })).toHaveCount(0);
});
