import { attachViewportScreenshot, expect, test } from "./fixtures";

// A missing reference is written as a review candidate by Playwright. Do not
// let a retry compare against that just-created file and turn an unreviewed
// baseline into a green (flaky) CI result.
test.describe.configure({ retries: 0 });

test.beforeEach(async ({ page }) => {
  // Pixel baselines prove final layout and hierarchy; semantic-motion specs
  // prove the transition path separately. Keep every app-level dock/backdrop
  // on the product's real reduced-motion branch so its entrance phase cannot
  // tint an otherwise identical accepted frame.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
});

// The world routes render the 2D fallback under ?visual=1 (deterministic,
// motion-free) — the same topology and URLs as the 3D scene.
const routes = [
  { name: "world-radar-demo", path: "/demo/w/radar?visual=1", view: "radar", lens: "all", overlay: "freshness" },
  { name: "world-atlas-demo", path: "/demo/w/atlas?visual=1", view: "atlas", lens: "type", overlay: "actions" },
  { name: "world-districts-demo", path: "/demo/w/districts?visual=1", view: "districts", lens: "type", overlay: "actions" },
  { name: "review-demo", path: "/demo/review?visual=1", surface: "Approve changes" },
  { name: "sources-demo", path: "/demo/sources?visual=1", surface: "Add knowledge" },
  { name: "health-demo", path: "/demo/health?visual=1", surface: "Checks" }
] as const;

for (const route of routes) {
  test(`${route.name} visual baseline`, async ({ page }, testInfo) => {
    await page.goto(route.path);
    // The snapshot bundle (17 fetches) loads before the shell paints; give the
    // cold first load headroom and wait for the committed runtime surface. A
    // header word such as "Galaxy" also exists in the lazy-loading skeleton,
    // so it cannot prove that a reviewable world has arrived.
    await expect(page.getByText("Loading cockpit")).toHaveCount(0, { timeout: 20000 });
    await expect(page.locator(".worldRouteLoading, .sceneLoading")).toHaveCount(0, { timeout: 20000 });
    const workspace = page.locator(".worldWorkspace");
    await expect(workspace).toBeVisible({ timeout: 20000 });
    await expect(workspace).toHaveAttribute("data-world-center", "root-alex-rivera");
    if ("view" in route) {
      await expect(workspace).toHaveAttribute("data-runtime-mode", "compat");
      await expect(workspace).toHaveAttribute("data-world-view", route.view);
      await expect(workspace).toHaveAttribute("data-world-lens", route.lens);
      await expect(workspace).toHaveAttribute("data-world-overlay", route.overlay);
      await expect(page.locator(".sceneShell")).toHaveAttribute("data-scene-perspective", route.view);
      await expect(page.locator(".sceneShell")).toHaveAttribute("data-scene-overlay", route.overlay);
      expect(new URL(page.url()).pathname).toBe(`/demo/w/${route.view}`);
    }
    if ("surface" in route) {
      await expect(page.getByRole("dialog", { name: route.surface })).toBeVisible({ timeout: 20000 });
    } else {
      await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/);
      await expect(page.locator(".sceneFallback .fallbackCore")).toBeVisible();
      await expect(page.locator(".fallbackNode").first()).toBeVisible();
    }
    await expect(page).toHaveScreenshot(`${route.name}.png`, {
      animations: "disabled",
      fullPage: false
    });
    await attachViewportScreenshot(page, testInfo, `${route.name}-accepted`);
  });
}

test("legacy /pages/:id bookmark lands in the world with the reader open", async ({ page }, testInfo) => {
  await page.goto("/demo/pages/root-alex-rivera?visual=1");
  await expect.poll(() => {
    const url = new URL(page.url());
    return {
      pathname: url.pathname,
      view: url.searchParams.get("view"),
      page: url.searchParams.get("page"),
      reader: url.searchParams.get("reader")
    };
  }).toEqual({ pathname: "/demo/w", view: "atlas", page: "root-alex-rivera", reader: "1" });
  await expect(page.locator(".worldRouteLoading, .sceneLoading")).toHaveCount(0, { timeout: 20000 });
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", "root-alex-rivera");
  await expect(page.locator(".pageReader")).toBeVisible();
  await expect(page).toHaveScreenshot("world-reader-demo.png", { animations: "disabled", fullPage: false });
  await attachViewportScreenshot(page, testInfo, "world-reader-demo-accepted");
});

test("keyboard loop: drill \u2192 lock \u2192 read \u2192 retreat over the same URLs", async ({ page }) => {
  await page.goto("/demo/w/atlas?visual=1");
  await expect(page.getByText("Galaxy")).toBeVisible();
  // Drill into a context via the fallback group links (same URL grammar).
  await page.locator(".fallbackGroupLink").first().click();
  await expect.poll(() => {
    const url = new URL(page.url());
    return {
      pathname: url.pathname,
      view: url.searchParams.get("view"),
      hasContext: Boolean(url.searchParams.get("compat_context"))
    };
  }).toEqual({ pathname: "/demo/w", view: "atlas", hasContext: true });
  // Lock a page (opens the reader and pins ?reader=1 in the URL).
  await page.locator(".fallbackNode").first().click();
  await page.waitForURL(/reader=1/);
  await expect(page.locator(".pageReader")).toBeVisible();
  // Esc releases the reader, then the lock, then retreats level by level —
  // always the exact reverse of the drill (spatial memory holds).
  await page.keyboard.press("Escape");
  await expect(page).not.toHaveURL(/reader=1/);
  await expect(page.locator(".pageReader")).toHaveCount(0);
  for (let step = 0; step < 3; step += 1) {
    const before = page.url();
    await page.keyboard.press("Escape");
    await expect.poll(() => page.url()).not.toBe(before);
    // Let the next route become the scene's committed retreat origin before
    // sending the next key in the ladder.
    await page.waitForTimeout(100);
  }
  await expect.poll(() => {
    const url = new URL(page.url());
    return {
      pathname: url.pathname,
      view: url.searchParams.get("view"),
      context: url.searchParams.get("compat_context"),
      group: url.searchParams.get("group"),
      page: url.searchParams.get("page"),
      reader: url.searchParams.get("reader")
    };
  }).toEqual({
    pathname: "/demo/w",
    view: "atlas",
    context: null,
    group: null,
    page: null,
    reader: null
  });
});
