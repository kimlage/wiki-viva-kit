import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

const DESKTOP_VIEWPORTS = [
  { width: 1600, height: 780 },
  { width: 1366, height: 768 },
  { width: 1280, height: 720 }
] as const;

const NATIVE_VIEWS = ["quadrants", "radar", "sources", "work"] as const;
const QUADRANT_LENSES = [
  { quadrant: "1", lens: "q1_intencao", sceneFacet: "intencao" },
  { quadrant: "2", lens: "q2_pratica", sceneFacet: "pratica" },
  { quadrant: "3", lens: "q3_relacoes", sceneFacet: "relacoes" },
  { quadrant: "4", lens: "q4_sistemas", sceneFacet: "sistemas" }
] as const;

test.describe.configure({ timeout: 90_000 });

async function prepareWorld(page: Page, options: { missionCard?: "open" | "closed" } = {}) {
  await page.addInitScript(({ missionCard }) => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wiki-cockpit.missionCard", missionCard);
    window.localStorage.removeItem("wikiCockpitVisualControl.v1");
    window.localStorage.removeItem("wikiCockpitVisualControl.v2");
  }, { missionCard: options.missionCard ?? "closed" });
  await page.goto("/demo/w/quadrants?center=root-alex-rivera");
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator(".sceneShell canvas")).toHaveCount(1, { timeout: 20_000 });
  await expect(page.locator(".worldNavigator")).toBeVisible({ timeout: 20_000 });
}

async function documentOverflow(page: Page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    const body = document.body;
    return {
      horizontal: Math.max(0, root.scrollWidth - root.clientWidth, body.scrollWidth - root.clientWidth),
      vertical: Math.max(0, root.scrollHeight - root.clientHeight, body.scrollHeight - root.clientHeight),
      root: { clientHeight: root.clientHeight, scrollHeight: root.scrollHeight },
      body: { clientHeight: body.clientHeight, scrollHeight: body.scrollHeight }
    };
  });
}

async function rememberCanvas(page: Page) {
  await page.evaluate(() => {
    const testWindow = window as Window & { __wikiUxRegressionCanvas?: HTMLCanvasElement };
    testWindow.__wikiUxRegressionCanvas = document.querySelector<HTMLCanvasElement>(".sceneShell canvas") ?? undefined;
  });
}

async function expectRememberedCanvas(page: Page) {
  await expect(page.locator(".sceneShell canvas")).toHaveCount(1);
  const sameCanvas = await page.evaluate(() => {
    const testWindow = window as Window & { __wikiUxRegressionCanvas?: HTMLCanvasElement };
    return document.querySelector<HTMLCanvasElement>(".sceneShell canvas") === testWindow.__wikiUxRegressionCanvas;
  });
  expect(sameCanvas).toBe(true);
}

test("desktop shell and open navigator panel never create document scrollbars", async ({ page }) => {
  for (const viewport of DESKTOP_VIEWPORTS) {
    await page.setViewportSize(viewport);
    await prepareWorld(page);

    const closedOverflow = await documentOverflow(page);
    expect.soft(closedOverflow.vertical, `${viewport.width}x${viewport.height} closed vertical overflow`).toBeLessThanOrEqual(1);
    expect.soft(closedOverflow.horizontal, `${viewport.width}x${viewport.height} closed horizontal overflow`).toBeLessThanOrEqual(1);

    await page.locator(".worldNavigatorLearn").click();
    const panel = page.locator(".worldNavigatorPanel");
    await expect(panel).toBeVisible();

    const openOverflow = await documentOverflow(page);
    expect.soft(openOverflow.vertical, `${viewport.width}x${viewport.height} open vertical overflow`).toBeLessThanOrEqual(1);
    expect.soft(openOverflow.horizontal, `${viewport.width}x${viewport.height} open horizontal overflow`).toBeLessThanOrEqual(1);

    const panelBounds = await panel.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return {
        top: rect.top,
        bottom: rect.bottom,
        viewportHeight: window.innerHeight,
        internalOverflow: element.scrollHeight - element.clientHeight,
        overflowY: getComputedStyle(element).overflowY
      };
    });
    expect.soft(panelBounds.top, `${viewport.width}x${viewport.height} panel top`).toBeGreaterThanOrEqual(0);
    expect.soft(panelBounds.bottom, `${viewport.width}x${viewport.height} panel bottom`).toBeLessThanOrEqual(panelBounds.viewportHeight + 1);
    // Tall viewports may fit the complete guide without needing a scroll
    // range. The contract is that any overflow stays inside the panel, never
    // that every supported viewport must manufacture overflow.
    expect.soft(panelBounds.internalOverflow, `${viewport.width}x${viewport.height} panel internal overflow`).toBeGreaterThanOrEqual(0);
    expect.soft(panelBounds.overflowY, `${viewport.width}x${viewport.height} panel owns its overflow`).toMatch(/auto|scroll/);
  }
});

test("switching native views preserves the mounted 3D canvas and center", async ({ page }) => {
  await prepareWorld(page);
  const workspace = page.locator(".worldWorkspace");
  const center = await workspace.getAttribute("data-world-center");
  expect(center).toBe("root-alex-rivera");
  const canonicalNodeCount = await page.locator(".sceneShell").getAttribute("data-scene-source-node-count");
  expect(Number(canonicalNodeCount)).toBeGreaterThan(100);
  await rememberCanvas(page);

  for (const view of NATIVE_VIEWS) {
    await page.locator(`[data-view-option="${view}"]`).click();
    await expect(workspace).toHaveAttribute("data-world-view", view);
    await expect(workspace).toHaveAttribute("data-world-center", center!);
    await expect(page.locator(".sceneShell")).toHaveAttribute("data-scene-center", center!);
    await expect(page.locator(".sceneShell")).toHaveAttribute("data-scene-input-node-count", canonicalNodeCount!);
    await expectRememberedCanvas(page);
  }
});

test("all four quadrant lenses work in every native view without changing center", async ({ page }) => {
  await prepareWorld(page);
  const workspace = page.locator(".worldWorkspace");
  const scene = page.locator(".sceneShell");
  const center = await workspace.getAttribute("data-world-center");
  expect(center).toBe("root-alex-rivera");
  await rememberCanvas(page);

  for (const view of NATIVE_VIEWS) {
    await page.locator(`[data-view-option="${view}"]`).click();
    await expect(workspace).toHaveAttribute("data-world-view", view);
    await expect(page.locator(".quadrantCompass")).toBeVisible();

    for (const { quadrant, lens, sceneFacet } of QUADRANT_LENSES) {
      await page.locator(`.quadrantTextCell[data-wilber-quadrant="${quadrant}"]`).click();
      await expect(workspace).toHaveAttribute("data-world-lens", lens);
      await expect(workspace).toHaveAttribute("data-world-center", center!);
      await expect(scene).toHaveAttribute("data-scene-center", center!);
      // The runtime URL/state keeps the canonical qN_* id; the scene exposes
      // the normalized facet consumed by layout/camera code.
      await expect(scene).toHaveAttribute("data-scene-quadrant", sceneFacet);
      await expectRememberedCanvas(page);
    }
  }
});

test("demo gate offers guided tour, free exploration and from-zero entry paths", async ({ page }) => {
  await page.goto("/demo");

  const doors = page.locator(".demoGateDoor");
  await expect(doors).toHaveCount(3);
  await expect(page.locator('.demoGateDoor.guided[href="/demo/world?tour=1"]')).toContainText(/Visita guiada|Guided tour/);
  await expect(page.locator('.demoGateDoor.world[href="/demo/world?tour=0"]')).toContainText(/Explorar livremente|Explore freely/);
  await expect(page.locator('.demoGateDoor.genesis[href="/demo/genesis"]')).toContainText(/Começar do zero|Start from zero/);
});

test("MissionCard keeps the secondary CTA below a full-width readable mission", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await prepareWorld(page, { missionCard: "open" });

  const row = page.locator(".missionRow", { has: page.locator(".missionRowAction") }).first();
  await expect(row).toBeVisible();
  const geometry = await row.evaluate((element) => {
    const main = element.querySelector<HTMLElement>(".missionRowMain");
    const copy = element.querySelector<HTMLElement>(".missionCopy");
    const actions = element.querySelector<HTMLElement>(".missionRowActions");
    if (!main || !copy || !actions) return null;
    const rowStyle = getComputedStyle(element);
    const rowRect = element.getBoundingClientRect();
    const mainRect = main.getBoundingClientRect();
    const copyRect = copy.getBoundingClientRect();
    const actionRect = actions.getBoundingClientRect();
    const innerWidth = rowRect.width - parseFloat(rowStyle.paddingLeft) - parseFloat(rowStyle.paddingRight);
    return {
      innerWidth,
      mainWidth: mainRect.width,
      copyWidth: copyRect.width,
      mainBottom: mainRect.bottom,
      actionTop: actionRect.top
    };
  });

  expect(geometry).not.toBeNull();
  expect.soft(geometry!.mainWidth / geometry!.innerWidth, "main mission owns the row width").toBeGreaterThan(0.96);
  expect.soft(geometry!.copyWidth, "mission copy stays readable beside its index").toBeGreaterThan(180);
  expect.soft(geometry!.actionTop, "secondary CTA starts on its own row").toBeGreaterThanOrEqual(geometry!.mainBottom + 2);
});
