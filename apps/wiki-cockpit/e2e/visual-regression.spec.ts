import { expect, test } from "@playwright/test";

const routes = [
  { name: "ops-demo", path: "/demo?visual=1", heading: "What needs attention?", focus: "Use The Map To" },
  { name: "review-demo", path: "/review?demo=1&visual=1", heading: "Approval Inbox", focus: "Scope to approve" },
  { name: "sources-demo", path: "/sources?demo=1&visual=1", heading: "Add Knowledge", focus: "Review New Source" },
  { name: "health-demo", path: "/health?demo=1&visual=1", heading: "Wiki Health", focus: "Wiki Health" },
  { name: "page-demo", path: "/pages/sample-root?demo=1&visual=1", heading: "Sample Memory", focus: "Sample Memory" }
] as const;

for (const route of routes) {
  test(`${route.name} visual baseline`, async ({ page }) => {
    await page.goto(route.path);
    await expect(page.getByRole("heading", { name: route.heading })).toBeVisible();
    await expect(page.getByText("Loading cockpit")).toHaveCount(0);
    await page.getByRole("heading", { name: route.focus }).scrollIntoViewIfNeeded();
    await expect(page).toHaveScreenshot(`${route.name}.png`, {
      animations: "disabled",
      fullPage: false
    });
  });
}
