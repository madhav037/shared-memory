import { expect, test } from "@playwright/test";

const fakeGitHub = "http://127.0.0.1:8124";

async function signInAs(page: import("@playwright/test").Page, id: number, login: string) {
  await page.request.post(`${fakeGitHub}/as-account`, { data: { id, login } });
  await page.getByTestId("sign-in").click();
}

test("a project is restricted, a member is let in, and then loses access", async ({ page }) => {
  await page.goto("/");
  await signInAs(page, 1, "olive");

  // Someone to let in, and a project to keep from everyone else.
  await page.getByTestId("to-team").click();
  await page.getByTestId("new-employee-id").fill("emp-ray");
  await page.getByTestId("new-name").fill("Ray Reader");
  await page.getByTestId("new-github").fill("ray-reader");
  await page.getByTestId("add-member").click();
  await expect(page.getByTestId("members")).toContainText("Ray Reader");

  await page.getByRole("link", { name: "Shared Memory" }).click();
  await page.getByTestId("new-project-name").fill("Vault");
  await page.getByTestId("create-project").click();
  const projectId = ((await page.getByTestId("project-id").textContent()) ?? "").trim();

  await page.getByTestId("new-access").fill("emp-ray");
  await page.getByTestId("add-access").click();
  await expect(page.getByTestId("access")).toContainText("Ray Reader");
  await page.getByTestId("restrict").click();
  await expect(page.getByTestId("restricted")).toBeVisible();

  // Ray is on the access list, so the project is theirs to read.
  await page.getByTestId("sign-out").click();
  await signInAs(page, 78, "ray-reader");
  await expect(page.getByTestId("project-card").filter({ hasText: "Vault" })).toBeVisible();

  // The lead takes that access away again.
  await page.getByTestId("sign-out").click();
  await signInAs(page, 1, "olive");
  await page.goto(`/projects/${projectId}/settings`);
  await page.getByTestId("revoke-emp-ray").click();
  await expect(page.getByTestId("access")).toContainText("Nobody has been let in yet");

  // Now Ray can neither see it listed nor open it.
  await page.getByTestId("sign-out").click();
  await signInAs(page, 78, "ray-reader");
  await expect(page.getByTestId("project-card").filter({ hasText: "Vault" })).toHaveCount(0);

  await page.goto(`/projects/${projectId}`);
  await expect(page.getByText(/is restricted/)).toBeVisible();
});
