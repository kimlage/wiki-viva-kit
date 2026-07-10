import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

const NATIVE_VIEWS = ["quadrants", "radar", "sources", "work"] as const;
type NativeView = (typeof NATIVE_VIEWS)[number];
type NativeOverlay = "attention" | "freshness" | "actions" | "ownership" | "evidence" | "quality";

test.describe.configure({ timeout: 90_000 });

async function prepareCanonicalV8World(
  page: Page,
  options: { view?: NativeView; overlay?: NativeOverlay; missionCard?: "open" | "closed"; group?: string } = {}
) {
  await page.addInitScript(({ missionCard }) => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wiki-cockpit.missionCard", missionCard);
    window.localStorage.removeItem("wikiCockpitVisualControl.v1");
    window.localStorage.removeItem("wikiCockpitVisualControl.v2");
  }, { missionCard: options.missionCard ?? "closed" });
  const view = options.view ?? "quadrants";
  const overlay = options.overlay ?? (view === "radar" ? "freshness" : "actions");
  const group = options.group ? `&group=${encodeURIComponent(options.group)}` : "";
  await page.goto(`/demo/w?center=root-alex-rivera&view=${view}&lens=all&overlay=${overlay}${group}&tour=0`);
  const workspace = page.locator(".worldWorkspace");
  await expect(workspace).toHaveAttribute("data-runtime-mode", "v8", { timeout: 20_000 });
  await expect(workspace).toHaveAttribute("data-world-view", view);
  await expect(workspace).toHaveAttribute("data-world-overlay", overlay);
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator(".sceneShell canvas")).toHaveCount(1, { timeout: 20_000 });
  await expect(page.locator(".worldNavigator")).toBeVisible({ timeout: 20_000 });
}

async function rememberCanvas(page: Page) {
  await page.evaluate(() => {
    const testWindow = window as Window & { __wikiNavigationCanvas?: HTMLCanvasElement };
    testWindow.__wikiNavigationCanvas = document.querySelector<HTMLCanvasElement>(".sceneShell canvas") ?? undefined;
  });
}

async function expectRememberedCanvas(page: Page) {
  await expect(page.locator(".sceneShell canvas")).toHaveCount(1);
  expect(await page.evaluate(() => {
    const testWindow = window as Window & { __wikiNavigationCanvas?: HTMLCanvasElement };
    return document.querySelector<HTMLCanvasElement>(".sceneShell canvas") === testWindow.__wikiNavigationCanvas;
  })).toBe(true);
}

const SURFACE_BACKGROUND_SELECTORS = [
  ".sceneCanvasFrame",
  ".worldCommandBar",
  ".worldTopStrip",
  ".worldBreadcrumbs",
  ".worldMeta",
  ".worldMissionCard",
  ".quadrantCompass"
] as const;

async function expectCanonicalNativeRoute(page: Page, view: NativeView) {
  const route = await page.evaluate(() => {
    const query = new URLSearchParams(window.location.search);
    return {
      pathname: window.location.pathname,
      view: query.get("view"),
      center: query.get("center"),
      runtimeView: document.querySelector<HTMLElement>(".worldWorkspace")?.dataset.worldView ?? "",
      runtimeCenter: document.querySelector<HTMLElement>(".worldWorkspace")?.dataset.worldCenter ?? ""
    };
  });
  expect(route).toEqual({
    pathname: "/demo/w",
    view,
    center: "root-alex-rivera",
    runtimeView: view,
    runtimeCenter: "root-alex-rivera"
  });
}

async function expectViewShortcutBlocked(page: Page, expectedView: NativeView) {
  const before = page.url();
  // Exercise the window-level listener, not a focused input/dialog handler.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press(expectedView === "radar" ? "4" : "2");
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-view", expectedView);
  expect(page.url()).toBe(before);
}

async function expectSurfaceBackground(page: Page, inert: boolean) {
  for (const selector of SURFACE_BACKGROUND_SELECTORS) {
    const target = page.locator(selector).first();
    await expect(target, `${selector} is part of the primary world background`).toHaveCount(1);
    if (inert) {
      await expect(target, `${selector} is hidden from assistive navigation behind a surface`).toHaveAttribute("aria-hidden", "true");
    } else {
      await expect(target, `${selector} is restored when the surface closes`).not.toHaveAttribute("aria-hidden", "true");
    }
    expect(await target.evaluate((element) => (element as HTMLElement).inert), selector).toBe(inert);
  }
}

test("v8 keyboard shortcuts 1-4 update one canonical view grammar", async ({ page }) => {
  await prepareCanonicalV8World(page);
  const workspace = page.locator(".worldWorkspace");
  await rememberCanvas(page);

  for (const [index, view] of NATIVE_VIEWS.entries()) {
    await page.keyboard.press(String(index + 1));
    await expect(workspace).toHaveAttribute("data-world-view", view);
    await expect(page).toHaveURL(new RegExp(`[?&]view=${view}(?:&|$)`));
    const route = await page.evaluate(() => ({
      pathname: window.location.pathname,
      queryView: new URLSearchParams(window.location.search).get("view"),
      runtimeView: document.querySelector<HTMLElement>(".worldWorkspace")?.dataset.worldView ?? ""
    }));
    expect(route).toEqual({ pathname: "/demo/w", queryView: view, runtimeView: view });
    await expectRememberedCanvas(page);
  }
});

test("semantic motion distinguishes a world morph from an overlay resolve", async ({ page }) => {
  await prepareCanonicalV8World(page, { view: "quadrants", overlay: "actions" });
  const workspace = page.locator(".worldWorkspace");
  const scene = page.locator(".sceneShell");
  const cue = page.locator(".sceneTransitionCue");
  await rememberCanvas(page);

  await expect(workspace).toHaveAttribute("data-visual-motion", "0.78");
  await page.getByRole("button", { name: "Radar", exact: true }).click();
  await expect(scene).toHaveAttribute("data-motion-intent", "view");
  await expect(cue).toHaveAttribute("data-motion-intent", "view");
  const viewDuration = Number(await scene.getAttribute("data-motion-duration-ms"));
  expect(viewDuration).toBeGreaterThanOrEqual(850);
  expect(viewDuration).toBeLessThanOrEqual(1_100);
  await expectRememberedCanvas(page);

  const geometryBeforeOverlay = await scene.getAttribute("data-layout-position-signature");
  await page.getByLabel("Overlay", { exact: true }).selectOption("evidence");
  await expect(scene).toHaveAttribute("data-motion-intent", "overlay");
  await expect(cue).toHaveAttribute("data-motion-intent", "overlay");
  const overlayDuration = Number(await scene.getAttribute("data-motion-duration-ms"));
  expect(overlayDuration).toBeGreaterThanOrEqual(300);
  expect(overlayDuration).toBeLessThan(viewDuration);
  await expect(scene).toHaveAttribute("data-layout-position-signature", geometryBeforeOverlay ?? "");
  await expectRememberedCanvas(page);
});

test("one semantic transaction sequences quadrant retreat and return travel on the persistent canvas", async ({ page }) => {
  await prepareCanonicalV8World(page, { view: "quadrants", overlay: "actions", group: "family:source" });
  const scene = page.locator(".sceneShell");
  const cue = page.locator(".sceneTransitionCue");
  await rememberCanvas(page);

  const initialSequence = Number(await scene.getAttribute("data-motion-sequence"));
  await expect(scene).not.toHaveAttribute("data-scene-level", "0");
  await page.locator(".worldBreadcrumbs .crumbButton").last().click();
  await expect(scene).toHaveAttribute("data-motion-intent", "retreat");
  await expect(scene).toHaveAttribute("data-scene-level", "0");
  const retreatSequence = Number(await scene.getAttribute("data-motion-sequence"));
  expect(retreatSequence).toBeGreaterThan(initialSequence);
  await expect(cue).toHaveAttribute("data-motion-sequence", String(retreatSequence));
  await expect(cue).toHaveAttribute("data-motion-intent", "retreat");
  await expectRememberedCanvas(page);

  await page.goBack();
  await expect(scene).toHaveAttribute("data-motion-intent", "travel");
  await expect(scene).not.toHaveAttribute("data-scene-level", "0");
  const travelSequence = Number(await scene.getAttribute("data-motion-sequence"));
  expect(travelSequence).toBeGreaterThan(retreatSequence);
  await expect(cue).toHaveAttribute("data-motion-sequence", String(travelSequence));
  await expect(cue).toHaveAttribute("data-motion-intent", "travel");
  await expectRememberedCanvas(page);
});

test("the stale next step switches the canonical view to Radar", async ({ page }) => {
  await prepareCanonicalV8World(page, { view: "work", overlay: "freshness", missionCard: "open" });
  const staleMission = page.locator(".missionRowMain").filter({ hasText: /Atualizar conteúdo antigo|Update old content/i });
  await expect(staleMission).toBeVisible();

  await staleMission.click();

  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-view", "radar");
  await expect(page).toHaveURL(/[?&]view=radar(?:&|$)/);
  await expect(page).toHaveURL(/[?&]filter=stale(?:&|$)/);
  const route = await page.evaluate(() => ({
    pathname: window.location.pathname,
    queryView: new URLSearchParams(window.location.search).get("view"),
    runtimeView: document.querySelector<HTMLElement>(".worldWorkspace")?.dataset.worldView ?? ""
  }));
  expect(route).toEqual({ pathname: "/demo/w", queryView: "radar", runtimeView: "radar" });
});

test("the world explanation makes every behind-world control inert", async ({ page }) => {
  await prepareCanonicalV8World(page, { missionCard: "open" });
  await page.locator(".worldNavigatorLearn").click();
  const panel = page.locator(".worldNavigatorPanel");
  await expect(panel).toBeVisible();

  for (const selector of [
    ".sceneCanvasFrame",
    ".worldCommandBar",
    ".worldBreadcrumbs",
    ".conditionStrip",
    ".worldMeta",
    ".worldMissionCard",
    ".quadrantCompass"
  ]) {
    const target = page.locator(selector).first();
    if (await target.count() === 0) continue;
    await expect(target).toHaveAttribute("aria-hidden", "true");
    expect(await target.evaluate((element) => (element as HTMLElement).inert), selector).toBe(true);
  }
  expect(await panel.evaluate((element) => Boolean(element.closest("[inert]")))).toBe(false);
  await expectViewShortcutBlocked(page, "quadrants");

  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  for (const selector of [".sceneCanvasFrame", ".worldCommandBar", ".worldBreadcrumbs", ".worldMissionCard", ".quadrantCompass"]) {
    const target = page.locator(selector).first();
    if (await target.count() === 0) continue;
    await expect(target).not.toHaveAttribute("aria-hidden", "true");
    expect(await target.evaluate((element) => (element as HTMLElement).inert), selector).toBe(false);
  }
});

test("global view shortcuts stay suspended under the coach, docks and reader", async ({ page }) => {
  await prepareCanonicalV8World(page, { missionCard: "open" });

  await page.locator(".tourButton").click();
  await expect(page.locator(".coachOverlay")).toBeVisible();
  await expectViewShortcutBlocked(page, "quadrants");
  await page.keyboard.press("Escape");
  await expect(page.locator(".coachOverlay")).toHaveCount(0);

  await page.locator(".workButton").click();
  await expect(page.locator(".workDockPanel")).toBeVisible();
  await expectViewShortcutBlocked(page, "quadrants");
  await page.locator(".workDockPanel .readerClose").first().click();
  await expect(page.locator(".workDockPanel")).toHaveCount(0);

  const search = page.locator(".commandSearch input");
  await search.fill("CRM accounts export");
  await search.press("Enter");
  await expect(page.locator(".pageReader")).toBeVisible();
  await expectViewShortcutBlocked(page, "quadrants");
});

test("dense action reader owns the foreground and starts with decision-ready information", async ({ page }) => {
  await page.setViewportSize({ width: 917, height: 908 });
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.goto(
    "/demo/w?center=root-alex-rivera&view=quadrants&lens=q2_pratica&overlay=actions" +
    "&page=action-region-pressure-004&reader=1&demo_scenario=dense_stress&tour=0"
  );

  const workspace = page.locator(".worldWorkspace");
  const reader = page.locator(".pageReader");
  const compass = page.locator(".quadrantCompass");
  await expect(reader).toBeVisible({ timeout: 20_000 });
  await expect(workspace).toHaveAttribute("data-primary-surface-open", "true");
  await expect(reader).toHaveAttribute("aria-modal", "true");
  await expect(compass).toBeHidden();
  await expect(compass).toHaveAttribute("aria-hidden", "true");
  await expect(page.locator(".readerHead h2")).toHaveText(
    "Ação que aguarda julgamento humano sobre evidência sintética de alta densidade 004"
  );
  await expect(page.locator(".readerBody h1")).toHaveCount(0);
  await expect(page.locator(".actionSummaryPanel")).toContainText("Waiting for human");
  await expect(page.locator(".actionNextStep")).toContainText(
    "Review the linked synthetic evidence and leave a human-gated receipt."
  );
  await expect(page.locator(".readerActionBar")).toBeVisible();

  const geometry = await page.evaluate(() => {
    const readerElement = document.querySelector<HTMLElement>(".pageReader");
    const compassElement = document.querySelector<HTMLElement>(".quadrantCompass");
    if (!readerElement || !compassElement) throw new Error("reader surface geometry unavailable");
    const readerRect = readerElement.getBoundingClientRect();
    const compassRect = compassElement.getBoundingClientRect();
    const left = Math.max(readerRect.left, compassRect.left);
    const right = Math.min(readerRect.right, compassRect.right);
    const top = Math.max(readerRect.top, compassRect.top);
    const bottom = Math.min(readerRect.bottom, compassRect.bottom);
    const hit = left < right && top < bottom
      ? document.elementFromPoint((left + right) / 2, (top + bottom) / 2)
      : null;
    return {
      readerWidth: readerRect.width,
      intersectionArea: Math.max(0, right - left) * Math.max(0, bottom - top),
      compassVisibility: getComputedStyle(compassElement).visibility,
      compassOpacity: Number(getComputedStyle(compassElement).opacity),
      overlapOwner: hit?.closest(".pageReader, .quadrantCompass")?.classList.contains("pageReader") ?? false,
      documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth
    };
  });
  expect(geometry.readerWidth).toBeGreaterThanOrEqual(420);
  expect(geometry.intersectionArea).toBeGreaterThan(0);
  expect(geometry.compassVisibility).toBe("hidden");
  expect(geometry.compassOpacity).toBe(0);
  expect(geometry.overlapOwner).toBe(true);
  expect(geometry.documentOverflow).toBeLessThanOrEqual(1);
});

test("Work accepts the Freshness overlay without route normalization", async ({ page }) => {
  await prepareCanonicalV8World(page, { view: "work", overlay: "freshness" });
  const workspace = page.locator(".worldWorkspace");
  await expect(workspace).toHaveAttribute("data-world-view", "work");
  await expect(workspace).toHaveAttribute("data-world-overlay", "freshness");
  await expect(workspace).not.toHaveAttribute("data-runtime-warnings", /unsupported_overlay/);
  await expect(page).toHaveURL(/[?&]view=work(?:&|$)/);
  await expect(page).toHaveURL(/[?&]overlay=freshness(?:&|$)/);
});

for (const scenario of [
  {
    view: "sources" as const,
    overlay: "evidence" as const,
    pageTitle: "CRM accounts export",
    dockButton: ".dockButton",
    dockLabel: /Sources|Fontes/,
    dock: "source",
    surface: ".sourceDock"
  },
  {
    view: "work" as const,
    overlay: "actions" as const,
    pageTitle: "Clean unsourced region claims",
    dockButton: ".workButton",
    dockLabel: /Work|Trabalho/,
    dock: "work",
    surface: ".workDockPanel"
  }
]) {
test(`${scenario.view} keeps page, reader and dock navigation on one canonical world route`, async ({ page }) => {
  await prepareCanonicalV8World(page, {
    view: scenario.view,
    overlay: scenario.overlay,
    missionCard: "open"
  });
  await expectCanonicalNativeRoute(page, scenario.view);

  const search = page.locator(".commandSearch input");
  await search.fill(scenario.pageTitle);
  await search.press("Enter");
  await expect(page.locator(".pageReader")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".readerHead h2")).toHaveText(scenario.pageTitle);
  await expect(page).toHaveURL(/[?&]reader=1(?:&|$)/);
  await expect(page).toHaveURL(/[?&]page=[^&]+/);
  await expectCanonicalNativeRoute(page, scenario.view);
  await expectSurfaceBackground(page, true);

  await page.locator(".pageReader .readerClose").last().click();
  await expect(page.locator(".pageReader")).toHaveCount(0);
  await expect(page).not.toHaveURL(/[?&]reader=1(?:&|$)/);
  await expectCanonicalNativeRoute(page, scenario.view);
  await expectSurfaceBackground(page, false);

  await page.locator(scenario.dockButton).filter({ hasText: scenario.dockLabel }).first().click();
  await expect(page.locator(scenario.surface)).toBeVisible({ timeout: 10_000 });
  await expect(page).toHaveURL(new RegExp(`[?&]dock=${scenario.dock}(?:&|$)`));
  await expect(page).not.toHaveURL(/[?&]reader=1(?:&|$)/);
  await expectCanonicalNativeRoute(page, scenario.view);
  await expectSurfaceBackground(page, true);

  await page.locator(`${scenario.surface} .readerClose`).first().click();
  await expect(page.locator(scenario.surface)).toHaveCount(0);
  await expect(page).not.toHaveURL(/[?&]dock=/);
  await expectCanonicalNativeRoute(page, scenario.view);
  await expectSurfaceBackground(page, false);
});
}

for (const [view, overlay] of [
  ["sources", "evidence"],
  ["work", "actions"]
] as const) {
test(`${view} fallback node hrefs use the canonical deep-link grammar`, async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.goto(`/demo/w?center=root-alex-rivera&view=${view}&lens=all&overlay=${overlay}&visual=1&tour=0`);
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-view", view, { timeout: 20_000 });
  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/, { timeout: 20_000 });

  const href = await page.locator(".fallbackNode:not(.groupNode)").first().getAttribute("href");
  expect(href).toBeTruthy();
  const deepLink = new URL(href!, page.url());
  expect(deepLink.pathname).toBe("/demo/w");
  expect(deepLink.searchParams.get("center")).toBe("root-alex-rivera");
  expect(deepLink.searchParams.get("view")).toBe(view);
  expect(deepLink.searchParams.get("lens")).toBe("all");
  expect(deepLink.searchParams.get("overlay")).toBe(overlay);
  expect(deepLink.searchParams.get("page")).toBeTruthy();
  expect(deepLink.searchParams.get("reader")).toBe("1");
  expect(deepLink.searchParams.get("visual")).toBe("1");
});
}
