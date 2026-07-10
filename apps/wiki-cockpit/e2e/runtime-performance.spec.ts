import { expect, resetRuntimePerformanceWindow, test, waitForRuntimePerformance } from "./fixtures";

const DESKTOP_FRAME_P95_BUDGET_MS = 33.33;
const SCENARIOS = [
  { id: "normal_operations", budget: "normal", sourceNodes: 107 },
  { id: "dense_stress", budget: "stress", sourceNodes: 378 }
] as const;

// Recording a Playwright trace and video consumes the same CPU/GPU frame time
// this file measures. Keep the product budget strict, but remove observer
// overhead from the bounded measurement window. The JSON telemetry attachment
// remains the authoritative failure evidence for these tests.
test.use({ trace: "off", video: "off" });

for (const scenario of SCENARIOS) {
  test(`Chromium desktop publishes bounded real render counters for ${scenario.id}`, async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    await page.addInitScript(() => {
      window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
      window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    });
    await page.goto(
      `/demo/w/quadrants?center=root-alex-rivera&demo_scenario=${scenario.id}&tour=0`
    );
    await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });

    // Warm the browser, renderer, shaders and route transition in a complete
    // bounded window. That window is deliberately discarded: the v8 contract
    // is sustained interaction p95, never cold-start/navigation or one lucky
    // frame. Each data scenario gets its own page and measurement window.
    await waitForRuntimePerformance(page, { minimumSamples: 120, timeout: 30_000 });
    await resetRuntimePerformanceWindow(page);
    await page.locator(".sceneShell canvas").hover({ position: { x: 640, y: 430 } });

    const evidence = await waitForRuntimePerformance(page, { minimumSamples: 120, timeout: 40_000 });
    await testInfo.attach(`runtime-performance-desktop-${scenario.id}.json`, {
      body: Buffer.from(`${JSON.stringify(evidence, null, 2)}\n`, "utf8"),
      contentType: "application/json"
    });

    expect(evidence.activeDevice).toBe("desktop");
    expect(evidence.sampleCount).toBeGreaterThanOrEqual(evidence.samplePolicy.minimumSamples);
    expect(evidence.sampleCount).toBeLessThanOrEqual(evidence.samplePolicy.capacity);
    expect(evidence.counters.sourceNodes).toBe(scenario.sourceNodes);
    expect(evidence.counters.interactiveNodes).toBeGreaterThan(0);
    expect(evidence.counters.relationLines).toBeGreaterThanOrEqual(0);
    expect(evidence.counters.labels).toBeGreaterThan(0);
    expect(evidence.counters.particles).toBeGreaterThanOrEqual(0);
    expect(evidence.counters.fallbackReason).toBeNull();
    expect(evidence.counters.frameTimeMedianMs).toBeGreaterThan(0);
    expect(evidence.counters.frameTimeP95Ms).toBeGreaterThan(0);
    expect(evidence.counters.frameTimeP95Ms ?? Number.POSITIVE_INFINITY).toBeLessThanOrEqual(
      DESKTOP_FRAME_P95_BUDGET_MS
    );
    expect(evidence.evaluations.desktop?.[scenario.budget].violations, `desktop ${scenario.budget}`).toEqual([]);
    expect(evidence.evaluations.desktop?.[scenario.budget].status, `desktop ${scenario.budget}`).not.toBe("blocked");
  });
}
