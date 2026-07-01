import { expect, test } from "@playwright/test";

const routes = [
  { name: "ops-demo", path: "/demo?visual=1", heading: "Operations - Sample Wiki", focus: "Timeline Radar" },
  { name: "review-demo", path: "/review?demo=1&visual=1", heading: "Human Gate", focus: "Semantic Diff" },
  { name: "sources-demo", path: "/sources?demo=1&visual=1", heading: "Sources", focus: "Ingestion Wizard" },
  { name: "health-demo", path: "/health?demo=1&visual=1", heading: "Context Vitality", focus: "Context Vitality" },
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
