import { expect, test } from "@playwright/test";

import { signInAs } from "./helpers";

test("a member picks their coding agent and gets its steps and the repository's files for it", async ({ page }) => {
  await signInAs(page, 1, "olive");
  await page.getByTestId("member-menu").click();
  await page.getByTestId("to-my-token").click();

  await page.getByTestId("connect-Codex").click();

  await expect(page.getByTestId("agent-steps")).toContainText(".codex/config.toml");
  const files = page.getByTestId("agent-files");
  await expect(files.getByTestId("agent-Codex")).toBeVisible();
  await expect(files).toContainText("bearer_token_env_var");
  await expect(files).toContainText("billing-api");
  await expect(files).not.toContainText("smt_");

  await page.getByTestId("connect-Cline").click();

  await expect(page.getByTestId("agent-files")).toContainText("Once, on each member's machine");
});
