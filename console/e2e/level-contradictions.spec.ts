import { expect, test } from "@playwright/test";

import { signInAs, teammates } from "./helpers";

// Olive leads a project of her own. In it Mira, who doesn't lead it, promotes a project memory her session judged
// contradicts a company memory: a level contradiction for the project's leads. Olive decides one each way.

test("a project lead decides level contradictions on the challenges screen, beside both memories and their levels: keeping an exception with a reason, and following, which retires the project memory", async ({
  page,
}) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("to-contents").click();
  await page.getByTestId("new-project-name").fill("Roost");
  await page.getByTestId("create-project").click();
  await expect(page.getByTestId("project-name")).toHaveText("Roost");
  const projectId = encodeURIComponent(decodeURIComponent(new URL(page.url()).pathname.split("/")[2]!));

  for (const way of ["keep", "follow"]) {
    const raised = await page.request.post(`${teammates}/level-contradiction?project_id=${projectId}&way=${way}`);
    expect(raised.ok()).toBe(true);
    expect(((await raised.json()) as { contradiction: number | null }).contradiction).not.toBeNull();
  }

  await page.getByTestId("to-challenges").click();
  await expect(page.getByRole("heading", { name: "Level contradictions" })).toBeVisible();
  const kiln = page.getByTestId("level-contradiction").filter({ hasText: "The glaze kiln fires at night" });
  await expect(kiln).toContainText("Mira Maker’s project memory contradicts company memory");
  await expect(kiln.getByTestId("decides-as")).toContainText("yours to decide as a project lead");
  const sides = kiln.getByTestId("level-side");
  await expect(sides.nth(0)).toContainText("Project memory");
  await expect(sides.nth(0)).toContainText("The glaze kiln fires at night");
  await expect(sides.nth(1)).toContainText("Company memory");
  await expect(sides.nth(1)).toContainText("Kiln firings start at dawn");

  // Keeping an exception needs a reason; with one, the project memory holds over the company memory.
  await kiln.getByRole("button", { name: "Keep an exception" }).click();
  await expect(kiln).toContainText("needs a reason");
  await kiln.getByTestId("exception-reason-input").fill("Glazes craze in the morning draught.");
  await kiln.getByRole("button", { name: "Keep an exception" }).click();
  const slip = page.getByTestId("decided");
  await expect(slip).toContainText("You kept an exception. ‘The glaze kiln fires at night’ holds over");
  await slip.getByRole("link", { name: "Read it" }).click();
  await expect(page.getByTestId("memory-title")).toContainText("The glaze kiln fires at night");
  await expect(page.getByTestId("exception-reason")).toContainText("Glazes craze in the morning draught.");

  // Following retires the project memory, and the company memory holds.
  await page.getByTestId("to-challenges").click();
  const clay = page.getByTestId("level-contradiction").filter({ hasText: "Porcelain clay is wedged by machine" });
  await clay.getByRole("button", { name: "Follow: retire the project memory" }).click();
  await expect(page.getByTestId("decided")).toContainText(
    "You followed it. ‘Porcelain clay is wedged by machine’ is retired, and ‘Clay is wedged by hand’ holds.",
  );
  await expect(page.getByTestId("level-contradictions")).toHaveCount(0);
});
