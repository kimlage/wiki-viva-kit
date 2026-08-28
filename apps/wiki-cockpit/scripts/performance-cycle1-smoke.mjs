import fs from "node:fs";
import { chromium } from "@playwright/test";

const baseURL = process.env.WIKI_PERFORMANCE_BASE_URL;
const output = process.env.WIKI_PERFORMANCE_OUTPUT;
if (!baseURL || !output) throw new Error("WIKI_PERFORMANCE_BASE_URL and WIKI_PERFORMANCE_OUTPUT are required");

const route = "/demo/w?view=quadrants&center=root-alex-rivera&demo_scenario=normal_operations&tour=0";

async function measureDevice(browser, name, viewport, isMobile) {
  const context = await browser.newContext({
    viewport,
    screen: viewport,
    deviceScaleFactor: isMobile ? 2 : 1,
    isMobile,
    hasTouch: isMobile,
    locale: "pt-BR"
  });
  const page = await context.newPage();
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.__wikiPerformanceMetrics = [];
    window.__wikiLongTasks = [];
    window.__wikiLongTaskObserverSupported = false;
    globalThis.__WIKI_SNAPSHOT_PERFORMANCE_OBSERVER__ = (metric) => {
      window.__wikiPerformanceMetrics.push(metric);
    };
    if (typeof PerformanceObserver !== "undefined") {
      try {
        const observer = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            window.__wikiLongTasks.push({ startTime: entry.startTime, duration: entry.duration });
          }
        });
        observer.observe({ type: "longtask", buffered: true });
        window.__wikiLongTaskObserverSupported = true;
      } catch {
        // Metric remains explicitly unavailable below.
      }
    }
  });
  const navigationStarted = performance.now();
  await page.goto(`${baseURL}${route}`, { waitUntil: "domcontentloaded" });
  await page.locator(".worldWorkspace").waitFor({ state: "visible", timeout: 30_000 });
  await page.locator(".worldWorkspace").waitFor({ state: "attached" });
  const reactReadyMs = performance.now() - navigationStarted;

  const runtimeOutput = page.locator('[data-testid="runtime-performance"]');
  let runtime = null;
  try {
    await page.waitForFunction(() => {
      const value = document.querySelector('[data-testid="runtime-performance"]')?.textContent || "";
      if (!value) return false;
      try { return JSON.parse(value).counters?.frameTimeP95Ms != null; } catch { return false; }
    }, undefined, { timeout: 12_000 });
    runtime = JSON.parse(await runtimeOutput.textContent());
  } catch {
    runtime = null;
  }

  const searchStarted = performance.now();
  const search = page.getByRole("combobox", { name: "Search content" });
  await search.fill("Alex");
  const firstOption = page.getByRole("option").first();
  let searchLatencyMs = null;
  let selectionLatencyMs = null;
  let selectionReason = null;
  try {
    await firstOption.waitFor({ state: "visible", timeout: 8_000 });
    searchLatencyMs = performance.now() - searchStarted;
    const beforeURL = page.url();
    const selectionStarted = performance.now();
    await firstOption.click();
    await page.waitForFunction((previous) => location.href !== previous || Boolean(document.querySelector(".pageReader")), beforeURL, { timeout: 8_000 });
    selectionLatencyMs = performance.now() - selectionStarted;
  } catch (error) {
    selectionReason = `unavailable:${error instanceof Error ? error.name : "unknown"}`;
  }

  if (await page.locator(".readerClose").count()) {
    await page.locator(".readerClose").first().click().catch(() => {});
  }
  await search.fill("").catch(() => {});
  const interactionStarted = performance.now();
  const radar = page.locator('[data-view-option="radar"]');
  let firstInteractionMs = null;
  let firstInteractionReason = null;
  try {
    await radar.click({ timeout: 8_000 });
    await page.locator('.worldWorkspace[data-world-view="radar"]').waitFor({ timeout: 8_000 });
    firstInteractionMs = performance.now() - interactionStarted;
  } catch (error) {
    firstInteractionReason = `unavailable:${error instanceof Error ? error.name : "unknown"}`;
  }

  const timelineStarted = performance.now();
  let chronoscopeMs = null;
  let chronoscopeReason = null;
  try {
    await page.locator('[data-view-option="timeline"]').click({ timeout: 8_000 });
    await page.locator(".timelineSurface").waitFor({ state: "visible", timeout: 15_000 });
    chronoscopeMs = performance.now() - timelineStarted;
  } catch (error) {
    chronoscopeReason = `unavailable:${error instanceof Error ? error.name : "unknown"}`;
  }

  const browserMetrics = await page.evaluate(async () => {
    const resources = performance.getEntriesByType("resource").map((entry) => ({
      name: entry.name,
      duration: entry.duration,
      transferSize: entry.transferSize || 0,
      decodedBodySize: entry.decodedBodySize || 0
    }));
    let heapBytes = null;
    let heapReason = null;
    if (performance.memory?.usedJSHeapSize) {
      heapBytes = performance.memory.usedJSHeapSize;
    } else if (typeof performance.measureUserAgentSpecificMemory === "function") {
      try { heapBytes = (await performance.measureUserAgentSpecificMemory()).bytes; }
      catch { heapReason = "measureUserAgentSpecificMemory_rejected"; }
    } else {
      heapReason = "heap_api_unavailable";
    }
    return {
      snapshotMetrics: window.__wikiPerformanceMetrics || [],
      longTasks: window.__wikiLongTasks || [],
      longTaskObserverSupported: Boolean(window.__wikiLongTaskObserverSupported),
      longTaskReason: window.__wikiLongTaskObserverSupported ? null : "longtask_observer_unavailable",
      resources,
      transferBytes: resources.reduce((sum, entry) => sum + entry.transferSize, 0),
      decodedBytes: resources.reduce((sum, entry) => sum + entry.decodedBodySize, 0),
      heapBytes,
      heapReason
    };
  });
  await context.close();
  return {
    device: name,
    viewport,
    reactReadyMs,
    searchLatencyMs,
    searchReason: searchLatencyMs == null ? selectionReason : null,
    searchSelectionMs: selectionLatencyMs,
    searchSelectionReason: selectionReason,
    centerSelectionMs: null,
    centerSelectionReason: "not_exercised_by_short_smoke_without_pointer_safe_center_target",
    firstInteractionMs,
    firstInteractionReason,
    chronoscopeMs,
    chronoscopeReason,
    frameP95Ms: runtime?.counters?.frameTimeP95Ms ?? null,
    runtimeReason: runtime ? null : "bounded_frame_window_not_ready_in_short_smoke",
    runtime,
    ...browserMetrics
  };
}

const browser = await chromium.launch({ headless: true, args: ["--enable-gpu"] });
try {
  const measurements = [];
  measurements.push(await measureDevice(browser, "desktop", { width: 1280, height: 900 }, false));
  measurements.push(await measureDevice(browser, "mobile", { width: 390, height: 844 }, true));
  fs.writeFileSync(output, `${JSON.stringify({ schema_version: "wiki_performance_browser_smoke.v1", measurements }, null, 2)}\n`, "utf8");
} finally {
  await browser.close();
}
