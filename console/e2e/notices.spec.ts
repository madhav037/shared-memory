import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

test("a member is told on the front page that their card was commented on, and opens the card from there", async ({
  page,
}) => {
  await signInAs(page, 1, "olive");

  // Raj commented on the card Olive claimed: the notice her coding agent passes on in a briefing is here too.
  const notice = page.getByTestId("notices").getByTestId("notice").filter({ hasText: "commented on your card 1" });
  await expect(notice).toContainText("Raj Raiser");
  await expect(notice).toContainText("The provider retries three times on its side too.");

  await notice.getByTestId("notice-link").click();

  await expect(page).toHaveURL(/\/board\?card=1/);
  await expect(page.getByTestId("card-panel")).toContainText("Retry failed webhooks");
  await expect(page.getByTestId("card-comments")).toContainText("The provider retries three times on its side too.");
});

test("a member told a memory was promoted in their name reads who did it and opens the memory by its title", async ({
  page,
}) => {
  await signInAs(page, 3, "mira");

  // The server words it for her coding agent, with Olive's member ID and the memory's path; here it names them.
  const notice = page.getByTestId("notices").getByTestId("notice").filter({ hasText: "promoted a memory in your name" });
  await expect(notice).toContainText("Olive Owner promoted a memory in your name: Money is integer cents");
  await expect(notice).not.toContainText("E1001");
  await expect(notice).not.toContainText("projects/");
  await expect(notice.locator(".notice-memory")).toHaveText("Money is integer cents");

  await notice.getByTestId("notice-memory-link").click();

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Money is integer cents");
});
