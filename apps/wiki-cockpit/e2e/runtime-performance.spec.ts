import {
  expect,
  expectStablePerformanceBudgetFallback,
  resetRuntimePerformanceWindow,
  test,
  waitForSettledRuntimePerformance,
  type RuntimePerformanceEvidence
} from "./fixtures";
import type { Page } from "@playwright/test";

const DESKTOP_FRAME_P95_BUDGET_MS = 33.33;
const SCENARIOS = [
  { id: "normal_operations", budget: "normal", sourceNodes: 107 },
  { id: "dense_stress", budget: "stress", sourceNodes: 378 }
] as const;

async function hoverClearCanvasPoint(page: Page) {
  const canvas = page.locator(".sceneShell canvas");
  const point = await canvas.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const candidates = [
      [0.5, 0.82], [0.2, 0.75], [0.8, 0.75], [0.5, 0.56],
      [0.12, 0.56], [0.88, 0.56], [0.3, 0.34], [0.7, 0.34]
    ];
    for (const [xFraction, yFraction] of candidates) {
      const x = rect.left + rect.width * xFraction;
      const y = rect.top + rect.height * yFraction;
      if (document.elementFromPoint(x, y) === element) {
        return { x: rect.width * xFraction, y: rect.height * yFraction };
      }
    }
    throw new Error("No pointer-safe canvas point remained after HUD and semantic labels were laid out");
  });
  await canvas.hover({ position: point });
}

// Recording a Playwright trace and video consumes the same CPU/GPU frame time
// this file measures. Keep the product budget strict, but remove observer
// overhead from the bounded measurement window. The JSON telemetry attachment
// remains the authoritative failure evidence for these tests.
test.use({ trace: "off", video: "off" });

for (const scenario of SCENARIOS) {
  test(`Chromium desktop publishes bounded real render counters for ${scenario.id}`, async ({ page }, testInfo) => {
    test.setTimeout(110_000);
    await page.addInitScript(() => {
      window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
      window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    });
    await page.goto(
      `/demo/w/quadrants?center=root-alex-rivera&demo_scenario=${scenario.id}&tour=0`
    );
    await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });

    // Warm the browser, renderer, shaders and route transition in a complete
    // bounded window. A healthy 3D result is followed by one bounded hover/JIT
    // warm-up and then a clean sustained window. This keeps the strict p95
    // budget while excluding one-time shader/GC work caused by the first real
    // pointer interaction. A frame-only sustained rejection must still settle
    // into its session-latched 2D fallback. Each scenario gets its own context.
    const warmEvidence = await waitForSettledRuntimePerformance(page, { timeout: 40_000 });
    await testInfo.attach(`runtime-performance-desktop-${scenario.id}-warm.json`, {
      body: Buffer.from(`${JSON.stringify(warmEvidence, null, 2)}\n`, "utf8"),
      contentType: "application/json"
    });

    let evidence: RuntimePerformanceEvidence = warmEvidence;
    if (warmEvidence.counters.fallbackReason === null) {
      await resetRuntimePerformanceWindow(page);
      await hoverClearCanvasPoint(page);
      const interactionWarmEvidence = await waitForSettledRuntimePerformance(page, { timeout: 45_000 });
      await testInfo.attach(`runtime-performance-desktop-${scenario.id}-interaction-warm.json`, {
        body: Buffer.from(`${JSON.stringify(interactionWarmEvidence, null, 2)}\n`, "utf8"),
        contentType: "application/json"
      });
      evidence = interactionWarmEvidence;
      if (interactionWarmEvidence.counters.fallbackReason === null) {
        await resetRuntimePerformanceWindow(page);
        evidence = await waitForSettledRuntimePerformance(page, { timeout: 45_000 });
      }
    }
    await testInfo.attach(`runtime-performance-desktop-${scenario.id}.json`, {
      body: Buffer.from(`${JSON.stringify(evidence, null, 2)}\n`, "utf8"),
      contentType: "application/json"
    });

    expect(evidence.activeDevice).toBe("desktop");
    expect(evidence.sampleCount).toBe(evidence.samplePolicy.capacity);
    expect(evidence.counters.sourceNodes).toBe(scenario.sourceNodes);
    expect(evidence.counters.interactiveNodes).toBeGreaterThan(0);
    expect(evidence.counters.relationLines).toBeGreaterThanOrEqual(0);
    expect(evidence.counters.labels).toBeGreaterThan(0);
    const performanceFallback = evidence.counters.fallbackReason === "performance_budget";
    if (performanceFallback) {
      expect(evidence.counters.particles).toBe(0);
      expect(evidence.counters.frameTimeMedianMs).toBeGreaterThan(0);
      expect(evidence.counters.frameTimeMedianMs ?? 0).toBeGreaterThan(
        1_000 / evidence.evaluations.desktop!.normal.budget.minimumFps
      );
      expect(evidence.counters.frameTimeP95Ms).toBeGreaterThan(DESKTOP_FRAME_P95_BUDGET_MS);
      expect(evidence.evaluations.desktop?.normal.status).toBe("fallback");
      expect(evidence.evaluations.desktop?.normal.violations.length).toBeGreaterThan(0);
      expect(evidence.evaluations.desktop?.normal.violations.every((violation) =>
        violation.startsWith("frameTimeP95Ms:")
      )).toBe(true);
      expect(evidence.evaluations.desktop?.[scenario.budget].status).toBe("fallback");
      await expectStablePerformanceBudgetFallback(page);

      const group = page.locator(".fallbackGroupLink:not(.emptyFacet)").first();
      await expect(group).toBeVisible();
      await group.click();
      await expect(page.locator(".sceneShell")).toHaveAttribute("data-scene-fallback-reason", "performance_budget");
      await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-fallback-active", "true");
    } else {
      expect(evidence.counters.fallbackReason).toBeNull();
      expect(evidence.counters.particles).toBeGreaterThanOrEqual(0);
      expect(evidence.counters.frameTimeMedianMs).toBeGreaterThan(0);
      expect(evidence.counters.frameTimeP95Ms).toBeGreaterThan(0);
      expect(evidence.counters.frameTimeP95Ms ?? Number.POSITIVE_INFINITY).toBeLessThanOrEqual(
        DESKTOP_FRAME_P95_BUDGET_MS
      );
      expect(evidence.evaluations.desktop?.[scenario.budget].violations, `desktop ${scenario.budget}`).toEqual([]);
      expect(evidence.evaluations.desktop?.[scenario.budget].status, `desktop ${scenario.budget}`).not.toBe("blocked");
      await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/);
      await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-fallback-active", "false");
      await expect(page.locator(".sceneShell canvas")).toHaveCount(1);
    }
  });
}
