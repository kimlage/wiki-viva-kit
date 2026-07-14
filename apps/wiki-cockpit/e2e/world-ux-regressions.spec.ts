import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

const DESKTOP_VIEWPORTS = [
  { width: 1600, height: 780 },
  { width: 1366, height: 768 },
  { width: 1280, height: 720 }
] as const;

const SPATIAL_NATIVE_VIEWS = ["quadrants", "radar", "sources", "work"] as const;
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
  await page.goto("/demo/w?view=quadrants&center=root-alex-rivera");
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator(".sceneShell canvas")).toHaveCount(1, { timeout: 20_000 });
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-runtime-mode", "v8");
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

async function workbenchContrast(page: Page) {
  return page.evaluate(() => {
    type Rgba = { r: number; g: number; b: number; a: number };
    const parse = (value: string): Rgba => {
      const text = value.trim();
      const rgb = text.match(/^rgba?\(\s*([\d.]+)[, ]+\s*([\d.]+)[, ]+\s*([\d.]+)(?:\s*[,/]\s*([\d.]+))?\s*\)$/i);
      if (rgb) return { r: +rgb[1], g: +rgb[2], b: +rgb[3], a: rgb[4] === undefined ? 1 : +rgb[4] };
      const srgb = text.match(/^color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+))?\)$/i);
      if (srgb) return { r: +srgb[1] * 255, g: +srgb[2] * 255, b: +srgb[3] * 255, a: srgb[4] === undefined ? 1 : +srgb[4] };
      const hex = text.match(/^#([0-9a-f]{6})([0-9a-f]{2})?$/i);
      if (hex) return {
        r: parseInt(hex[1].slice(0, 2), 16),
        g: parseInt(hex[1].slice(2, 4), 16),
        b: parseInt(hex[1].slice(4, 6), 16),
        a: hex[2] ? parseInt(hex[2], 16) / 255 : 1
      };
      throw new Error(`unsupported color ${value}`);
    };
    const composite = (foreground: Rgba, background: Rgba): Rgba => {
      const a = foreground.a + background.a * (1 - foreground.a);
      return {
        r: (foreground.r * foreground.a + background.r * background.a * (1 - foreground.a)) / a,
        g: (foreground.g * foreground.a + background.g * background.a * (1 - foreground.a)) / a,
        b: (foreground.b * foreground.a + background.b * background.a * (1 - foreground.a)) / a,
        a
      };
    };
    const luminance = ({ r, g, b }: Rgba) => {
      const channel = (value: number) => {
        const n = value / 255;
        return n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
    };
    const effectiveBackground = (element: Element) => {
      let color = parse(getComputedStyle(document.documentElement).getPropertyValue("--wiki-bg"));
      const ancestors: Element[] = [];
      for (let current: Element | null = element; current; current = current.parentElement) ancestors.unshift(current);
      for (const current of ancestors) {
        const layer = parse(getComputedStyle(current).backgroundColor);
        if (layer.a > 0) color = composite(layer, color);
      }
      return color;
    };
    const targets = [
      ["title", ".packWorkbenchHeader h2"],
      ["intro", ".packWorkbenchHeader p"],
      ["page title", ".packWorkbenchPageTitle strong"],
      ["page summary", ".packWorkbenchPageSummary"],
      ["inventory intro", ".packWorkbenchInventory header p"],
      ["adapter notice", ".packWorkbenchAdapterNotice"]
    ] as const;
    return targets.map(([label, selector]) => {
      const element = document.querySelector<HTMLElement>(selector);
      if (!element) throw new Error(`missing workbench contrast target ${selector}`);
      const foreground = parse(getComputedStyle(element).color);
      const background = effectiveBackground(element);
      const light = Math.max(luminance(foreground), luminance(background));
      const dark = Math.min(luminance(foreground), luminance(background));
      return { label, ratio: Number(((light + 0.05) / (dark + 0.05)).toFixed(3)) };
    });
  });
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
  const scene = page.locator(".sceneShell");
  const sourceNodeCount = await scene.getAttribute("data-scene-source-node-count");
  const localNodeCount = await scene.getAttribute("data-scene-input-node-count");
  expect(Number(sourceNodeCount)).toBeGreaterThan(100);
  expect(Number(localNodeCount)).toBeGreaterThan(1);
  // The source census remains the whole snapshot, while every view projects
  // the same compiler-scoped local world (center + exact direct members).
  expect(Number(localNodeCount)).toBeLessThan(Number(sourceNodeCount));
  await rememberCanvas(page);

  for (const view of SPATIAL_NATIVE_VIEWS) {
    await page.locator(`[data-view-option="${view}"]`).click();
    await expect(workspace).toHaveAttribute("data-world-view", view);
    await expect(workspace).toHaveAttribute("data-world-center", center!);
    await expect(scene).toHaveAttribute("data-scene-center", center!);
    await expect(scene).toHaveAttribute("data-scene-source-node-count", sourceNodeCount!);
    await expect(scene).toHaveAttribute("data-scene-input-node-count", localNodeCount!);
    await expectRememberedCanvas(page);
  }
});

test("all four quadrant lenses work in every spatial native view without changing center", async ({ page }) => {
  await prepareWorld(page);
  const workspace = page.locator(".worldWorkspace");
  const scene = page.locator(".sceneShell");
  const center = await workspace.getAttribute("data-world-center");
  expect(center).toBe("root-alex-rivera");
  await rememberCanvas(page);

  for (const view of SPATIAL_NATIVE_VIEWS) {
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

test("Timeline is a shareable native 2D view over the same mounted world", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  const temporalRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/temporal_graph.json")) temporalRequests.push(request.url());
  });
  await prepareWorld(page);
  expect(temporalRequests).toHaveLength(0);
  await rememberCanvas(page);
  const workspace = page.locator(".worldWorkspace");
  const timeline = page.locator(".timelineSurface");

  await page.locator('[data-view-option="timeline"]').click();
  await expect(workspace).toHaveAttribute("data-world-view", "timeline");
  await expect(page).toHaveURL(/[?&]view=timeline(?:&|$)/);
  await expect(timeline).toBeVisible();
  await expect(page.getByRole("heading", { name: /Chronoscope|Cronoscópio/ })).toBeVisible();
  await expect.poll(() => temporalRequests.length).toBe(1);
  await expect(page.locator(".timelineEvent").first()).toBeVisible();
  await expect(page.locator(".timelineContractWarning")).toHaveCount(0);
  // The committed public graph is clean. Rejected-adapter rendering remains a
  // component contract, while this release flow proves the real snapshot does
  // not invent a warning that is absent from its diagnostic_count.
  await expect(page.locator(".timelineDiagnosticWarning")).toHaveCount(0);
  await expect(page.locator(".sceneShell")).toHaveAttribute("data-scene-suspended", "true");
  await expect(page.getByRole("combobox", { name: /Overlay|Sobreposição/ })).toBeDisabled();
  await expect(page.locator(".worldBreadcrumbs")).toBeHidden();
  const list = page.locator(".timelineEventList");
  const initialScroll = await list.evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
    overflowY: getComputedStyle(element).overflowY
  }));
  expect(initialScroll.clientHeight).toBeGreaterThan(0);
  expect(initialScroll.scrollHeight).toBeGreaterThan(initialScroll.clientHeight);
  expect(initialScroll.overflowY).toMatch(/auto|scroll/);
  const showMore = page.locator(".timelineShowMore");
  await showMore.scrollIntoViewIfNeeded();
  await expect(showMore).toBeVisible();
  const beforeExpansion = await page.locator(".timelineEvent").count();
  await showMore.click();
  await expect.poll(() => page.locator(".timelineEvent").count()).toBeGreaterThan(beforeExpansion);
  await expect(page.locator(".sceneCanvasFrame")).toHaveAttribute("aria-hidden", "true");
  expect(await page.locator(".sceneCanvasFrame").evaluate((element) => (element as HTMLElement).inert)).toBe(true);
  await expectRememberedCanvas(page);

  await page.getByRole("button", { name: /When it was recorded|Quando foi registrado/ }).click();
  await expect(page).toHaveURL(/[?&]time_mode=recorded(?:&|$)/);
  await page.locator(".timelineLaneControls button").filter({ hasText: /Actions|Ações/ }).click();
  await expect(page).toHaveURL(/[?&]time_lanes=action(?:&|$)/);
  await expectRememberedCanvas(page);

  await page.goBack();
  await expect(page).not.toHaveURL(/[?&]time_lanes=action(?:&|$)/);
  await page.goBack();
  await expect(page).not.toHaveURL(/[?&]time_mode=recorded(?:&|$)/);
  await expect(page.getByRole("button", { name: /Semantic event time|Tempo semântico do evento/ })).toHaveAttribute("aria-pressed", "true");
  await page.goForward();
  await expect(page).toHaveURL(/[?&]time_mode=recorded(?:&|$)/);
  await page.goForward();
  await expect(page).toHaveURL(/[?&]time_lanes=action(?:&|$)/);
  await page.reload();
  await expect(page.getByRole("heading", { name: /Chronoscope|Cronoscópio/ })).toBeVisible();
  await expect(page).toHaveURL(/[?&]time_mode=recorded(?:&|$)/);
  // A full document reload creates a new WebGL host by definition; remember
  // that new host and keep proving continuity for the interactions after it.
  await rememberCanvas(page);

  const firstEvent = page.locator(".timelineEvent").first();
  await firstEvent.click();
  await expect(page).toHaveURL(/[?&]time_cursor=[^&]+/);
  const openPage = page.getByRole("button", { name: /Open canonical page|Abrir página canônica/ });
  if (await openPage.count()) {
    await openPage.click();
    await expect(page.locator(".pageReader")).toBeVisible();
    await expect(timeline).toHaveAttribute("aria-hidden", "true");
    expect(await timeline.evaluate((element) => (element as HTMLElement).inert)).toBe(true);
    await page.getByRole("button", { name: /Close reader|Fechar leitor/ }).click();
    await expect(timeline).not.toHaveAttribute("aria-hidden", "true");
  }
  await expectRememberedCanvas(page);
});

test("Timeline keeps stale cursors explicit and provides one keyboard path to the inspector", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 780 });
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.goto("/demo/w?center=root-alex-rivera&view=timeline&time_cursor=evt-missing&tour=0");
  await expect(page.locator(".timelineInspector strong").filter({
    hasText: /shared event is outside|evento compartilhado está fora/i
  })).toBeVisible();
  await expect(page.locator('.timelineEvent[aria-current="true"]')).toHaveCount(0);

  const events = page.locator(".timelineEvent");
  await expect(events.first()).toBeVisible();
  await expect(page.locator('.timelineEvent[tabindex="0"]')).toHaveCount(1);
  await events.first().focus();
  await page.keyboard.press("ArrowDown");
  await expect(page).toHaveURL(/[?&]time_cursor=[^&]+/);
  await expect(page.locator('.timelineEvent[aria-current="true"]')).toHaveCount(1);
  await expect(page.locator('.timelineEvent[tabindex="0"]')).toHaveCount(1);

  await page.locator(".timelineLaneControls button").filter({ hasText: /Actions|Ações/ }).click();
  await expect(page).not.toHaveURL(/[?&]time_cursor=/);
});

test("Timeline keeps one scroll model and 44px controls on mobile and fallback", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.goto("/demo/w?center=root-alex-rivera&view=timeline&lens=all&overlay=evidence&visual=1&tour=0");
  const timeline = page.locator(".timelineSurface");
  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(timeline).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".sceneFallback")).toHaveAttribute("aria-hidden", "true");

  const geometry = await timeline.evaluate((surface) => {
    const controls = [...surface.querySelectorAll<HTMLElement>("button, input")].filter((element) => {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    });
    const rect = surface.getBoundingClientRect();
    const navigatorViews = [
      ...document.querySelectorAll<HTMLElement>(".worldNavigatorViewControls .worldNavigatorView")
    ];
    return {
      minWidth: Math.min(...controls.map((element) => element.getBoundingClientRect().width)),
      minHeight: Math.min(...controls.map((element) => element.getBoundingClientRect().height)),
      navigatorViewCount: navigatorViews.length,
      navigatorLabelOverflow: Math.max(
        0,
        ...navigatorViews.map((element) => element.scrollWidth - element.clientWidth)
      ),
      surface: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom },
      viewport: { width: window.innerWidth, height: window.innerHeight },
      documentOverflow: Math.max(
        document.documentElement.scrollWidth - document.documentElement.clientWidth,
        document.body.scrollWidth - document.documentElement.clientWidth
      )
    };
  });
  expect.soft(geometry.minWidth).toBeGreaterThanOrEqual(44);
  expect.soft(geometry.minHeight).toBeGreaterThanOrEqual(44);
  expect.soft(geometry.navigatorViewCount).toBe(5);
  expect.soft(geometry.navigatorLabelOverflow).toBeLessThanOrEqual(0);
  expect.soft(geometry.surface.left).toBeGreaterThanOrEqual(0);
  expect.soft(geometry.surface.right).toBeLessThanOrEqual(geometry.viewport.width + 1);
  expect.soft(geometry.surface.top).toBeGreaterThanOrEqual(0);
  expect.soft(geometry.surface.bottom).toBeLessThanOrEqual(geometry.viewport.height + 1);
  expect.soft(geometry.documentOverflow).toBeLessThanOrEqual(1);

  const actionsLane = page.locator(".timelineLaneControls button").filter({ hasText: /Actions|Ações/ });
  await actionsLane.click();
  await expect(actionsLane).toHaveAttribute("aria-pressed", "true");
  await expect(page).toHaveURL(/[?&]time_lanes=action(?:&|$)/);

  const firstEvent = page.locator(".timelineEvent").first();
  await firstEvent.scrollIntoViewIfNeeded();
  await firstEvent.click();
  await expect(firstEvent).toHaveAttribute("aria-controls", "timeline-inspector");
  await expect(firstEvent).toHaveAttribute("aria-current", "true");
  const inspectorHeading = page.locator(".timelineInspector h3");
  await expect(inspectorHeading).toBeVisible();
  await expect.poll(() => inspectorHeading.evaluate((element) => document.activeElement === element)).toBe(true);
  const inspectorRect = await inspectorHeading.boundingBox();
  expect(inspectorRect).not.toBeNull();
  expect(inspectorRect!.y).toBeGreaterThanOrEqual(0);
  expect(inspectorRect!.y + inspectorRect!.height).toBeLessThanOrEqual(845);

  // Regression: at this exact scroll position the constrained fifth grid row
  // used to collapse to zero. The list and inspector then painted outside
  // their boxes and on top of each other despite retaining the right DOM order.
  await timeline.evaluate((surface) => { surface.scrollTop = 350; });
  await expect.poll(() => timeline.evaluate((surface) => surface.scrollTop)).toBe(350);
  const mobileFlow = await timeline.evaluate((surface) => {
    const body = surface.querySelector<HTMLElement>(".timelineBody")!;
    const list = surface.querySelector<HTMLElement>(".timelineEventList")!;
    const inspector = surface.querySelector<HTMLElement>(".timelineInspector")!;
    const lastEvent = list.querySelector<HTMLElement>("li:last-child")!;
    const lastDetail = inspector.lastElementChild as HTMLElement;
    const listRect = list.getBoundingClientRect();
    const inspectorRect = inspector.getBoundingClientRect();
    return {
      bodyHeight: body.getBoundingClientRect().height,
      directChildOrder:
        body.children[0] === list &&
        body.children[1] === inspector &&
        Boolean(list.compareDocumentPosition(inspector) & Node.DOCUMENT_POSITION_FOLLOWING),
      visualGap: inspectorRect.top - listRect.bottom,
      listContentOverflow: list.scrollHeight - list.clientHeight,
      inspectorContentOverflow: inspector.scrollHeight - inspector.clientHeight,
      lastEventOverflow: lastEvent.getBoundingClientRect().bottom - listRect.bottom,
      lastDetailOverflow: lastDetail.getBoundingClientRect().bottom - inspectorRect.bottom,
      surfaceHorizontalOverflow: surface.scrollWidth - surface.clientWidth,
      documentHorizontalOverflow: Math.max(
        document.documentElement.scrollWidth - document.documentElement.clientWidth,
        document.body.scrollWidth - document.documentElement.clientWidth
      )
    };
  });
  expect.soft(mobileFlow.bodyHeight).toBeGreaterThan(0);
  expect.soft(mobileFlow.directChildOrder).toBe(true);
  expect.soft(mobileFlow.visualGap).toBeGreaterThanOrEqual(0);
  expect.soft(mobileFlow.listContentOverflow).toBeLessThanOrEqual(1);
  expect.soft(mobileFlow.inspectorContentOverflow).toBeLessThanOrEqual(1);
  expect.soft(mobileFlow.lastEventOverflow).toBeLessThanOrEqual(1);
  expect.soft(mobileFlow.lastDetailOverflow).toBeLessThanOrEqual(1);
  expect.soft(mobileFlow.surfaceHorizontalOverflow).toBeLessThanOrEqual(1);
  expect.soft(mobileFlow.documentHorizontalOverflow).toBeLessThanOrEqual(1);

  await inspectorHeading.scrollIntoViewIfNeeded();
  await expect(inspectorHeading).toBeVisible();
  const readableDetail = await inspectorHeading.evaluate((heading) => {
    const surface = heading.closest<HTMLElement>(".timelineSurface")!;
    const headingRect = heading.getBoundingClientRect();
    const surfaceRect = surface.getBoundingClientRect();
    const hitTarget = document.elementFromPoint(
      headingRect.left + headingRect.width / 2,
      headingRect.top + headingRect.height / 2
    );
    const style = getComputedStyle(heading);
    return {
      text: heading.textContent?.trim() ?? "",
      fullyReachable:
        headingRect.top >= surfaceRect.top - 1 &&
        headingRect.bottom <= surfaceRect.bottom + 1,
      topmost: hitTarget === heading || heading.contains(hitTarget),
      fontSize: Number.parseFloat(style.fontSize),
      opacity: Number.parseFloat(style.opacity)
    };
  });
  expect.soft(readableDetail.text.length).toBeGreaterThan(0);
  expect.soft(readableDetail.fullyReachable).toBe(true);
  expect.soft(readableDetail.topmost).toBe(true);
  expect.soft(readableDetail.fontSize).toBeGreaterThanOrEqual(16);
  expect.soft(readableDetail.opacity).toBe(1);
});

test("demo gate offers guided tour, free exploration and from-zero entry paths", async ({ page }) => {
  await page.goto("/demo");

  const doors = page.locator(".demoGateDoor");
  await expect(doors).toHaveCount(5);
  await expect(page.locator('.demoGateDoor.guided[href="/demo/world?tour=1"]')).toContainText(/Visita guiada|Guided tour/);
  await expect(page.locator('.demoGateDoor.world[href="/demo/world?tour=0"]')).toContainText(/Explorar livremente|Explore freely/);
  await expect(page.locator('.demoGateDoor.genesis[href="/demo/genesis"]')).toContainText(/Começar do zero|Start from zero/);
  await expect(page.locator('.demoGateDoor.study[href*="demo_scenario=study_research_showcase"]')).toContainText(/Estudos e Pesquisa|Study & Research/);
  await expect(page.locator('.demoGateDoor.finance[href*="demo_scenario=personal_finance_showcase"]')).toContainText(/Finanças Pessoais|Personal Finance/);
  const labs = page.locator(".demoValidationLabs");
  await expect(labs.locator("summary")).toContainText(/Laboratórios de validação|Validation labs/);
  await labs.locator("summary").click();
  await expect(labs.locator(".demoValidationLab")).toHaveCount(7);
});

for (const fixture of [
  {
    label: "Study & Research",
    scenario: "study_research_showcase",
    root: "root-study-research-showcase",
    pack: "study-research",
    view: "study-research.evidence-matrix",
    viewport: { width: 1280, height: 780 },
    appearance: { theme: "luminous-observatory", density: "balanced" }
  },
  {
    label: "Personal Finance mobile",
    scenario: "personal_finance_showcase",
    root: "root-personal-finance-showcase",
    pack: "personal-finance",
    view: "personal-finance.category-variance",
    viewport: { width: 390, height: 844 },
    appearance: { theme: "night-mission-control", density: "command" }
  }
] as const) {
  test(`${fixture.label} pack view round-trips, reads canonical pages and hands temporal profiles to Chronoscope`, async ({ page }) => {
    await page.setViewportSize(fixture.viewport);
    await page.addInitScript(({ appearance }) => {
      window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
      window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
      window.localStorage.setItem("wikiCockpitAppearance.v1", JSON.stringify(appearance));
    }, { appearance: fixture.appearance });
    await page.goto(
      `/demo/w?demo_scenario=${fixture.scenario}&center=${fixture.root}&view=quadrants&overlay=evidence&tour=0`
    );
    await expect(page.locator(".worldNavigator")).toBeVisible({ timeout: 20_000 });
    await rememberCanvas(page);

    const extensionButton = page.locator('.worldNavigatorPackBadge[data-active-pack-count="1"]');
    await expect(extensionButton).toBeVisible();
    await extensionButton.click();
    const packView = page.locator(`[data-pack-view-card="${fixture.view}"]`);
    await expect(packView).toBeVisible();
    await packView.click();

    const workbench = page.locator(`.packWorkbenchSurface[data-pack-id="${fixture.pack}"]`);
    await expect(workbench).toBeVisible();
    await expect(workbench).toHaveAttribute("data-pack-view", fixture.view);
    await expect.poll(() => new URL(page.url()).searchParams.get("pack_view")).toBe(fixture.view);
    await expect(page.locator(".sceneShell")).toHaveAttribute("data-scene-suspended", "true");
    await expect(page.locator(".sceneCanvasFrame")).toHaveAttribute("aria-hidden", "true");
    await expectRememberedCanvas(page);
    await expect(page.locator("html")).toHaveAttribute("data-wiki-theme", fixture.appearance.theme);
    await expect(page.locator("html")).toHaveAttribute("data-wiki-density", fixture.appearance.density);
    for (const row of await workbenchContrast(page)) {
      expect.soft(row.ratio, `${fixture.label}: ${row.label} contrast`).toBeGreaterThanOrEqual(4.5);
    }

    const protectedRoute = page.url();
    const protectedWorld = await page.locator(".worldWorkspace").evaluate((workspace) => ({
      center: workspace.dataset.worldCenter,
      view: workspace.dataset.worldView
    }));
    for (const key of ["2", "q", "w", "Enter", "/"]) {
      await page.keyboard.press(key);
      expect(page.url(), `${fixture.label}: global ${key} shortcut stayed blocked`).toBe(protectedRoute);
      await expect(page.locator(".pageReader")).toHaveCount(0);
      await expect(page.locator(".packWorkbenchSurface")).toBeVisible();
    }
    const backgroundFocusLeaks = await page.evaluate(() => {
      const selectors = [
        ".worldCommandBar button",
        ".quadrantCompass button",
        ".focusLegend button",
        ".worldMinimap button",
        ".radarStatusStrip button",
        ".sceneCanvasFrame [tabindex='0']",
        ".sceneFallback [tabindex='0']"
      ];
      return selectors.flatMap((selector) => [...document.querySelectorAll<HTMLElement>(selector)])
        .filter((element) => {
          const style = getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          return element.tabIndex >= 0 &&
            !element.closest("[inert], [aria-hidden='true']") &&
            style.visibility !== "hidden" &&
            style.display !== "none" &&
            rect.width > 0 &&
            rect.height > 0;
        })
        .map((element) => element.className || element.tagName);
    });
    expect(backgroundFocusLeaks).toEqual([]);

    await page.keyboard.press("Escape");
    await expect(page.locator(".packWorkbenchSurface")).toHaveCount(0);
    await expect.poll(() => new URL(page.url()).searchParams.get("pack_view")).toBeNull();
    await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", protectedWorld.center!);
    await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-view", protectedWorld.view!);
    await page.goto(protectedRoute);
    await expect(page.locator(`.packWorkbenchSurface[data-pack-id="${fixture.pack}"]`)).toBeVisible({ timeout: 20_000 });

    await expect(workbench.locator(".packWorkbenchBlockPackages li")).toHaveCount(2);
    await expect(workbench.locator(".packWorkbenchAdapterNotice")).toBeVisible();
    await expect.poll(() => workbench.locator(".packWorkbenchInventoryGroup button:disabled").count()).toBeGreaterThan(0);
    await expect.poll(() => workbench.locator("[data-pack-page-id]").count()).toBeGreaterThan(0);

    const pageButtons = workbench.locator(".packWorkbenchPageGrid article > button");
    const firstPage = pageButtons.first();
    await firstPage.focus();
    if (await pageButtons.count() > 1) {
      await page.keyboard.press("ArrowDown");
      await expect.poll(() => pageButtons.nth(1).evaluate((element) => document.activeElement === element)).toBe(true);
    }
    await page.keyboard.press("Enter");
    const reader = page.locator(".pageReader");
    await expect(reader).toBeVisible();
    await expect(workbench).toHaveAttribute("aria-hidden", "true");
    expect(await workbench.evaluate((element) => (element as HTMLElement).inert)).toBe(true);
    await page.getByRole("button", { name: /Close reader|Fechar leitor/ }).click();
    await expect(workbench).not.toHaveAttribute("aria-hidden", "true");
    await expect.poll(() => new URL(page.url()).searchParams.get("pack_view")).toBe(fixture.view);

    if (fixture.viewport.width <= 640) {
      const geometry = await workbench.evaluate((surface) => {
        const rect = surface.getBoundingClientRect();
        const controls = [...surface.querySelectorAll<HTMLElement>("button:not(:disabled), input")].filter((element) => {
          const box = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return box.width > 0 && box.height > 0 && style.display !== "none" && style.visibility !== "hidden";
        });
        return {
          left: rect.left,
          right: rect.right,
          viewportWidth: window.innerWidth,
          minControlHeight: Math.min(...controls.map((element) => element.getBoundingClientRect().height)),
          documentOverflow: Math.max(
            document.documentElement.scrollWidth - document.documentElement.clientWidth,
            document.body.scrollWidth - document.documentElement.clientWidth
          )
        };
      });
      expect.soft(geometry.left).toBeGreaterThanOrEqual(0);
      expect.soft(geometry.right).toBeLessThanOrEqual(geometry.viewportWidth + 1);
      expect.soft(geometry.minControlHeight).toBeGreaterThanOrEqual(44);
      expect.soft(geometry.documentOverflow).toBeLessThanOrEqual(1);
    }

    await page.reload();
    await expect(page.locator(`.packWorkbenchSurface[data-pack-id="${fixture.pack}"]`)).toBeVisible({ timeout: 20_000 });
    await expect.poll(() => new URL(page.url()).searchParams.get("pack_view")).toBe(fixture.view);
    const timelineProfile = page.locator(".packWorkbenchTimelineProfiles button").first();
    await expect(timelineProfile).toBeVisible();
    await timelineProfile.click();
    await expect.poll(() => new URL(page.url()).searchParams.get("pack_view")).toBeNull();
    await expect.poll(() => new URL(page.url()).searchParams.get("view")).toBe("timeline");
    await expect(page.getByRole("heading", { name: /Chronoscope|Cronoscópio/ })).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".timelinePackProfiles")).toBeVisible();
  });
}

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
