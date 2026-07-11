import type { Locator, Page } from "@playwright/test";
import {
  attachViewportScreenshot,
  expect,
  expectStablePerformanceBudgetFallback,
  test,
  waitForRuntimePerformance,
  waitForSettledRuntimePerformance
} from "./fixtures";
import { expectSpatialCardsWithinSafeArea } from "./spatial-assertions";
import { expectOverlayEncodingMatrix } from "./overlay-assertions";

// Video/trace recording at a 3x mobile device scale materially taxes the same
// WebKit render loop used by the runtime budget test. CI still captures the
// automatic screenshot plus redacted JSON evidence for every failure; local
// runs retain the richer interactive artifacts for diagnosis.
test.use({
  trace: process.env.CI ? "off" : "retain-on-failure",
  video: process.env.CI ? "off" : "retain-on-failure"
});

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
  await expect(page.locator(".appDockPresence")).toHaveCount(0);

  await page.locator(".dockButton").filter({ hasText: /Create|Criar/ }).tap();
  await expect(page).toHaveURL(/[?&]dock=create/);
  await expect(page.locator(".spatialCardType")).toHaveCount(7, { timeout: 10_000 });
  await expectSpatialCardsWithinSafeArea(page, { expectedPrimary: 7, expectedTotal: 8 });
  const createClose = page.locator(".seedTitle .questPlateClose");
  await expectTouchTarget(createClose);
  await createClose.tap();
  await expect(page).not.toHaveURL(/[?&]dock=create/);
  await expect(page.locator(".appDockPresence")).toHaveCount(0);

  for (const longTitle of [
    "Evidence shelf clarifies source-backed work",
    "Calendário calmo rende trabalho melhor"
  ]) {
    await page.locator(".commandSearch input").fill(longTitle);
    await page.locator(".commandSearch input").press("Enter");
    await expect(page.locator(".pageReader")).toBeVisible({ timeout: 10_000 });
    // The 250 ms query debounce must not replay the pre-close Create route
    // after Enter has committed query + reader as one transaction.
    await page.waitForTimeout(350);
    await expect(page.locator(".pageReader")).toBeVisible();
    await expect(page).not.toHaveURL(/[?&]dock=/);
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

  // Also exercise the branch where the 250 ms debounce commits `q` before
  // Enter. Closing, clearing and submitting the identical title again must
  // release the submitted-draft marker instead of suppressing future search.
  const repeatedTitle = "Evidence shelf clarifies source-backed work";
  const search = page.locator(".commandSearch input");
  await search.fill(repeatedTitle);
  await expect.poll(() => page.evaluate(() => new URLSearchParams(window.location.search).get("q"))).toBe(repeatedTitle);
  await search.press("Enter");
  await expect(page.locator(".pageReader")).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(350);
  await expect(page.locator(".pageReader")).toBeVisible();
  await expect(page.locator(".readerHead h2")).toHaveText(repeatedTitle);
  await page.keyboard.press("Escape");
  await expect(page.locator(".pageReader")).toHaveCount(0);

  await search.fill("");
  await expect.poll(() => page.evaluate(() => new URLSearchParams(window.location.search).get("q"))).toBeNull();
  await search.fill(repeatedTitle);
  await expect.poll(() => page.evaluate(() => new URLSearchParams(window.location.search).get("q"))).toBe(repeatedTitle);
  await search.press("Enter");
  await expect(page.locator(".pageReader")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".readerHead h2")).toHaveText(repeatedTitle);
  await expect(page).not.toHaveURL(/[?&]dock=/);
  await attachViewportScreenshot(page, testInfo, "webkit-mobile-touch-flow");
});

test("WebKit mobile opens a semantic quadrant collection and reaches a real center in two taps", async ({ page }, testInfo) => {
  await prepareMobileWorld(
    page,
    "/demo/w?center=root-alex-rivera&view=quadrants&lens=q2_pratica&overlay=actions&tour=0"
  );
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator(".sceneShell canvas")).toHaveCount(1, { timeout: 20_000 });
  await page.evaluate(() => {
    (window as Window & { __mobileQuadrantCanvas?: HTMLCanvasElement }).__mobileQuadrantCanvas =
      document.querySelector<HTMLCanvasElement>(".sceneShell canvas") ?? undefined;
  });

  const group = page.getByRole("button", { name: "sources & evidence", exact: true });
  await expectTouchTarget(group);
  await group.tap();

  const summary = page.locator('[data-world-group-summary="family:source"]');
  await expect(summary).toHaveAttribute("data-world-group-count", "13");
  await expect(summary).toContainText("Systems, files, and records");
  await expectMobileViewportBounded(page, ".familyCollectionPanel");
  const examples = summary.locator("[data-world-member-id]");
  await expect(examples).toHaveCount(3);
  for (let index = 0; index < 3; index += 1) await expectTouchTarget(examples.nth(index));

  const firstMember = examples.first();
  const memberId = await firstMember.getAttribute("data-world-member-id");
  expect(memberId).toBeTruthy();
  await firstMember.tap();
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", memberId!);
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", "all");
  await expect(page.locator(".worldBreadcrumbs")).toContainText("Action ledger export");
  expect(await page.evaluate(() =>
    document.querySelector(".sceneShell canvas") ===
    (window as Window & { __mobileQuadrantCanvas?: HTMLCanvasElement }).__mobileQuadrantCanvas
  )).toBe(true);
  await expectMobileViewportBounded(page, ".sceneShell");
  await attachViewportScreenshot(page, testInfo, "webkit-mobile-quadrant-collection");
});

test("WebKit mobile keeps the visible mission, quadrant controls and real Q2 targets pointer-safe", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.removeItem("wikiCockpitMissionCard.v1");
    window.localStorage.removeItem("wiki-cockpit.missionCard");
  });
  await page.setViewportSize({ width: 390, height: 664 });
  await page.goto(
    "/demo/w?center=root-alex-rivera&view=quadrants&lens=q2_pratica&overlay=actions&tour=0"
  );
  await expect(page.getByText("Loading cockpit")).toHaveCount(0, { timeout: 20_000 });
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator(".sceneShell canvas")).toHaveCount(1, { timeout: 20_000 });
  await waitForSettledRuntimePerformance(page);
  await expect(page.locator(".worldMissionSlim")).toBeVisible();
  await expect(page.locator(".quadrantCompass")).toBeVisible();

  const rendererMode = await page.evaluate(() => {
    const renderer = document.querySelector(".sceneShell canvas, .sceneShell .sceneFallback");
    if (!renderer) throw new Error("adaptive renderer is unavailable");
    (window as Window & { __missionQuadrantRenderer?: Element }).__missionQuadrantRenderer = renderer;
    return renderer.matches("canvas") ? "3d" : "performance_budget";
  });
  expect(["3d", "performance_budget"]).toContain(rendererMode);
  if (rendererMode === "performance_budget") await expectStablePerformanceBudgetFallback(page);

  const targetIds = [
    "root-alex-rivera",
    "source-action-ledger",
    "event-ingest-agenda-2026-07",
    "family:source",
    "family:event"
  ] as const;
  for (const id of targetIds) {
    const target = page.locator(`[data-world-target-id="${id}"]`);
    await expect(target).toHaveCount(1);
    if (rendererMode === "performance_budget") await target.scrollIntoViewIfNeeded();
    await expectTouchTarget(target);
  }

  const overlaps = rendererMode === "3d" ? await page.evaluate((ids) => {
    const rect = (element: Element) => element.getBoundingClientRect();
    const intersects = (left: DOMRect, right: DOMRect) =>
      Math.min(left.right, right.right) - Math.max(left.left, right.left) > 1 &&
      Math.min(left.bottom, right.bottom) - Math.max(left.top, right.top) > 1;
    const blockers = [".worldMissionSlim", ".quadrantCompass", ".worldCommandBar", ".radarStatusStrip"]
      .flatMap((selector) => Array.from(document.querySelectorAll(selector)))
      .filter((element) => {
        const style = getComputedStyle(element);
        const bounds = rect(element);
        return style.display !== "none" && style.visibility !== "hidden" && bounds.width > 0 && bounds.height > 0;
      });
    const targets = ids.flatMap((id) => {
      const target = document.querySelector(`[data-world-target-id="${id}"]`);
      return target ? [{ id, target, bounds: rect(target) }] : [];
    });
    return ids.flatMap((id) => {
      const entry = targets.find((candidate) => candidate.id === id);
      if (!entry) return [{ id, blocker: "missing" }];
      const outsideViewport =
        entry.bounds.left < 0 || entry.bounds.right > window.innerWidth ||
        entry.bounds.top < 0 || entry.bounds.bottom > window.innerHeight;
      const surfaceOverlaps = blockers
        .filter((blocker) => intersects(entry.bounds, rect(blocker)))
        .map((blocker) => ({ id, blocker: blocker.className }));
      const targetOverlaps = targets
        .filter((candidate) => candidate.id !== id && intersects(entry.bounds, candidate.bounds))
        .map((candidate) => ({ id, blocker: `target:${candidate.id}` }));
      return [
        ...(outsideViewport ? [{ id, blocker: "viewport" }] : []),
        ...surfaceOverlaps,
        ...targetOverlaps
      ];
    });
  }, targetIds) : [];
  expect(overlaps).toEqual([]);

  const expectRendererContinuity = async () => {
    expect(await page.evaluate((mode) => {
      const current = mode === "3d"
        ? document.querySelector(".sceneShell canvas")
        : document.querySelector(".sceneShell .sceneFallback");
      return current ===
        (window as Window & { __missionQuadrantRenderer?: Element }).__missionQuadrantRenderer;
    }, rendererMode)).toBe(true);
  };

  const returnToQ2 = async () => {
    await page.goBack();
    await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", "root-alex-rivera");
    await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", "q2_pratica");
    await expect(page.locator(".worldMissionSlim")).toBeVisible();
    await expectRendererContinuity();
  };

  await page.locator('[data-world-target-id="source-action-ledger"]').tap();
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", "source-action-ledger");
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", "all");
  await returnToQ2();

  await page.locator('[data-world-target-id="event-ingest-agenda-2026-07"]').tap();
  await expect(page.locator(".pageReader")).toBeVisible();
  await expect(page).toHaveURL(/[?&]page=event-ingest-agenda-2026-07(?:&|$)/);
  await returnToQ2();

  await page.locator('[data-world-target-id="family:source"]').tap();
  await expect(page.locator('[data-world-group-summary="family:source"]')).toBeVisible();
  await returnToQ2();

  await page.locator('[data-world-target-id="family:event"]').tap();
  await expect(page.locator('[data-world-group-summary="family:event"]')).toBeVisible();
  await returnToQ2();

  await page.locator('[data-world-target-id="root-alex-rivera"]').tap();
  await expect(page.locator(".pageReader")).toBeVisible();
  await expectRendererContinuity();
});

test("WebKit mobile keeps the same semantic route in reduced-motion fallback", async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await prepareMobileWorld(page, "/demo/w/quadrants?center=root-alex-rivera&lens=pratica");

  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator("canvas")).toHaveCount(0);
  await expect(page).not.toHaveURL(/[?&]visual=1/);
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", "root-alex-rivera");
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", /pratica|q2_pratica/);
  await expect(page.locator(".worldMissionSlim")).toBeVisible();
  await expect(page.locator(".quadrantCompass")).toBeVisible();
  await expect(page.locator(".quadrantSeed")).toBeHidden();
  await expect(page.locator(".worldCommandBar .dockButton").filter({ hasText: /Create|Criar/ })).toBeVisible();
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

  const group = page.locator('[data-world-target-id="family:source"]');
  await expect(group).toHaveCount(1);
  await group.scrollIntoViewIfNeeded();
  await expect(group).toBeVisible();
  await group.tap();
  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/);
  await expect(page.locator('[data-world-group-summary="family:source"]')).toBeVisible();
  await page.goBack();
  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/);

  const node = page.locator(".fallbackNode:not(.groupNode)").first();
  await expect(node).toBeVisible();
  await node.tap();
  await expect(page.locator(".pageReader")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".quadrantCompass")).toBeHidden();
  const horizontalScrollContract = await page.locator(".sceneShell").evaluate((shell) => ({
    internalOverflow: shell.scrollWidth - shell.clientWidth,
    overflowX: getComputedStyle(shell).overflowX,
    documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    windowScrollX: window.scrollX
  }));
  // Fractional WebKit layout may leave up to a few non-painted internal CSS
  // pixels. The user-facing contract is stricter and more direct: the shell
  // clips the x axis, the document has no x overflow and the viewport did not
  // move horizontally.
  expect(horizontalScrollContract.internalOverflow).toBeLessThanOrEqual(4);
  expect(horizontalScrollContract.overflowX).toMatch(/^(hidden|clip)$/);
  expect(horizontalScrollContract.documentOverflow).toBeLessThanOrEqual(1);
  expect(horizontalScrollContract.windowScrollX).toBe(0);
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

test("WebKit mobile either passes the sustained frame budget or switches to the explicit 2D map", async ({ page }, testInfo) => {
  test.setTimeout(100_000);
  await prepareMobileWorld(page);
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });
  const evidence = await waitForSettledRuntimePerformance(page);
  expect(evidence.activeDevice).toBe("mobile");
  expect(evidence.sampleCount).toBeLessThanOrEqual(evidence.samplePolicy.capacity);
  expect(evidence.counters.sourceNodes).toBeGreaterThan(0);
  expect(evidence.counters.interactiveNodes).toBeGreaterThan(0);
  expect(evidence.counters.labels).toBeGreaterThan(0);
  const performanceFallback = evidence.counters.fallbackReason === "performance_budget";
  if (performanceFallback) {
    expect(evidence.sampleCount).toBe(evidence.samplePolicy.capacity);
    expect(evidence.counters.particles).toBe(0);
    expect(evidence.counters.frameTimeMedianMs ?? 0).toBeGreaterThan(
      1_000 / evidence.evaluations.mobile!.normal.budget.minimumFps
    );
    expect(evidence.evaluations.mobile?.normal.status).toBe("fallback");
    expect(evidence.evaluations.mobile?.normal.violations.length).toBeGreaterThan(0);
    expect(evidence.evaluations.mobile?.normal.violations.every((violation) =>
      violation.startsWith("frameTimeP95Ms:")
    )).toBe(true);
    await expectStablePerformanceBudgetFallback(page);

    // Route changes must preserve the same session verdict too.
    const group = page.locator(".fallbackGroupLink:not(.emptyFacet)").first();
    await expect(group).toBeVisible();
    await group.tap();
    await expect(page.locator(".sceneShell")).toHaveAttribute("data-scene-fallback-reason", "performance_budget");
    await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-fallback-active", "true");
  } else {
    expect(evidence.sampleCount).toBe(evidence.samplePolicy.capacity);
    expect(evidence.counters.fallbackReason).toBeNull();
    expect(evidence.counters.frameTimeMedianMs).toBeGreaterThan(0);
    expect(evidence.counters.frameTimeP95Ms).toBeGreaterThan(0);
    for (const scenario of ["normal", "stress"] as const) {
      expect(evidence.evaluations.mobile?.[scenario].violations, `mobile ${scenario}`).toEqual([]);
      expect(evidence.evaluations.mobile?.[scenario].status, `mobile ${scenario}`).not.toBe("blocked");
    }
  }
  expect(evidence.evaluations.mobile?.normal.status).not.toBe("blocked");
  await testInfo.attach("runtime-performance-mobile.json", {
    body: Buffer.from(`${JSON.stringify(evidence, null, 2)}\n`, "utf8"),
    contentType: "application/json"
  });
});
