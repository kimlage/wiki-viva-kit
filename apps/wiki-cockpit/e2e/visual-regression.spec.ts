import { expect, test } from "@playwright/test";

// The world routes render the 2D fallback under ?visual=1 (deterministic,
// motion-free) — the same topology and URLs as the 3D scene.
const routes = [
  { name: "world-radar-demo", path: "/demo/w/radar?visual=1", probe: "Galaxy" },
  { name: "world-atlas-demo", path: "/demo/w/atlas?visual=1", probe: "Galaxy" },
  { name: "world-districts-demo", path: "/demo/w/districts?visual=1", probe: "Galaxy" },
  { name: "review-demo", path: "/demo/review?visual=1", probe: "Approve changes" },
  { name: "sources-demo", path: "/demo/sources?visual=1", probe: "Add Knowledge" },
  { name: "health-demo", path: "/demo/health?visual=1", probe: "Checks" }
] as const;

for (const route of routes) {
  test(`${route.name} visual baseline`, async ({ page }) => {
    await page.goto(route.path);
    // The snapshot bundle (17 fetches) loads before the shell paints; give the
    // cold first load headroom so the probe is not flaky on a loaded machine.
    await expect(page.getByText("Loading cockpit")).toHaveCount(0, { timeout: 20000 });
    await expect(page.getByText(route.probe).first()).toBeVisible({ timeout: 20000 });
    await expect(page).toHaveScreenshot(`${route.name}.png`, {
      animations: "disabled",
      fullPage: false
    });
  });
}

test("legacy /pages/:id bookmark lands in the world with the reader open", async ({ page }) => {
  await page.goto("/demo/pages/root-alex-rivera?visual=1");
  await page.waitForURL(/\/demo\/w\/atlas(?:\/|\?|$)/);
  await expect(page.getByLabel(/Reader:/)).toBeVisible();
  await expect(page).toHaveScreenshot("world-reader-demo.png", { animations: "disabled", fullPage: false });
});

test("keyboard loop: drill \u2192 lock \u2192 read \u2192 retreat over the same URLs", async ({ page }) => {
  await page.goto("/demo/w/atlas?visual=1");
  await expect(page.getByText("Galaxy")).toBeVisible();
  // Drill into a context via the fallback group links (same URL grammar).
  await page.locator(".fallbackGroupLink").first().click();
  await page.waitForURL(/\/demo\/w\/atlas\/[^/?]+/);
  // Lock a page (opens the reader and pins ?reader=1 in the URL).
  await page.locator(".fallbackNode").first().click();
  await page.waitForURL(/reader=1/);
  await expect(page.getByLabel(/Reader:/)).toBeVisible();
  // Esc releases the reader, then the lock, then retreats level by level —
  // always the exact reverse of the drill (spatial memory holds).
  await page.keyboard.press("Escape");
  await expect(page).not.toHaveURL(/reader=1/);
  for (let step = 0; step < 3; step += 1) {
    await page.keyboard.press("Escape");
  }
  await expect(page).toHaveURL(/\/demo\/w\/atlas(\?|$)/);
});
