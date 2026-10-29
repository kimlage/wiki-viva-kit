import { expect, test } from "./fixtures";

test("standalone Kanban reads canonical demo cards without contacting the operator", async ({ page }) => {
  const operatorRequests: string[] = [];
  page.on("request", request => {
    if (new URL(request.url()).pathname.startsWith("/api/")) {
      operatorRequests.push(`${request.method()} ${new URL(request.url()).pathname}`);
    }
  });
  await page.goto("/demo/board");
  await expect(page.locator(".boardEyebrow")).toContainText("DEMO");
  await expect(page.getByRole("button", { name: "New task", exact: true })).toBeDisabled();
  const card = page.locator(".boardCard").first();
  await expect(card).toBeVisible();
  const title = await card.locator("h3").innerText();
  await page.getByRole("searchbox", { name: "Search actions" }).fill(title);
  await expect(page.locator(".boardCard")).toHaveCount(1);
  await card.click();
  const detail = page.locator(".boardDetail");
  await expect(detail).toHaveAttribute("data-read-state", "ready");
  await expect(detail.getByRole("heading", { name: title, exact: true }).first()).toBeVisible();
  await expect(detail.locator(".boardEvidence")).not.toBeEmpty();
  await expect(detail.locator(".boardForm fieldset")).toHaveAttribute("disabled", "");
  const fields = detail.locator(".boardForm input, .boardForm select, .boardForm textarea");
  expect(await fields.count()).toBeGreaterThan(0);
  for (const field of await fields.all()) await expect(field).toBeDisabled();
  await expect(detail.locator('button[type="submit"]')).toHaveCount(0);
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(detail).toHaveAttribute("data-read-state", "ready");
  await expect(detail.getByRole("heading", { name: title, exact: true }).first()).toBeVisible();
  expect(operatorRequests).toEqual([]);
});
