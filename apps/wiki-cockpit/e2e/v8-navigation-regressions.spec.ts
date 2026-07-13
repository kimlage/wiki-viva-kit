import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

// These tests intentionally keep one WebGL world mounted through long route,
// reader and dock journeys. Video/trace would become part of the renderer's
// own 120-frame budget and can honestly trigger the adaptive 2D verdict before
// the 3D continuity assertion finishes. Dedicated performance/fallback specs
// cover that branch; keep this interaction contract observer-free.
test.use({ trace: "off", video: "off" });

const NATIVE_VIEWS = ["quadrants", "radar", "sources", "work"] as const;
type NativeView = (typeof NATIVE_VIEWS)[number];
type NativeOverlay = "attention" | "freshness" | "actions" | "ownership" | "evidence" | "quality";
type NativeLens = "all" | "q1_intencao" | "q2_pratica" | "q3_relacoes" | "q4_sistemas";

test.describe.configure({ timeout: 90_000 });

async function prepareCanonicalV8World(
  page: Page,
  options: {
    view?: NativeView;
    lens?: NativeLens;
    overlay?: NativeOverlay;
    missionCard?: "open" | "closed";
    group?: string;
    center?: string;
    scenario?: "dense_stress";
  } = {}
) {
  await page.addInitScript(({ missionCard }) => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wiki-cockpit.missionCard", missionCard);
    window.localStorage.removeItem("wikiCockpitVisualControl.v1");
    window.localStorage.removeItem("wikiCockpitVisualControl.v2");
  }, { missionCard: options.missionCard ?? "closed" });
  const view = options.view ?? "quadrants";
  const lens = options.lens ?? "all";
  const overlay = options.overlay ?? (view === "radar" ? "freshness" : "actions");
  const group = options.group ? `&group=${encodeURIComponent(options.group)}` : "";
  const center = options.center ?? "root-alex-rivera";
  const scenario = options.scenario ? `&demo_scenario=${options.scenario}` : "";
  await page.goto(`/demo/w?center=${center}&view=${view}&lens=${lens}&overlay=${overlay}${group}${scenario}&tour=0`);
  const workspace = page.locator(".worldWorkspace");
  await expect(workspace).toHaveAttribute("data-runtime-mode", "v8", { timeout: 20_000 });
  await expect(workspace).toHaveAttribute("data-world-view", view);
  await expect(workspace).toHaveAttribute("data-world-lens", lens);
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

async function expectSceneInteractionsSettled(page: Page) {
  await expect(page.locator(".sceneTransitionCue")).toHaveCSS("pointer-events", "none", { timeout: 10_000 });
}

async function expectWorldTargetCentersOwned(page: Page, nodeIds: string[]) {
  const ownership = await page.evaluate((expectedNodeIds) => {
    return expectedNodeIds.map((nodeId) => {
      const element = [...document.querySelectorAll<HTMLElement>("[data-world-node-id]")]
        .find((candidate) => candidate.dataset.worldNodeId === nodeId) ?? null;
      const bounds = element?.getBoundingClientRect();
      const hit = bounds
        ? document.elementFromPoint(bounds.left + bounds.width / 2, bounds.top + bounds.height / 2)
        : null;
      return {
        nodeId,
        hitNodeId: hit?.closest<HTMLElement>("[data-world-node-id]")?.dataset.worldNodeId ?? ""
      };
    });
  }, nodeIds);
  expect(ownership).toEqual(nodeIds.map((nodeId) => ({ nodeId, hitNodeId: nodeId })));
}

async function visibleWorldTargetIds(page: Page, kind: "page" | "group") {
  return page.locator(`[data-world-target-kind="${kind}"]`).evaluateAll((elements) =>
    elements
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return (
          style.visibility !== "hidden" &&
          style.display !== "none" &&
          rect.width > 0 &&
          rect.height > 0 &&
          !element.closest("[inert]")
        );
      })
      .map((element) => element.getAttribute("data-world-target-id") ?? "")
      .filter(Boolean)
      .sort()
  );
}

async function expectVisibleWorldTargetsAccessible(page: Page) {
  const targets = await page.locator("[data-world-target-kind]").evaluateAll((elements) => {
    const visibleElements = elements
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
      });
    return visibleElements.map((element) => {
      (element as HTMLElement).focus();
      return {
        id: (element as HTMLElement).dataset.worldTargetId ?? "",
        kind: (element as HTMLElement).dataset.worldTargetKind ?? "",
        tag: element.tagName.toLowerCase(),
        tabIndex: (element as HTMLElement).tabIndex,
        name: element.getAttribute("aria-label") || (element.textContent ?? "").trim(),
        focused: document.activeElement === element
      };
    });
  });
  expect(targets.length).toBeGreaterThan(0);
  expect(new Set(targets.map((target) => `${target.kind}:${target.id}`)).size).toBe(targets.length);
  for (const target of targets) {
    expect(["button", "a"], `${target.id} must be a native control`).toContain(target.tag);
    expect(target.tabIndex, `${target.id} must be keyboard reachable`).toBeGreaterThanOrEqual(0);
    expect(target.name.trim(), `${target.id} must have an accessible name`).not.toBe("");
    expect(target.focused, `${target.id} must accept DOM focus`).toBe(true);
  }

  const decorativeViolations = await page.locator("[data-world-decorative=true]").evaluateAll((elements) =>
    elements.filter((element) => {
      const html = element as HTMLElement;
      const tag = element.tagName.toLowerCase();
      return tag === "button" || tag === "a" || html.tabIndex >= 0 || getComputedStyle(element).cursor === "pointer";
    }).length
  );
  expect(decorativeViolations).toBe(0);
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

async function expectMissionSurfaceBelowTopStrip(page: Page, selector: ".worldMissionCard" | ".worldMissionSlim") {
  const mission = page.locator(selector);
  await expect(mission).toBeVisible();
  const hudGeometry = await page.evaluate((missionSelector) => {
    const shell = document.querySelector<HTMLElement>(".sceneShell");
    const strip = document.querySelector<HTMLElement>(".worldTopStrip");
    const missionSurface = document.querySelector<HTMLElement>(missionSelector);
    if (!shell || !strip || !missionSurface) return null;
    const stripRect = strip.getBoundingClientRect();
    const missionRect = missionSurface.getBoundingClientRect();
    return {
      measuredHeight: Number.parseFloat(shell.style.getPropertyValue("--world-top-strip-height")),
      renderedHeight: Math.ceil(stripRect.height),
      gap: missionRect.top - stripRect.bottom
    };
  }, selector);
  expect(hudGeometry).not.toBeNull();
  expect(hudGeometry?.measuredHeight).toBe(hudGeometry?.renderedHeight);
  expect(hudGeometry?.gap).toBeGreaterThanOrEqual(8);
}

for (const [view, lens, overlay, compatibilityLabel, compatibilityHint, currentOnly] of [
  ["radar", "all", "freshness", null, null, false],
  ["atlas", "type", "actions", "Atlas", "hierarchy: what lives under each area", false],
  ["districts", "type", "actions", "Districts", "identification: the world sorted by kind", true]
] as const) {
  test(`explicit legacy ${view} deep link preserves its registered compatibility projection`, async ({ page }) => {
    if (compatibilityLabel) {
      // A Linux-like wrapped desktop width exercises the platform-font case
      // where compatibility context makes the top strip taller than one row.
      await page.setViewportSize({ width: 1100, height: 900 });
    }
    await page.addInitScript(() => {
      window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
      window.localStorage.setItem("wiki-cockpit.missionCard", "open");
    });
    await page.goto(`/demo/w/${view}?visual=1&tour=0`);

    const workspace = page.locator(".worldWorkspace");
    await expect(workspace).toHaveAttribute("data-runtime-mode", "compat", { timeout: 20_000 });
    await expect(workspace).toHaveAttribute("data-world-view", view);
    await expect(workspace).toHaveAttribute("data-world-lens", lens);
    await expect(workspace).toHaveAttribute("data-world-overlay", overlay);
    await expect(page.locator(".sceneShell")).toHaveAttribute("data-scene-perspective", view);
    await expect(page.locator(".sceneShell")).toHaveAttribute("data-scene-overlay", overlay);

    const address = new URL(page.url());
    expect(address.pathname).toBe(`/demo/w/${view}`);
    expect(address.searchParams.get("view")).toBeNull();

    const navigator = page.locator(".worldNavigator");
    if (compatibilityLabel && compatibilityHint) {
      await expect(navigator).toHaveAttribute("data-native-view", "");
      await expect(navigator).toHaveAttribute("data-compatibility-view", view);
      await expect(navigator.locator('[data-view-option][aria-pressed="true"]')).toHaveCount(0);
      await expect(navigator.locator(`[data-compatibility-context="${view}"]`)).toContainText(compatibilityLabel);
      await expect(navigator.locator(`[data-compatibility-context="${view}"]`)).toContainText(compatibilityHint);

      const missionContext = page.locator(".missionContextSummary");
      await expect(missionContext).toHaveAttribute("data-view-context", "compatibility");
      await expect(missionContext.locator(".missionViewBadge")).toHaveText("Compatibility view");
      await expect(missionContext.locator(".missionViewContext")).toHaveText(compatibilityLabel);
      await expect(missionContext.locator(".missionViewHint")).toHaveText(compatibilityHint);
      await expectMissionSurfaceBelowTopStrip(page, ".worldMissionCard");
      await page.locator(".missionCollapse").click();
      await expect(page.locator(".worldMissionCard")).toHaveCount(0);
      await expectMissionSurfaceBelowTopStrip(page, ".worldMissionSlim");
    } else {
      await expect(navigator).toHaveAttribute("data-native-view", view);
      await expect(navigator).toHaveAttribute("data-compatibility-view", "");
      await expect(navigator.locator(`[data-view-option="${view}"]`)).toHaveAttribute("aria-pressed", "true");
      await expect(page.locator(".missionContextSummary")).toHaveAttribute("data-view-context", "native");
    }

    const compatibilityGlyph = page.locator(`.perspectiveGlyphs [data-perspective-option="${view}"]`);
    await expect(compatibilityGlyph).toHaveAttribute("aria-pressed", "true");
    await expect(compatibilityGlyph).toHaveAttribute("data-compatibility-current-only", currentOnly ? "true" : "false");

    if (view === "districts") {
      await page.setViewportSize({ width: 390, height: 844 });
      await expect(navigator.locator('[data-compatibility-context="districts"]')).toBeVisible();
      await expect(navigator.locator('[data-view-option][aria-pressed="true"]')).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    }
  });
}

test("fallback HUD flows mission status between context and quadrant navigation", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.goto("/demo/w/radar?visual=1&tour=0");

  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expectMissionSurfaceBelowTopStrip(page, ".worldMissionSlim");
  await expect(page.locator(".quadrantCompass")).toBeVisible();

  const flow = await page.evaluate(() => {
    const strip = document.querySelector<HTMLElement>(".worldTopStrip");
    const mission = document.querySelector<HTMLElement>(".worldMissionSlim");
    const compass = document.querySelector<HTMLElement>(".quadrantCompass");
    if (!strip || !mission || !compass) return null;
    const stripRect = strip.getBoundingClientRect();
    const missionRect = mission.getBoundingClientRect();
    const compassRect = compass.getBoundingClientRect();
    return {
      missionGap: missionRect.top - stripRect.bottom,
      compassGap: compassRect.top - missionRect.bottom,
      missionBeforeCompass: Boolean(mission.compareDocumentPosition(compass) & Node.DOCUMENT_POSITION_FOLLOWING)
    };
  });
  expect(flow).not.toBeNull();
  expect(flow?.missionGap).toBeGreaterThanOrEqual(8);
  expect(flow?.compassGap).toBeGreaterThanOrEqual(8);
  expect(flow?.missionBeforeCompass).toBe(true);

  await page.locator(".fallbackNode").first().click();
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-primary-surface-open", "true");
  await expect(page.locator(".pageReader")).toBeVisible();
  await expect(page.locator(".worldMissionSlim")).toBeHidden();
  expect(await page.locator(".worldMissionSlim").evaluate((element) => getComputedStyle(element).display)).toBe("none");
});

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

test("URL-owned Missions tray hydrates deep links, resolves singleton conflicts and follows Back/Forward with focus", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  const world = "/demo/w?view=quadrants&center=root-alex-rivera&lens=all&overlay=actions&tour=0";
  await page.goto(`${world}&tray=missions`);

  const missions = page.locator(".missionsPanel");
  const close = missions.locator(".readerClose");
  const missionButton = page.locator(".missionsButton");
  const search = page.locator(".commandSearch input");
  await expect(missions).toBeVisible({ timeout: 20_000 });
  await expect(page).toHaveURL(/[?&]tray=missions(?:&|$)/);
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-primary-surface-open", "true");
  await expect(close).toBeFocused();

  await close.click();
  await expect(missions).toHaveCount(0);
  await expect(page).not.toHaveURL(/[?&]tray=/);
  await expect(search).toBeFocused();

  await page.goBack();
  await expect(missions).toBeVisible();
  await expect(page).toHaveURL(/[?&]tray=missions(?:&|$)/);
  await expect(close).toBeFocused();

  await page.goForward();
  await expect(missions).toHaveCount(0);
  await expect(page).not.toHaveURL(/[?&]tray=/);
  await expect(search).toBeFocused();

  await missionButton.click();
  await expect(missions).toBeVisible();
  await expect(page).toHaveURL(/[?&]tray=missions(?:&|$)/);
  await expect(close).toBeFocused();
  await close.click();
  await expect(missions).toHaveCount(0);
  await expect(missionButton).toBeFocused();

  // A hand-written conflict has no event ordering. The parser's documented
  // dock > reader > tray precedence is immediately reflected back into the
  // address, so the visible surface and the shareable URL stay identical.
  await page.goto(`${world}&dock=gates&tray=missions`);
  await expect(page.locator(".gatesDock")).toBeVisible({ timeout: 20_000 });
  await expect(missions).toHaveCount(0);
  await expect(page).toHaveURL(/[?&]dock=gates(?:&|$)/);
  await expect(page).not.toHaveURL(/[?&]tray=/);

  // URL ownership does not bypass block-stack ownership: Genesis stage 0 has
  // no gamification/Missions capability, so a stale deep link closes itself.
  await page.goto("/demo/genesis?stage=0&tray=missions&tour=0");
  await expect(page.getByRole("button", { name: /A person|Uma pessoa/i })).toBeVisible({ timeout: 20_000 });
  await expect(missions).toHaveCount(0);
  await expect(page).not.toHaveURL(/[?&]tray=/);
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

test("the mobile world guide owns the viewport and exposes all three axes", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await prepareCanonicalV8World(page, { missionCard: "open" });
  await page.locator(".worldNavigatorLearn").click();

  const panel = page.locator(".worldNavigatorPanel");
  const mission = page.locator(".worldMissionCard");
  await expect(panel).toBeVisible();
  // View, lens and overlay remain the three independent axes. A composed
  // bundle also exposes its extension-pack catalog as a fourth, explicitly
  // named section instead of hiding installed capabilities from the guide.
  await expect(page.locator("[data-experience-section]")).toHaveCount(4);
  for (const section of ["views", "packs", "lenses", "overlays"] as const) {
    await expect(page.locator(`[data-experience-section="${section}"]`)).toHaveCount(1);
  }
  await expect(mission).toBeHidden();
  await panel.evaluate(async (element) => {
    const finite = element
      .getAnimations({ subtree: true })
      .filter((animation) => animation.effect?.getTiming().iterations !== Infinity);
    await Promise.all(finite.map((animation) => animation.finished.catch(() => undefined)));
  });

  const geometry = await panel.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const topBar = document.querySelector<HTMLElement>(".topBar")?.getBoundingClientRect();
    return {
      top: rect.top,
      bottom: rect.bottom,
      topBarBottom: topBar?.bottom ?? 0,
      viewportHeight: window.innerHeight,
      scrollable: element.scrollHeight > element.clientHeight
    };
  });
  expect(geometry.top).toBeGreaterThanOrEqual(geometry.topBarBottom + 8);
  expect(geometry.bottom).toBeLessThanOrEqual(geometry.viewportHeight);
  expect(geometry.scrollable).toBe(true);

  for (const axis of ["views", "lenses", "overlays"] as const) {
    const section = page.locator(`[data-experience-section="${axis}"]`);
    await section.scrollIntoViewIfNeeded();
    const hitTest = await section.evaluate((element) => {
      const header = element.querySelector("header") ?? element;
      const rect = header.getBoundingClientRect();
      const x = Math.min(window.innerWidth - 1, Math.max(0, rect.left + Math.min(rect.width / 2, 40)));
      const y = Math.min(window.innerHeight - 1, Math.max(0, rect.top + Math.min(rect.height / 2, 20)));
      const hit = document.elementFromPoint(x, y);
      return {
        withinViewport: rect.top >= 0 && rect.bottom <= window.innerHeight,
        belongsToPanel: Boolean(hit?.closest(".worldNavigatorPanel"))
      };
    });
    expect(hitTest.withinViewport, axis).toBe(true);
    expect(hitTest.belongsToPanel, axis).toBe(true);
  }
});

test("quadrant overview keeps every semantic group target disjoint at reviewed phone and desktop sizes", async ({ page }, testInfo) => {
  // This is six complete worlds and every real group round-trip in one fixed
  // matrix cell. The post-Back fail-fast ownership assertion prevents a stale
  // label from consuming this allowance as click retries; the larger ceiling
  // only accommodates the intentionally expanded positive coverage.
  test.setTimeout(180_000);
  const lensByQuadrant: Record<string, NativeLens> = {
    intencao: "q1_intencao",
    pratica: "q2_pratica",
    relacoes: "q3_relacoes",
    sistemas: "q4_sistemas"
  };
  const cases = [
    // The five ingestion events live below their source anchors. With the
    // root's canonical nested_mode=summarize, the overview therefore owns four
    // root-level families; events appear only after entering a source world.
    { id: "instructional", center: "root-alex-rivera", minimumGroups: 4, scenario: undefined },
    { id: "dense-repeated-families", center: "hub-clientes", minimumGroups: 4, scenario: "dense_stress" as const }
  ];
  const viewports = [
    { id: "phone-short", width: 390, height: 664, minimumTarget: 43.9 },
    { id: "phone-tall", width: 390, height: 844, minimumTarget: 43.9 },
    { id: "desktop", width: 1280, height: 900, minimumTarget: 29.9 }
  ];
  const runs = viewports.flatMap((viewport) => cases.map((fixture) => ({ viewport, fixture })));

  for (const { viewport, fixture } of runs) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await prepareCanonicalV8World(page, {
      view: "quadrants",
      lens: "all",
      overlay: "actions",
      center: fixture.center,
      scenario: fixture.scenario
    });
    await rememberCanvas(page);

    const groups = page.locator('.sceneHtmlControl [data-world-target-kind="group"].nodeGroupLabelSatellite');
    await expect.poll(() => groups.count(), { timeout: 10_000 }).toBeGreaterThanOrEqual(fixture.minimumGroups);
    // Geometry is the settled navigation contract, not an intermediate frame
    // of the deliberate view/travel morph. Wait beyond the longest authored
    // transition before measuring overlap and hit ownership.
    await page.waitForTimeout(1_400);
    await expectSceneInteractionsSettled(page);

    const geometry = await groups.evaluateAll((elements) => {
      const visible = elements.flatMap((element) => {
        const style = getComputedStyle(element);
        const bounds = element.getBoundingClientRect();
        if (style.display === "none" || style.visibility === "hidden" || bounds.width <= 0 || bounds.height <= 0) return [];
        const hit = document.elementFromPoint(bounds.left + bounds.width / 2, bounds.top + bounds.height / 2);
        const hitControl = hit?.closest<HTMLElement>("[data-world-node-id]") ?? null;
        return [{
          nodeId: (element as HTMLElement).dataset.worldNodeId ?? "",
          id: (element as HTMLElement).dataset.worldTargetId ?? "",
          quadrant: (element as HTMLElement).dataset.worldQuadrant ?? "",
          label: element.getAttribute("aria-label") ?? "",
          hitNodeId: hitControl?.dataset.worldNodeId ?? "",
          left: bounds.left,
          right: bounds.right,
          top: bounds.top,
          bottom: bounds.bottom,
          width: bounds.width,
          height: bounds.height
        }];
      });
      const overlaps = visible.flatMap((entry, index) => visible.slice(index + 1).flatMap((candidate) => {
        const overlapWidth = Math.min(entry.right, candidate.right) - Math.max(entry.left, candidate.left);
        const overlapHeight = Math.min(entry.bottom, candidate.bottom) - Math.max(entry.top, candidate.top);
        return overlapWidth > 1 && overlapHeight > 1
          ? [{ first: `${entry.quadrant}:${entry.id}:${entry.label}`, second: `${candidate.quadrant}:${candidate.id}:${candidate.label}`, overlapWidth, overlapHeight }]
          : [];
      }));
      return { visible, overlaps, viewport: { width: window.innerWidth, height: window.innerHeight } };
    });

    await testInfo.attach(`${viewport.id}-quadrant-geometry-${fixture.id}`, {
      body: Buffer.from(JSON.stringify(geometry, null, 2)),
      contentType: "application/json"
    });

    expect(geometry.visible.every((entry) => entry.quadrant)).toBe(true);
    expect(geometry.visible.every((entry) => entry.label)).toBe(true);
    expect(geometry.visible.every((entry) => entry.nodeId && entry.hitNodeId === entry.nodeId)).toBe(true);
    // Fractional transforms can report 43.99998 CSS px for an authored 44px
    // phone control. Desktop retains full explanatory labels, whose compact
    // single-line variant has an authored 30px height.
    expect(geometry.visible.every((entry) => entry.width >= 43.9 && entry.height >= viewport.minimumTarget)).toBe(true);
    expect(geometry.visible.every((entry) =>
      entry.left >= -1 && entry.right <= geometry.viewport.width + 1 &&
      entry.top >= -1 && entry.bottom <= geometry.viewport.height + 1
    )).toBe(true);
    expect(geometry.overlaps).toEqual([]);
    expect(await page.evaluate(() => ({
      horizontal: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      vertical: document.documentElement.scrollHeight > document.documentElement.clientHeight
    }))).toEqual({ horizontal: false, vertical: false });

    const screenshotPath = testInfo.outputPath(`${viewport.id}-quadrant-overview-${fixture.id}.png`);
    await page.screenshot({ path: screenshotPath });
    await testInfo.attach(`${viewport.id}-quadrant-overview-${fixture.id}`, { path: screenshotPath, contentType: "image/png" });
    await expectRememberedCanvas(page);

    for (const destination of geometry.visible) {
      const target = page.locator(`[data-world-node-id="${destination.nodeId}"]`);
      await expect(target).toHaveCount(1);
      await target.focus();
      await expect(target).toBeFocused();
      await target.click();
      expect(new URL(page.url()).searchParams.get("group")).toBe(destination.id);
      await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", lensByQuadrant[destination.quadrant]);
      await expect(page.locator(".worldBreadcrumbs")).toContainText(destination.label);
      await expect(page.locator(`[data-world-group-summary="${destination.id}"]`)).toBeVisible();
      await expectRememberedCanvas(page);

      await page.goBack();
      await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", "all");
      await expect(page).not.toHaveURL(/[?&]group=/);
      await expectRememberedCanvas(page);
      // The overlay owns pointer events during the return morph. Wait for the
      // map's explicit interaction contract instead of measuring/clicking a
      // transient label position.
      await expectSceneInteractionsSettled(page);
      // The interaction cue is the product's promise that projected Html
      // controls have sampled their final frame. Re-prove center ownership on
      // every real return; a stale label must fail here, before Playwright can
      // spend the remaining test timeout retrying an impossible pointer click.
      await expectWorldTargetCentersOwned(page, geometry.visible.map((entry) => entry.nodeId));
    }
  }
});

test("the compact quadrant compass can return from a focused lens to all", async ({ page }) => {
  await prepareCanonicalV8World(page, { lens: "q2_pratica" });
  const workspace = page.locator(".worldWorkspace");
  const all = page.locator("[data-quadrant-all]");
  const q2 = page.locator('[data-wilber-quadrant="2"]');
  await expect(workspace).toHaveAttribute("data-world-lens", "q2_pratica");
  await expect(all).toHaveAttribute("aria-pressed", "false");
  await expect(q2).toHaveAttribute("aria-pressed", "true");

  await q2.click();

  await expect(workspace).toHaveAttribute("data-world-lens", "all");
  await expect(all).toHaveAttribute("aria-pressed", "true");
  await expect(q2).toHaveAttribute("aria-pressed", "false");

  await q2.click();

  await expect(workspace).toHaveAttribute("data-world-lens", "q2_pratica");
  await expect(all).toHaveAttribute("aria-pressed", "false");
  await expect(q2).toHaveAttribute("aria-pressed", "true");

  await all.click();

  await expect(workspace).toHaveAttribute("data-world-lens", "all");
  await expect(all).toHaveAttribute("aria-pressed", "true");
  await expect(q2).toHaveAttribute("aria-pressed", "false");
  await expect(page).toHaveURL(/[?&]lens=all(?:&|$)/);
  await expect(page.locator("canvas")).toHaveCount(1);
});

test("resolved Markdown links navigate the reader by mouse and keyboard without remounting the world", async ({ page }) => {
  await prepareCanonicalV8World(page, { lens: "all", overlay: "actions" });
  await rememberCanvas(page);

  const search = page.locator(".commandSearch input");
  await search.fill("Enviar proposta para Caio");
  await search.press("Enter");
  await expect(page.locator(".readerHead h2")).toHaveText("Enviar proposta para Caio");

  const followMarkdownLink = async (activation: "mouse" | "keyboard") => {
    const link = page.locator('.readerBody a.readerWikiLink[data-page-id="person-caio-prado"]');
    await expect(link).toHaveCount(1);
    await expect(link).toBeVisible();
    await expect(link).toHaveAccessibleName("Caio Prado");
    if (activation === "keyboard") {
      await link.focus();
      await expect(link).toBeFocused();
      await link.press("Enter");
    } else {
      await link.click();
    }

    await expect(page).toHaveURL(/[?&]page=person-caio-prado(?:&|$)/);
    await expect(page.locator(".readerHead h2")).toHaveText("Caio Prado");
    await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", "root-alex-rivera");
    await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", "all");
    await expectRememberedCanvas(page);
  };

  await followMarkdownLink("mouse");
  await page.getByRole("button", { name: "Enviar proposta para Caio", exact: true }).click();
  await expect(page.locator(".readerHead h2")).toHaveText("Enviar proposta para Caio");
  await followMarkdownLink("keyboard");
});

test("Alex quadrant journey reaches semantic collections and real pages in two steps without remount or loops", async ({ page }) => {
  test.setTimeout(180_000);
  await prepareCanonicalV8World(page, { lens: "all", overlay: "actions" });
  await rememberCanvas(page);

  const journey = [
    {
      quadrant: 1,
      lens: "q1_intencao" as const,
      facet: "Identity & intent",
      directPage: "insight-calendario-calmo",
      groups: []
    },
    {
      quadrant: 2,
      lens: "q2_pratica" as const,
      facet: "Outputs & evidence",
      groups: [
        { label: "sources & evidence", id: "family:source", count: 13 }
      ]
    },
    {
      quadrant: 3,
      lens: "q3_relacoes" as const,
      facet: "Culture & relations",
      directPage: "person-bea-rivera",
      groups: [
        { label: "people & responsibilities", id: "family:person", count: 2 }
      ]
    },
    {
      quadrant: 4,
      lens: "q4_sistemas" as const,
      facet: "Systems & governance",
      groups: [
        { label: "areas & workspaces", id: "family:hub", count: 4 },
        { label: "tools in this world", id: "family:content", count: 3 }
      ]
    }
  ];

  for (const step of journey) {
    const quadrant = page.locator(`[data-wilber-quadrant="${step.quadrant}"]`);
    await quadrant.click();
    await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", step.lens);
    await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", "root-alex-rivera");
    await expectRememberedCanvas(page);
    // Lens state commits before the worker-backed scene finishes its spatial
    // transition. Wait for the semantic group set itself so the regression
    // never exercises outgoing controls from the previous quadrant.
    await expect.poll(() => visibleWorldTargetIds(page, "group"), { timeout: 10_000 })
      .toEqual(step.groups.map((group) => group.id).sort());
    await expectVisibleWorldTargetsAccessible(page);

    const visiblePageIds = await visibleWorldTargetIds(page, "page");
    expect(new Set(visiblePageIds).size).toBe(visiblePageIds.length);
    if (step.directPage) expect(visiblePageIds).toContain(step.directPage);

    // Exercise every page-shaped target actually exposed by this quadrant,
    // alternating mouse and keyboard. A visible node must reach either its
    // reader or a real center, then return to the same breadcrumb/lens state.
    for (const [targetIndex, pageId] of visiblePageIds.entries()) {
      const pageTarget = page.locator(`[data-world-target-kind="page"][data-world-target-id="${pageId}"]`);
      await expect(pageTarget).toHaveCount(1);
      const pageTitle = await pageTarget.getAttribute("title");
      expect(pageTitle).toBeTruthy();
      await pageTarget.focus();
      if (targetIndex % 2 === 0) await pageTarget.press("Enter");
      else await pageTarget.click();
      await expect.poll(async () => ({
        center: await page.locator(".worldWorkspace").getAttribute("data-world-center"),
        reader: await page.locator(".pageReader").count()
      })).not.toEqual({ center: "root-alex-rivera", reader: 0 });

      const destinationCenter = await page.locator(".worldWorkspace").getAttribute("data-world-center");
      if (destinationCenter !== "root-alex-rivera") {
        expect(destinationCenter).toBe(pageId);
        await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", "all");
        await expect(page.locator(".worldBreadcrumbs")).toContainText(pageTitle!);
      } else {
        await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", step.lens);
        await expect(page.locator(".pageReader")).toBeVisible();
        await expect(page.locator(".readerHead h2")).toHaveText(pageTitle!);
      }
      await expectRememberedCanvas(page);
      if (destinationCenter !== "root-alex-rivera") {
        await page.goBack();
      } else {
        await page.locator(".pageReader .readerClose").last().click();
        await expect(page.locator(".pageReader")).toHaveCount(0);
        const plate = page.locator(".worldPlate");
        if (await plate.count()) {
          await plate.locator(".questPlateClose").click();
          await expect(plate).toHaveCount(0);
        }
      }
      await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", "root-alex-rivera");
      await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", step.lens);
      await expect(page.locator(".worldBreadcrumbs")).toContainText("Alex Rivera");
      await expect.poll(() => visibleWorldTargetIds(page, "page"), { timeout: 10_000 })
        .toEqual([...visiblePageIds].sort());
    }

    await expect.poll(() => visibleWorldTargetIds(page, "group"), { timeout: 10_000 })
      .toEqual(step.groups.map((group) => group.id).sort());

    for (const [groupIndex, group] of step.groups.entries()) {
      const groupControl = page.getByRole("button", { name: group.label, exact: true });
      await expect(groupControl).toHaveCount(1);
      await groupControl.focus();
      if (groupIndex % 2 === 0) await groupControl.press("Enter");
      else await groupControl.click();

      await expect(page).toHaveURL(new RegExp(`[?&]group=${encodeURIComponent(group.id).replaceAll("%", "%")}(?:&|$)`));
      await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", step.lens);
      await expect(page.locator(".worldBreadcrumbs")).toContainText(step.facet);
      await expect(page.locator(".worldBreadcrumbs")).toContainText(group.label);
      await expectRememberedCanvas(page);

      const summary = page.locator(`[data-world-group-summary="${group.id}"]`);
      await expect(summary).toHaveAttribute("data-world-group-count", String(group.count));
      await expect(summary.locator("p")).not.toHaveText("");
      const examples = summary.locator("[data-world-member-id]");
      const exampleCount = await examples.count();
      expect(exampleCount).toBeGreaterThan(0);
      expect(exampleCount).toBeLessThanOrEqual(3);
      await expect(page.locator(`[data-world-target-kind="group"][data-world-target-id="${group.id}"]`)).toHaveCount(0);

      for (let index = 0; index < exampleCount; index += 1) {
        const example = examples.nth(index);
        const memberId = await example.getAttribute("data-world-member-id");
        expect(memberId).toBeTruthy();
        if (index % 2 === 0) await example.click();
        else await example.press("Enter");
        await expect.poll(async () => ({
          center: await page.locator(".worldWorkspace").getAttribute("data-world-center"),
          reader: await page.locator(".pageReader").count()
        })).not.toEqual({ center: "root-alex-rivera", reader: 0 });

        const destinationCenter = await page.locator(".worldWorkspace").getAttribute("data-world-center");
        if (destinationCenter !== "root-alex-rivera") {
          expect(destinationCenter).toBe(memberId);
          await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", "all");
        } else {
          await expect(page.locator(".pageReader")).toBeVisible();
          await expect(page).toHaveURL(new RegExp(`[?&]page=${memberId}(?:&|$)`));
        }
        await expectRememberedCanvas(page);
        if (destinationCenter !== "root-alex-rivera") {
          await page.goBack();
        } else {
          await page.locator(".pageReader .readerClose").last().click();
          await expect(page.locator(".pageReader")).toHaveCount(0);
          const plate = page.locator(".worldPlate");
          if (await plate.count()) {
            await plate.locator(".questPlateClose").click();
            await expect(plate).toHaveCount(0);
          }
        }
        await expect(summary).toBeVisible();
      }

      const facetCrumb = page.getByRole("button", { name: step.facet, exact: true });
      await expect(facetCrumb).toHaveCount(1);
      await facetCrumb.click();
      await expect(page).not.toHaveURL(/[?&]group=/);
      await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", step.lens);
      await expectRememberedCanvas(page);
    }
  }

  // A collection belongs to the lens that explains it. Changing quadrant
  // leaves the collection instead of silently reusing the same family key for
  // an empty or semantically different population.
  await page.locator('[data-wilber-quadrant="2"]').click();
  await page.getByRole("button", { name: "sources & evidence", exact: true }).press("Enter");
  await expect(page.locator('[data-world-group-summary="family:source"]')).toBeVisible();
  await page.locator('[data-wilber-quadrant="3"]').click();
  await expect(page).not.toHaveURL(/[?&]group=/);
  await expect(page.locator('[data-world-group-summary="family:source"]')).toHaveCount(0);
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", "q3_relacoes");
  await expectRememberedCanvas(page);

  // The Sources view's former technical "Event Emitters" bucket is a real
  // semantic collection too: one activation explains it, the next reaches a
  // source page, and the same canvas remains mounted throughout.
  await page.locator(".worldNavigatorView").filter({ hasText: /^Sources$/ }).click();
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-view", "sources");
  await expectVisibleWorldTargetsAccessible(page);
  const origins = page.getByRole("button", { name: "Evidence origins", exact: true });
  await expect(origins).toHaveCount(1);
  await origins.focus();
  await origins.press("Enter");
  const originsSummary = page.locator('[data-world-group-summary="family:source"]');
  await expect(originsSummary).toHaveAttribute("data-world-group-count", "13");
  await expect(originsSummary.locator("p")).toContainText("Source pages");
  await expect(page.locator(".worldBreadcrumbs")).toContainText("Sources");
  await expect(page.locator(".worldBreadcrumbs")).toContainText("Evidence origins");
  await expect(page.locator('[data-world-target-id="source-emitters"]')).toHaveCount(0);
  const sourceExample = originsSummary.locator("[data-world-member-id]").first();
  const sourceId = await sourceExample.getAttribute("data-world-member-id");
  expect(sourceId).toBeTruthy();
  await sourceExample.click();
  await expect.poll(async () => ({
    center: await page.locator(".worldWorkspace").getAttribute("data-world-center"),
    reader: await page.locator(".pageReader").count()
  })).not.toEqual({ center: "root-alex-rivera", reader: 0 });
  const sourceDestinationCenter = await page.locator(".worldWorkspace").getAttribute("data-world-center");
  if (sourceDestinationCenter !== "root-alex-rivera") {
    expect(sourceDestinationCenter).toBe(sourceId);
    await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", "all");
  } else {
    await expect(page.locator(".pageReader")).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`[?&]page=${sourceId}(?:&|$)`));
  }
  await expectRememberedCanvas(page);

  if (sourceDestinationCenter !== "root-alex-rivera") {
    await page.goBack();
  } else {
    await page.locator(".pageReader .readerClose").last().click();
  }
  await expect(originsSummary).toBeVisible();
  await page.locator(".worldNavigatorView").filter({ hasText: /^Quadrants$/ }).click();
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-view", "quadrants");
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", "root-alex-rivera");

  // Canonical source hierarchy: an event is not a sibling of its source in
  // Alex's root map. Traverse the source collection, enter Agenda as a real
  // center, then reach its normalized event inside that source's Q2 world.
  await page.locator('[data-wilber-quadrant="2"]').click();
  await page.getByRole("button", { name: "sources & evidence", exact: true }).press("Enter");
  const sourceSummary = page.locator('[data-world-group-summary="family:source"]');
  const agendaMember = sourceSummary.locator('[data-world-member-id="source-agenda"]');
  await expect(agendaMember).toHaveCount(1);
  await agendaMember.press("Enter");
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", "source-agenda");
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", "all");
  await expectRememberedCanvas(page);

  await page.locator('[data-wilber-quadrant="2"]').click();
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", "q2_pratica");
  await expect(page.locator('[data-world-target-id="family:event"]')).toHaveCount(0);
  const ingestionEvent = page.locator(
    '[data-world-target-kind="page"][data-world-target-id="event-ingest-agenda-2026-07"]'
  );
  await expect(ingestionEvent).toHaveCount(1);
  await ingestionEvent.press("Enter");
  await expect(page.locator(".pageReader")).toBeVisible();
  await expect(page.locator(".readerHead h2")).toHaveText("Ingestão: agenda");
  await expectRememberedCanvas(page);
});

test("global view shortcuts stay suspended under the coach, docks and reader", async ({ page }) => {
  await prepareCanonicalV8World(page, { missionCard: "open" });

  await page.locator(".tourButton").click();
  await expect(page.locator(".coachOverlay")).toBeVisible();
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-primary-surface-open", "false");
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-background-surface-owned", "true");
  await expect(page.locator(".worldCommandBar")).toHaveAttribute("inert", "");
  await expect(page.locator(".worldCommandBar")).toHaveAttribute("aria-hidden", "true");
  await expectViewShortcutBlocked(page, "quadrants");

  const tourAnchors = [
    null,
    ".worldNavigatorViewControls",
    ".worldNavigatorOverlaySelect",
    ".quadrantCompass",
    ".worldBreadcrumbs",
    ".worldMissionCard, .worldMissionSlim",
    ".commandSearch"
  ];
  for (let index = 0; index < tourAnchors.length; index += 1) {
    await expect(page.locator(".coachProgress")).toHaveText(new RegExp(`^${index + 1} (of|de) 7$`));
    const selector = tourAnchors[index];
    if (selector) {
      const anchor = page.locator(selector).first();
      await expect(anchor).toBeVisible();
      const anchorBox = await anchor.boundingBox();
      expect(anchorBox?.width ?? 0).toBeGreaterThan(0);
      expect(anchorBox?.height ?? 0).toBeGreaterThan(0);
      await expect(page.locator(".coachSpotlight")).toBeVisible();
    }
    if (index < tourAnchors.length - 1) await page.locator(".coachCard .actionButton").click();
  }
  await page.keyboard.press("Escape");
  await expect(page.locator(".coachOverlay")).toHaveCount(0);
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-background-surface-owned", "false");
  await expect(page.locator(".worldCommandBar")).not.toHaveAttribute("inert", "");
  await expect(page.locator(".worldCommandBar")).not.toHaveAttribute("aria-hidden", "true");
  await expect(page.locator(".tourButton")).toBeFocused();

  await page.locator(".workButton").click();
  await expect(page.locator(".workDockPanel")).toBeVisible();
  await expectViewShortcutBlocked(page, "quadrants");
  await page.locator(".workDockPanel .readerClose").first().click();
  await expect(page.locator(".workDockPanel")).toHaveCount(0);

  const search = page.locator(".commandSearch input");
  await search.fill("CRM accounts export");
  await search.press("Enter");
  await expect(page.locator(".pageReader")).toBeVisible();
  await page.keyboard.press("Shift+/");
  await expect(page.locator(".coachOverlay")).toHaveCount(0);
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

  await page.locator(".pageReader .readerClose").last().click();
  await expect(reader).toHaveCount(0);

  const search = page.getByRole("combobox", { name: /Search content|Buscar conteúdo/ });
  await search.fill("dense-canonical action");
  const listbox = page.locator("#world-search-results");
  const resultOptions = listbox.locator('[role="option"]');
  await expect(listbox).toBeVisible();
  await expect(resultOptions).toHaveCount(10);
  await expect(resultOptions.first()).toContainText("Dense canonical action 001");
  await expect(search).toHaveAttribute("aria-expanded", "true");
  await expect(search).toHaveAttribute("aria-controls", "world-search-results");
  await expect(search).toHaveAttribute(
    "aria-activedescendant",
    "world-search-results-option-0"
  );
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe(
    "dense-canonical action"
  );

  await page.getByRole("combobox", { name: /Type|Tipo/ }).selectOption("action");
  await page.getByRole("combobox", { name: /Context|Contexto/ }).selectOption("clientes");
  await expect.poll(() => new URL(page.url()).searchParams.get("search_type")).toBe("action");
  await expect.poll(() => new URL(page.url()).searchParams.get("search_context")).toBe("clientes");
  await expect(resultOptions.first()).toContainText(/action|ação/i);

  await page.getByRole("button", { name: /Show 10 more|Mostrar mais 10/ }).click();
  await expect(resultOptions).toHaveCount(20);
  await expect.poll(() => new URL(page.url()).searchParams.get("search_limit")).toBe("20");

  for (let index = 0; index < 15; index += 1) await search.press("ArrowDown");
  await expect(search).toHaveAttribute(
    "aria-activedescendant",
    "world-search-results-option-15"
  );
  const activeResultGeometry = await page.evaluate(() => {
    const viewport = document.querySelector<HTMLElement>(".missionSearchResults");
    const active = document.querySelector<HTMLElement>(
      '#world-search-results [role="option"][aria-selected="true"]'
    );
    if (!viewport || !active) throw new Error("active search result geometry unavailable");
    const viewportRect = viewport.getBoundingClientRect();
    const activeRect = active.getBoundingClientRect();
    const viewportTop = viewportRect.top + viewport.clientTop;
    const viewportBottom = viewportTop + viewport.clientHeight;
    return {
      selectedCount: document.querySelectorAll(
        '#world-search-results [role="option"][aria-selected="true"]'
      ).length,
      topGap: activeRect.top - viewportTop,
      bottomGap: viewportBottom - activeRect.bottom,
      scrollTop: viewport.scrollTop
    };
  });
  expect(activeResultGeometry.selectedCount).toBe(1);
  expect(activeResultGeometry.topGap).toBeGreaterThanOrEqual(-1);
  expect(activeResultGeometry.bottomGap).toBeGreaterThanOrEqual(-1);
  expect(activeResultGeometry.scrollTop).toBeGreaterThan(0);

  await page.goBack();
  await expect(resultOptions).toHaveCount(10);
  await expect.poll(() => new URL(page.url()).searchParams.has("search_limit")).toBe(false);
  await expect(search).toHaveAttribute(
    "aria-activedescendant",
    "world-search-results-option-0"
  );
  await expect(listbox.locator('[role="option"][aria-selected="true"]')).toHaveCount(1);
  await expect(resultOptions.first()).toHaveAttribute("aria-selected", "true");
  const resetResultGeometry = await page.evaluate(() => {
    const viewport = document.querySelector<HTMLElement>(".missionSearchResults");
    const active = document.querySelector<HTMLElement>(
      '#world-search-results [role="option"][aria-selected="true"]'
    );
    if (!viewport || !active) throw new Error("reset search result geometry unavailable");
    const viewportRect = viewport.getBoundingClientRect();
    const activeRect = active.getBoundingClientRect();
    const viewportTop = viewportRect.top + viewport.clientTop;
    const viewportBottom = viewportTop + viewport.clientHeight;
    return {
      topGap: activeRect.top - viewportTop,
      bottomGap: viewportBottom - activeRect.bottom
    };
  });
  expect(resetResultGeometry.topGap).toBeGreaterThanOrEqual(-1);
  expect(resetResultGeometry.bottomGap).toBeGreaterThanOrEqual(-1);

  await page.getByRole("combobox", { name: /Scope|Escopo/ }).selectOption("world");
  await expect.poll(() => new URL(page.url()).searchParams.get("search_scope")).toBe("world");
  expect(await resultOptions.count()).toBeLessThanOrEqual(20);
  await page.getByRole("combobox", { name: /Scope|Escopo/ }).selectOption("");
  await expect.poll(() => new URL(page.url()).searchParams.has("search_scope")).toBe(false);

  // The immediate keyboard path uses the current draft, not the stale
  // debounced URL result set. One ArrowDown must therefore open result 002.
  await search.fill("dense canonical action");
  await search.press("ArrowDown");
  await search.press("Enter");
  await expect(page.locator(".readerHead h2")).toHaveText("Dense canonical action 002");
  await page.keyboard.press("Escape");
  await expect(reader).toHaveCount(0);

  await page.getByRole("combobox", { name: /Type|Tipo/ }).selectOption("");
  await page.getByRole("combobox", { name: /Context|Contexto/ }).selectOption("");
  await search.fill("acao que aguarda julgamento humano");
  await expect(listbox.locator('[role="option"]').first()).toContainText(
    "Ação que aguarda julgamento humano"
  );
  await search.fill("");
  await expect.poll(() => {
    const query = new URL(page.url()).searchParams;
    return [
      query.has("q"),
      query.has("search_type"),
      query.has("search_context"),
      query.has("search_scope"),
      query.has("search_limit")
    ];
  }).toEqual([false, false, false, false, false]);
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

  const dockClose = page.locator(`${scenario.surface} .readerClose`).first();
  await expect(dockClose).toBeVisible();
  expect(await dockClose.evaluate((button) => {
    const rect = button.getBoundingClientRect();
    const topmost = document.elementFromPoint(
      rect.left + rect.width / 2,
      rect.top + rect.height / 2
    );
    return topmost === button || Boolean(topmost && button.contains(topmost));
  }), "the primary dock must own its close-button pixels above shell controls").toBe(true);
  await dockClose.click();
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

test("quadrant fallback renders the active collection as a summary, never a same-route link", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.goto(
    "/demo/w?center=root-alex-rivera&view=quadrants&lens=q2_pratica&overlay=actions&group=family%3Asource&visual=1&tour=0"
  );
  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator('[data-world-group-summary="family:source"]')).toHaveAttribute("data-world-group-count", "13");
  await expect(page.locator(".fallbackGroups .currentGroup")).toContainText("sources & evidence · 13");
  await expect(page.locator('.fallbackGroups a[href*="group=family%3Asource"]')).toHaveCount(0);
  await expect(page.locator('[data-world-target-kind="page"]')).not.toHaveCount(0);
  await expect(page.locator(".fallbackPlan")).toHaveAttribute("aria-hidden", "true");
  await expect(page.locator('.fallbackPlan [style*="cursor"]')).toHaveCount(0);
  await expectVisibleWorldTargetsAccessible(page);

  const anchorLink = page.locator('[data-world-target-kind="page"][data-world-target-id="source-action-ledger"]');
  await expect(anchorLink).toHaveCount(1);
  const anchorHref = new URL((await anchorLink.getAttribute("href"))!, page.url());
  expect(anchorHref.searchParams.get("center")).toBe("source-action-ledger");
  expect(anchorHref.searchParams.get("lens")).toBe("all");
  expect(anchorHref.searchParams.get("page")).toBeNull();
  expect(anchorHref.searchParams.get("reader")).toBeNull();
});
