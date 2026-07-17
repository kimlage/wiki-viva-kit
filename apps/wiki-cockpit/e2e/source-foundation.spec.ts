// Source-foundation journeys (plan §19.7, core set): the canonical
// view=sources route renders the SAME mounted canvas and center as the upper
// views but from the lower hemisphere; a station selection opens the
// SourceDock through the existing dock=source grammar; the upstream trace is
// ephemeral (never in the URL); Back/Forward and refresh restore the sources
// view; an overlay switch never relayouts the foundation; reduced motion
// serves the 2D fallback on the SAME route with the banded plan; labels are
// never mirrored; and the whole journey produces zero console errors.
//
// The §20 density counters ride the same runtime-performance evidence element
// the rest of the suite already reads, so this spec also proves the foundation
// census is measured over DERIVED primitives, not just source GraphNodes.

import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

test.describe.configure({ timeout: 60_000 });

const CANONICAL_SOURCES_URL = "/demo/w?view=sources&center=root-alex-rivera&tour=0";

type ConsoleErrorRow = { kind: "console" | "pageerror"; text: string };

function collectConsoleErrors(page: Page): ConsoleErrorRow[] {
  const rows: ConsoleErrorRow[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") rows.push({ kind: "console", text: message.text() });
  });
  page.on("pageerror", (error) => {
    rows.push({ kind: "pageerror", text: error.stack ?? error.message });
  });
  return rows;
}

async function prepareApp(page: Page, path: string) {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.goto(path);
}

async function prepareFoundationWorld(page: Page, path = CANONICAL_SOURCES_URL) {
  await prepareApp(page, path);
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator(".sceneShell canvas")).toHaveCount(1, { timeout: 20_000 });
  await expectFoundationPose(page);
}

async function expectFoundationPose(page: Page) {
  const scene = page.locator(".sceneShell");
  await expect(scene).toHaveAttribute("data-scene-perspective", "sources");
  await expect(scene).toHaveAttribute("data-camera-hemisphere", "lower", { timeout: 20_000 });
  await expect(scene).toHaveAttribute("data-world-spatial-profile", "source-foundation");
  await expect(scene).toHaveAttribute("data-world-plane", "foundation");
}

async function rememberCanvas(page: Page) {
  await page.evaluate(() => {
    const testWindow = window as Window & { __wikiFoundationCanvas?: HTMLCanvasElement };
    testWindow.__wikiFoundationCanvas = document.querySelector<HTMLCanvasElement>(".sceneShell canvas") ?? undefined;
  });
}

async function expectRememberedCanvas(page: Page) {
  await expect(page.locator(".sceneShell canvas")).toHaveCount(1);
  expect(await page.evaluate(() => {
    const testWindow = window as Window & { __wikiFoundationCanvas?: HTMLCanvasElement };
    return document.querySelector<HTMLCanvasElement>(".sceneShell canvas") === testWindow.__wikiFoundationCanvas;
  })).toBe(true);
}

// §10.9/§19.7 item 22: every scene label is a screen-space billboard. A
// mirrored label would need a negative determinant in its computed transform.
async function expectNoMirroredLabels(page: Page) {
  const mirrored = await page.evaluate(() => {
    const labels = [...document.querySelectorAll<HTMLElement>(".sceneHtmlLabel")];
    const negative: string[] = [];
    for (const label of labels) {
      for (const element of [label, ...label.querySelectorAll<HTMLElement>("*")]) {
        const transform = getComputedStyle(element).transform;
        if (!transform || transform === "none") continue;
        const match = transform.match(/matrix(?:3d)?\(([^)]+)\)/);
        if (!match) continue;
        const parts = match[1].split(",").map((value) => Number(value.trim()));
        // 2D matrix(a,b,c,d,e,f) → det = a*d − b*c; matrix3d uses the same
        // upper-left block at indices 0,1,4,5.
        const det = parts.length === 6 ? parts[0] * parts[3] - parts[1] * parts[2] : parts[0] * parts[5] - parts[1] * parts[4];
        if (det < 0) negative.push(`${element.className}:${transform}`);
      }
    }
    return negative;
  });
  expect(mirrored).toEqual([]);
}

test("canonical sources route keeps the same canvas, same center and crosses to the lower hemisphere", async ({ page }) => {
  const consoleErrors = collectConsoleErrors(page);
  await prepareApp(page, "/demo/w?view=quadrants&center=root-alex-rivera&tour=0");
  const workspace = page.locator(".worldWorkspace");
  const scene = page.locator(".sceneShell");
  await expect(scene).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator(".sceneShell canvas")).toHaveCount(1, { timeout: 20_000 });
  await expect(workspace).toHaveAttribute("data-world-center", "root-alex-rivera");
  await expect(scene).toHaveAttribute("data-camera-hemisphere", "upper");
  await rememberCanvas(page);

  // 1/2/3/4: canonical view=sources on the SAME canvas, same center, lower
  // hemisphere via the outer-arc path.
  await page.locator('[data-view-option="sources"]').click();
  await expect(page).toHaveURL(/[?&]view=sources(?:&|$)/);
  await expect(workspace).toHaveAttribute("data-world-view", "sources");
  await expect(workspace).toHaveAttribute("data-world-center", "root-alex-rivera");
  await expect(scene).toHaveAttribute("data-scene-center", "root-alex-rivera");
  await expectFoundationPose(page);
  await expect(scene).toHaveAttribute("data-camera-path", "outer_arc");
  await expectRememberedCanvas(page);
  await expectNoMirroredLabels(page);

  // 11: return to the upper view on the same canvas.
  await page.locator('[data-view-option="quadrants"]').click();
  await expect(workspace).toHaveAttribute("data-world-view", "quadrants");
  await expect(scene).toHaveAttribute("data-camera-hemisphere", "upper", { timeout: 20_000 });
  await expect(scene).toHaveAttribute("data-world-plane", "knowledge");
  await expectRememberedCanvas(page);

  // 12: browser Back/Forward restore each hemisphere on the same canvas.
  await page.goBack();
  await expect(workspace).toHaveAttribute("data-world-view", "sources");
  await expectFoundationPose(page);
  await expectRememberedCanvas(page);
  await page.goForward();
  await expect(workspace).toHaveAttribute("data-world-view", "quadrants");
  await expect(scene).toHaveAttribute("data-camera-hemisphere", "upper", { timeout: 20_000 });
  await expectRememberedCanvas(page);

  expect(consoleErrors).toEqual([]);
});

test("station selection opens the SourceDock, the upstream trace stays ephemeral and refresh restores the view", async ({ page }) => {
  const consoleErrors = collectConsoleErrors(page);
  await prepareFoundationWorld(page, "/demo/w?view=sources&center=root-alex-rivera&page=source-agenda&tour=0");

  // 5/7: §14.4 Enter on the selected source station opens its SourceDock via
  // the existing dock=source&src grammar — never a recenter.
  await page.locator("body").press("Enter");
  await expect(page).toHaveURL(/[?&]dock=source(?:&|$)/);
  await expect(page).toHaveURL(/[?&]src=source-agenda(?:&|$)/);
  await expect(page).not.toHaveURL(/[?&]center=(?!root-alex-rivera)/);
  const dock = page.locator(".sourceDock");
  await expect(dock).toBeVisible({ timeout: 10_000 });
  await expect(dock).toContainText("Agenda");

  // 8: upstream trace is selection-driven and ephemeral (§12.3) — pressed
  // state only, no URL change, and re-press clears it.
  const urlWithDock = page.url();
  const upstream = dock.locator(".sourceTraceButton").first();
  await upstream.click();
  await expect(upstream).toHaveAttribute("aria-pressed", "true");
  expect(page.url()).toBe(urlWithDock);
  await upstream.click();
  await expect(upstream).toHaveAttribute("aria-pressed", "false");
  expect(page.url()).toBe(urlWithDock);

  // 13: refresh restores the sources view, center, pose and the open dock.
  await page.reload();
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator(".sceneShell canvas")).toHaveCount(1, { timeout: 20_000 });
  await expectFoundationPose(page);
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", "root-alex-rivera");
  await expect(page.locator(".sourceDock")).toBeVisible({ timeout: 10_000 });

  expect(consoleErrors).toEqual([]);
});

test("overlay switch never relayouts the foundation and the §20 density counters ride the evidence", async ({ page }) => {
  const consoleErrors = collectConsoleErrors(page);
  await prepareFoundationWorld(page);
  const scene = page.locator(".sceneShell");
  const output = page.locator('[data-testid="runtime-performance"]');
  await expect(output).toHaveAttribute("data-performance-ready", "true", { timeout: 20_000 });

  // §20: the foundation census measures derived primitives with the active
  // quality tier attached, and the shipped demo fits its budgets.
  await expect(output).toHaveAttribute("data-performance-foundation-profile", /compact|balanced|rich/);
  const counters = await output.evaluate((element) => ({
    stations: Number((element as HTMLElement).dataset.performanceSourceStations),
    ports: Number((element as HTMLElement).dataset.performanceSourceStreamPorts),
    lanes: Number((element as HTMLElement).dataset.performanceSourcePipelineLanes),
    flows: Number((element as HTMLElement).dataset.performanceSourceFlowSegments),
    gaps: Number((element as HTMLElement).dataset.performanceSourceGapMarkers),
    labels: Number((element as HTMLElement).dataset.performanceFoundationLabels)
  }));
  expect(counters.stations).toBeGreaterThan(0);
  expect(counters.ports).toBeGreaterThan(0);
  expect(counters.gaps).toBeGreaterThan(0);
  expect(counters.labels).toBeGreaterThan(0);
  // The canonical center projects the compiler-scoped local world; emission
  // bundles only mount when both endpoints are local, so flow/lane counters
  // are asserted as REGISTERED numbers, not as nonzero.
  expect(Number.isFinite(counters.flows)).toBe(true);
  expect(Number.isFinite(counters.lanes)).toBe(true);
  const foundationEvaluation = await output.evaluate((element) => {
    const raw = (element as HTMLOutputElement).value || element.textContent || "";
    return raw ? (JSON.parse(raw) as { foundation: { profile: string; violations: string[] } | null }).foundation : null;
  });
  expect(foundationEvaluation).not.toBeNull();
  expect(foundationEvaluation!.violations).toEqual([]);

  // 14/15: hover and overlay switch keep URL geometry and node positions —
  // overlay changes encoding only (§19.4/§19.7 item 15).
  const signatureBefore = await scene.getAttribute("data-layout-position-signature");
  expect(signatureBefore).toBeTruthy();
  await rememberCanvas(page);
  await page.mouse.move(400, 300);
  await page.mouse.move(640, 360);
  await expect(page).toHaveURL(/[?&]view=sources(?:&|$)/);
  await page.getByLabel("Overlay", { exact: true }).selectOption("freshness");
  await expect(scene).toHaveAttribute("data-scene-overlay", "freshness");
  await expect(scene).toHaveAttribute("data-layout-position-signature", signatureBefore!);
  await expectFoundationPose(page);
  await expectRememberedCanvas(page);

  expect(consoleErrors).toEqual([]);
});

test("reduced motion serves the 2D fallback on the SAME sources route with the banded foundation plan", async ({ page }) => {
  const consoleErrors = collectConsoleErrors(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await prepareApp(page, CANONICAL_SOURCES_URL);

  // 19/21: same route, no canvas, static banded plan (§14.2) with the five
  // navigable sections firing the same semantic events (§14.3).
  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page).toHaveURL(/[?&]view=sources(?:&|$)/);
  await expect(page.locator(".sceneShell canvas")).toHaveCount(0);
  await expect(page.locator(".sceneFallback .fallbackPlan")).toHaveAttribute("data-plane-profile", "foundation");
  const nav = page.locator(".fallbackFoundation");
  await expect(nav).toBeVisible();
  await expect(nav.locator("[data-section]")).toHaveCount(5);

  // The 2D fallback mounts no derived 3D primitives: foundation counters are
  // structural zeros and no foundation evaluation is claimed.
  const output = page.locator('[data-testid="runtime-performance"]');
  await expect(output).toHaveAttribute("data-performance-foundation-profile", "");
  await expect(output).toHaveAttribute("data-performance-source-stations", "0");

  // The same dock grammar still answers a source activation.
  await nav.locator('[data-section="sources"] a').first().click();
  await expect(page).toHaveURL(/[?&]dock=source/);
  await expect(page.locator(".sourceDock")).toBeVisible({ timeout: 10_000 });

  expect(consoleErrors).toEqual([]);
});
