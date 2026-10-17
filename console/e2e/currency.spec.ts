import { expect, test } from "@playwright/test";

import { openInContents, signInAs } from "./helpers";

test("a memory says how current it is and how to cite it exactly", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Billing", "Project memory", "Conventions", "Use pnpm, not npm");

  await expect(page.getByTestId("currency")).toContainText("First written");
  await expect(page.getByTestId("currency")).toContainText("2 versions");

  // A citation points at one version, not just the file, so it still means this text after the next amendment.
  await expect(page.getByTestId("citation")).toContainText("use-pnpm-not-npm.md");
  await expect(page.getByTestId("citation")).toHaveText(/@[0-9a-f]{7}$/);
});

test("a memory reads as text or as the agent reads it, and back", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Billing", "Project memory", "Conventions", "Use pnpm, not npm");

  await page.getByTestId("view-source").click();
  await expect(page.getByTestId("memory-source")).toContainText("type: convention");

  await page.getByTestId("view-text").click();
  await expect(page.getByTestId("memory-body")).toContainText("second lockfile");
  await expect(page.getByTestId("memory-source")).toHaveCount(0);
});

test("the timeline walks a memory back to how it first stood, and forward again", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await openInContents(page, "Billing", "Project memory", "Conventions", "Use pnpm, not npm");

  const timeline = page.getByTestId("timeline");
  await expect(timeline).toContainText("First written");
  await expect(timeline).toContainText("Current");

  // A screen reader hears which version the slider is on and when it was the text, not a bare number.
  const slider = page.getByTestId("history-slider").getByRole("slider");
  await expect(slider).toHaveAttribute("aria-valuetext", /^Version 2 of 2, in force since /);
  await slider.focus();
  await page.keyboard.press("ArrowLeft");

  await expect(slider).toHaveAttribute("aria-valuetext", /^Version 1 of 2, in force /);
  await expect(page.getByTestId("history-stamp")).toContainText("As it stood: version 1");
  await expect(page.getByTestId("version-text")).toContainText("second lockfile");
  // The margin stands at that version too; pinning and retiring still act on the memory as it is now.
  const margin = page.getByTestId("memory-details");
  await expect(margin.getByTestId("standing-past")).toHaveText("As it stood: version 1");
  await expect(margin).not.toContainText("Current");
  await expect(margin.getByTestId("acts-on-current")).toContainText("act on the memory as it stands now");

  await page.keyboard.press("ArrowRight");

  await expect(page.getByTestId("memory-body")).toContainText("second lockfile");
  await expect(page.getByTestId("version-text")).toHaveCount(0);
  await expect(margin).toContainText("Current");
  await expect(margin.getByTestId("acts-on-current")).toHaveCount(0);
});

test("the contents say how current the team's memory is", async ({ page }) => {
  await signInAs(page, 1, "olive");

  await expect(page.getByTestId("current-to")).toContainText("Current to");
});
