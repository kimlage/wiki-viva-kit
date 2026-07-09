import { expect, resetRuntimePerformanceWindow, test, waitForRuntimePerformance } from "./fixtures";

test("Chromium desktop publishes bounded real render counters and passes normal/stress budgets", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
  });
  await page.goto("/demo/w/quadrants?center=root-alex-rivera");
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });

  // Warm the browser, renderer, shaders and route transition in a complete
  // bounded window. That window is deliberately discarded: the v8 contract is
  // sustained interaction p95, never cold-start/navigation or one lucky frame.
  await waitForRuntimePerformance(page, { minimumSamples: 120, timeout: 30_000 });
  await resetRuntimePerformanceWindow(page);
  await page.locator(".sceneShell canvas").hover({ position: { x: 640, y: 430 } });

  // The verdict is the next complete 120-frame window during stable pointer
  // interaction. The evidence attachment retains sample count, median and p95.
  const evidence = await waitForRuntimePerformance(page, { minimumSamples: 120 });

  expect(evidence.activeDevice).toBe("desktop");
  expect(evidence.sampleCount).toBeGreaterThanOrEqual(evidence.samplePolicy.minimumSamples);
  expect(evidence.sampleCount).toBeLessThanOrEqual(evidence.samplePolicy.capacity);
  expect(evidence.counters.sourceNodes).toBeGreaterThan(0);
  expect(evidence.counters.interactiveNodes).toBeGreaterThan(0);
  expect(evidence.counters.relationLines).toBeGreaterThanOrEqual(0);
  expect(evidence.counters.labels).toBeGreaterThan(0);
  expect(evidence.counters.particles).toBeGreaterThanOrEqual(0);
  expect(evidence.counters.fallbackReason).toBeNull();
  expect(evidence.counters.frameTimeMedianMs).toBeGreaterThan(0);
  expect(evidence.counters.frameTimeP95Ms).toBeGreaterThan(0);
  for (const scenario of ["normal", "stress"] as const) {
    expect(evidence.evaluations.desktop?.[scenario].violations, `desktop ${scenario}`).toEqual([]);
    expect(evidence.evaluations.desktop?.[scenario].status, `desktop ${scenario}`).not.toBe("blocked");
  }
  await testInfo.attach("runtime-performance-desktop.json", {
    body: Buffer.from(`${JSON.stringify(evidence, null, 2)}\n`, "utf8"),
    contentType: "application/json"
  });
});
