import type { Locator, Page } from "@playwright/test";
import { attachViewportScreenshot, expect, test, waitForRuntimePerformance } from "./fixtures";
import { expectSpatialCardsWithinSafeArea } from "./spatial-assertions";
import { expectOverlayEncodingMatrix } from "./overlay-assertions";

async function prepareMobileWorld(page: Page, path = "/demo/w/quadrants?center=root-alex-rivera") {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.goto(path);
  await expect(page.getByText("Loading cockpit")).toHaveCount(0, { timeout: 20_000 });
}

async function expectTouchTarget(locator: Locator) {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  expect.soft(box, "touch target must have a measurable box").not.toBeNull();
  if (!box) return;
  expect.soft(box.width, "touch target width").toBeGreaterThanOrEqual(44);
  expect.soft(box.height, "touch target height").toBeGreaterThanOrEqual(44);
}

async function expectNoMobileTextClipping(page: Page, selectors: string[]) {
  const clipped = await page.evaluate((items) => items.flatMap((selector) =>
    Array.from(document.querySelectorAll<HTMLElement>(selector))
      .filter((element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 1 && rect.height > 1;
      })
      .filter((element) => element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1)
      .map((element) => ({
        selector,
        text: element.textContent?.trim().replace(/\s+/g, " ").slice(0, 160) ?? "",
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
        clientHeight: element.clientHeight,
        scrollHeight: element.scrollHeight
      }))
  ), selectors);
  expect.soft(clipped, "visible mobile labels must not clip").toEqual([]);
}

async function expectMobileViewportBounded(page: Page, selector: string) {
  const surface = page.locator(selector);
  await surface.evaluate(async (element) => {
    const finite = element
      .getAnimations({ subtree: true })
      .filter((animation) => animation.effect?.getTiming().iterations !== Infinity);
    await Promise.all(finite.map((animation) => animation.finished.catch(() => undefined)));
  });
  const bounds = await surface.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return {
      left: rect.left,
      right: rect.right,
      top: rect.top,
      bottom: rect.bottom,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth
    };
  });
  expect.soft(bounds.left, `${selector} left bound`).toBeGreaterThanOrEqual(-1);
  expect.soft(bounds.right, `${selector} right bound`).toBeLessThanOrEqual(bounds.viewportWidth + 1);
  expect.soft(bounds.top, `${selector} top bound`).toBeGreaterThanOrEqual(-1);
  expect.soft(bounds.bottom, `${selector} bottom bound`).toBeLessThanOrEqual(bounds.viewportHeight + 1);
  expect.soft(bounds.documentOverflow, `${selector} document overflow`).toBeLessThanOrEqual(1);
}

test("WebKit mobile uses real touch for lens, view, dock and long-label reader flows", async ({ page }, testInfo) => {
  await prepareMobileWorld(page);

  const device = await page.evaluate(() => ({
    viewport: { width: window.innerWidth, height: window.innerHeight },
    touchPoints: navigator.maxTouchPoints,
    coarse: window.matchMedia("(pointer: coarse)").matches
  }));
  expect(device.viewport).toEqual({ width: 390, height: 844 });
  // Playwright WebKit on macOS intentionally reports maxTouchPoints=0 even
  // when its touch screen is enabled. The coarse-pointer signal plus the
  // real locator.tap() calls below are the cross-browser proof of touch input.
  expect(device.coarse).toBe(true);

  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator("canvas")).toHaveCount(1, { timeout: 20_000 });
  const originalCenter = await page.locator(".worldWorkspace").getAttribute("data-world-center");

  await page.locator(".quadrantTextCell").nth(2).tap();
  await expect(page).toHaveURL(/[?&]lens=/);
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", originalCenter ?? "root-alex-rivera");

  await page.locator(".glyphButton").filter({ hasText: /Atlas/ }).tap();
  await expect(page).toHaveURL(/\/demo\/w\/atlas(?:\?|$)/);
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", originalCenter ?? "root-alex-rivera");

  await page.locator(".dockButton").filter({ hasText: /Sources|Fontes/ }).tap();
  await expect(page).toHaveURL(/[?&]dock=source/);
  const sourceDock = page.locator(".sourceDock");
  await expect(sourceDock).toBeVisible({ timeout: 10_000 });
  await expectMobileViewportBounded(page, ".sourceDock");
  const sourceClose = sourceDock.locator(".readerClose").first();
  await expectTouchTarget(sourceClose);
  await sourceClose.tap();
  await expect(page).not.toHaveURL(/[?&]dock=/);

  await page.locator(".dockButton").filter({ hasText: /Create|Criar/ }).tap();
  await expect(page).toHaveURL(/[?&]dock=create/);
  await expect(page.locator(".spatialCardType")).toHaveCount(7, { timeout: 10_000 });
  await expectSpatialCardsWithinSafeArea(page, { expectedPrimary: 7, expectedTotal: 8 });
  const createClose = page.locator(".seedTitle .questPlateClose");
  await expectTouchTarget(createClose);
  await createClose.tap();
  await expect(page).not.toHaveURL(/[?&]dock=create/);

  for (const longTitle of [
    "Evidence shelf clarifies source-backed work",
    "Calendário calmo rende trabalho melhor"
  ]) {
    await page.locator(".commandSearch input").fill(longTitle);
    await page.locator(".commandSearch input").press("Enter");
    await expect(page.locator(".pageReader")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".readerHead h2")).toHaveText(longTitle);
    await expect(page.locator(".quadrantCompass")).toBeHidden();
    await expect(page.locator(".worldNavigator")).toBeHidden();
    await expectMobileViewportBounded(page, ".pageReader");
    await expectNoMobileTextClipping(page, [
      ".worldBreadcrumbs strong",
      ".worldMeta span",
      ".readerHead h2",
      ".readerChips .pill",
      ".readerActionBar .secondaryButton span",
      ".dockHeader strong",
      ".dockTelemetryTop small",
      ".dockTelemetryTop strong"
    ]);
    const readerClose = page.locator(".pageReader .readerClose").last();
    await expectTouchTarget(readerClose);
    await readerClose.tap();
    await expect(page.locator(".pageReader")).toHaveCount(0);
  }
  await attachViewportScreenshot(page, testInfo, "webkit-mobile-touch-flow");
});

test("WebKit mobile keeps the same semantic route in reduced-motion fallback", async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await prepareMobileWorld(page, "/demo/w/quadrants?center=root-alex-rivera&lens=pratica");

  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator("canvas")).toHaveCount(0);
  await expect(page).not.toHaveURL(/[?&]visual=1/);
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", "root-alex-rivera");
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", /pratica|q2_pratica/);
  await expect(page.locator(".fallbackCore")).toBeInViewport();
  const initialFallbackGeometry = await page.evaluate(() => {
    const shell = document.querySelector<HTMLElement>(".sceneShell.fallbackMode");
    const fallback = document.querySelector<HTMLElement>(".sceneFallback");
    const core = document.querySelector<HTMLElement>(".fallbackCore");
    if (!shell || !fallback || !core) throw new Error("fallback geometry is unavailable");
    const shellRect = shell.getBoundingClientRect();
    const fallbackRect = fallback.getBoundingClientRect();
    const coreRect = core.getBoundingClientRect();
    return {
      visibleTop: Math.max(shellRect.top, fallbackRect.top),
      visibleBottom: Math.min(shellRect.bottom, fallbackRect.bottom),
      coreTop: coreRect.top,
      coreBottom: coreRect.bottom,
      fallbackScrollTop: fallback.scrollTop
    };
  });
  expect(initialFallbackGeometry.fallbackScrollTop).toBe(0);
  expect(initialFallbackGeometry.coreTop).toBeGreaterThanOrEqual(initialFallbackGeometry.visibleTop);
  expect(initialFallbackGeometry.coreBottom).toBeLessThanOrEqual(initialFallbackGeometry.visibleBottom);
  const fallbackEvidence = await waitForRuntimePerformance(page, { minimumSamples: 0 });
  expect(fallbackEvidence.activeDevice).toBe("mobile");
  expect(fallbackEvidence.counters.fallbackReason).toBe("reduced_motion");
  expect(fallbackEvidence.counters.particles).toBe(0);
  expect(fallbackEvidence.evaluations.mobile?.normal.status).toBe("fallback");

  const group = page.locator(".fallbackGroupLink:not(.emptyFacet)").first();
  await expect(group).toBeVisible();
  await group.tap();
  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/);

  const node = page.locator(".fallbackNode:not(.groupNode)").first();
  await expect(node).toBeVisible();
  await node.tap();
  await expect(page.locator(".pageReader")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".quadrantCompass")).toBeHidden();
  expect(await page.locator(".sceneShell").evaluate((shell) => shell.scrollWidth - shell.clientWidth)).toBeLessThanOrEqual(1);
  const close = page.locator(".pageReader .readerClose").last();
  await expectTouchTarget(close);
  await close.tap();
  await expect(page.locator(".pageReader")).toHaveCount(0);
  await attachViewportScreenshot(page, testInfo, "webkit-mobile-fallback");
});

test("WebKit mobile keeps semantic overlay tokens and geometry stable", async ({ page }, testInfo) => {
  await prepareMobileWorld(page, "/demo/w/quadrants?center=root-alex-rivera&overlay=attention");
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });
  const evidence = await expectOverlayEncodingMatrix(page, { fallback: false });
  await testInfo.attach("overlay-encoding-mobile.json", {
    body: Buffer.from(`${JSON.stringify(evidence, null, 2)}\n`, "utf8"),
    contentType: "application/json"
  });
  await attachViewportScreenshot(page, testInfo, "webkit-mobile-overlay-quality");
});

test("WebKit mobile publishes bounded real render counters and passes normal/stress budgets", async ({ page }, testInfo) => {
  await prepareMobileWorld(page);
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });
  const evidence = await waitForRuntimePerformance(page, { minimumSamples: 120 });
  expect(evidence.activeDevice).toBe("mobile");
  expect(evidence.sampleCount).toBeGreaterThanOrEqual(evidence.samplePolicy.minimumSamples);
  expect(evidence.sampleCount).toBeLessThanOrEqual(evidence.samplePolicy.capacity);
  expect(evidence.counters.sourceNodes).toBeGreaterThan(0);
  expect(evidence.counters.interactiveNodes).toBeGreaterThan(0);
  expect(evidence.counters.labels).toBeGreaterThan(0);
  expect(evidence.counters.fallbackReason).toBeNull();
  expect(evidence.counters.frameTimeMedianMs).toBeGreaterThan(0);
  expect(evidence.counters.frameTimeP95Ms).toBeGreaterThan(0);
  for (const scenario of ["normal", "stress"] as const) {
    expect(evidence.evaluations.mobile?.[scenario].violations, `mobile ${scenario}`).toEqual([]);
    expect(evidence.evaluations.mobile?.[scenario].status, `mobile ${scenario}`).not.toBe("blocked");
  }
  await testInfo.attach("runtime-performance-mobile.json", {
    body: Buffer.from(`${JSON.stringify(evidence, null, 2)}\n`, "utf8"),
    contentType: "application/json"
  });
});
