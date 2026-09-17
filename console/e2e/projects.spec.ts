import { expect, test } from "@playwright/test";

const fakeGitHub = "http://127.0.0.1:8124";

test("an admin creates a project, appoints a lead, and that lead sees it as theirs", async ({ page }) => {
  await page.request.post(`${fakeGitHub}/as-account`, { data: { id: 1, login: "olive" } });

  await page.goto("/");
  await page.getByTestId("sign-in").click();

  // The member who will lead the new project.
  await page.getByTestId("to-team").click();
  await page.getByTestId("new-employee-id").fill("emp-lead");
  await page.getByTestId("new-name").fill("Lee Lead");
  await page.getByTestId("new-github").fill("lee-lead");
  await page.getByTestId("add-member").click();
  await expect(page.getByTestId("members")).toContainText("Lee Lead");

  // Creating a project leaves the creator its first lead, on the project's own page.
  await page.getByRole("link", { name: "Shared Memory" }).click();
  await page.getByTestId("new-project-name").fill("Warehouse");
  await page.getByTestId("create-project").click();
  await expect(page.getByTestId("project-name")).toHaveText("Warehouse");
  await expect(page.getByTestId("leads")).toContainText("Olive Owner");

  await page.getByTestId("new-lead").fill("emp-lead");
  await page.getByTestId("add-lead").click();
  await expect(page.getByTestId("leads")).toContainText("Lee Lead");

  await page.getByTestId("new-repository").fill("warehouse-api");
  await page.getByTestId("add-repository").click();
  const projectId = (await page.getByTestId("project-id").textContent()) ?? "";
  await expect(page.getByTestId("repositories")).toContainText("SHARED_MEMORY_REPOSITORY");
  await expect(page.getByTestId("repositories")).toContainText(projectId.trim());

  // Lee signs in and finds the project listed as one they lead, with its audit log.
  await page.getByTestId("sign-out").click();
  await page.request.post(`${fakeGitHub}/as-account`, { data: { id: 77, login: "lee-lead" } });
  await page.getByTestId("sign-in").click();

  await expect(page.getByTestId("who")).toContainText("Lee Lead");
  const warehouse = page.getByTestId("project-card").filter({ hasText: "Warehouse" });
  await expect(warehouse).toContainText("you lead this");
  await expect(warehouse).toContainText("Lee Lead");

  await page.getByTestId("to-audit").click();
  const rows = page.getByTestId("audit-table").locator("tbody tr");
  await expect(rows.first()).toContainText("repository added");
  await expect(page.getByTestId("audit-table")).not.toContainText("signed in");
});
