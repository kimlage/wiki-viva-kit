import type { Page, TestInfo } from "@playwright/test";
import { attachViewportScreenshot, expect, test } from "./fixtures";

const THEMES = [
  { id: "luminous-observatory", colorScheme: "light" },
  { id: "night-mission-control", colorScheme: "dark" }
] as const;

const DENSITIES = ["focus", "balanced", "command"] as const;
type ThemeId = (typeof THEMES)[number]["id"];
type DensityId = (typeof DENSITIES)[number];

const WORLD_PATH = "/demo/w?center=root-alex-rivera&view=quadrants&overlay=evidence&tour=0";

test.describe.configure({ timeout: 60_000 });

async function prepareAppearance(
  page: Page,
  options: {
    viewport?: { width: number; height: number };
    appearance?: { theme: ThemeId; density: DensityId };
  } = {}
) {
  if (options.viewport) await page.setViewportSize(options.viewport);
  await page.addInitScript(({ appearance }) => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
    if (appearance) window.localStorage.setItem("wikiCockpitAppearance.v1", JSON.stringify(appearance));
  }, { appearance: options.appearance });
  await page.goto(WORLD_PATH);
  await expect(page.locator(".worldWorkspace")).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".appearanceControl > summary")).toBeVisible();
}

async function openAppearance(page: Page) {
  const control = page.locator(".appearanceControl");
  if (await control.getAttribute("open") === null) await control.locator(":scope > summary").click();
  await expect(control.locator(".appearanceControlMenu")).toBeVisible();
}

function themeButton(page: Page, theme: ThemeId) {
  return page.locator(".appearanceOption", {
    has: page.locator(`.appearanceThemeSwatch--${theme}`)
  });
}

function densityButton(page: Page, density: DensityId) {
  return page.locator(".appearanceDensityOptions button").nth(DENSITIES.indexOf(density));
}

async function chooseAppearance(page: Page, theme: ThemeId, density: DensityId) {
  await openAppearance(page);
  await themeButton(page, theme).click();
  await densityButton(page, density).click();
  await expect(page.locator("html")).toHaveAttribute("data-wiki-theme", theme);
  await expect(page.locator("html")).toHaveAttribute("data-wiki-density", density);
  await expect(themeButton(page, theme)).toHaveAttribute("aria-pressed", "true");
  await expect(densityButton(page, density)).toHaveAttribute("aria-pressed", "true");
}

async function waitForAppearanceSettled(page: Page) {
  await page.waitForFunction(() => {
    const surfaces = [
      document.documentElement,
      document.body,
      document.querySelector(".topBar"),
      document.querySelector(".demoBanner"),
      document.querySelector(".worldRuntimeControls"),
      document.querySelector(".appearanceControlMenu")
    ].filter((value): value is Element => value instanceof Element);
    return surfaces.every((surface) =>
      surface.getAnimations({ subtree: true }).every((animation) => animation.playState !== "running")
    );
  }, undefined, { timeout: 3_000 });
  await page.evaluate(() => new Promise<void>((resolve) =>
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
  ));
}

async function rememberWorldSurface(page: Page) {
  await page.evaluate(() => {
    const testWindow = window as Window & {
      __appearanceScene?: Element | null;
      __appearanceCanvas?: Element | null;
    };
    testWindow.__appearanceScene = document.querySelector(".sceneShell");
    testWindow.__appearanceCanvas = document.querySelector(".sceneShell canvas");
  });
}

async function expectRememberedWorldSurface(page: Page) {
  const evidence = await page.evaluate(() => {
    const testWindow = window as Window & {
      __appearanceScene?: Element | null;
      __appearanceCanvas?: Element | null;
    };
    const currentCanvas = document.querySelector(".sceneShell canvas");
    return {
      sceneStable: document.querySelector(".sceneShell") === testWindow.__appearanceScene,
      canvasWasMounted: Boolean(testWindow.__appearanceCanvas),
      canvasStable: currentCanvas === testWindow.__appearanceCanvas
    };
  });
  expect(evidence.sceneStable).toBe(true);
  if (evidence.canvasWasMounted) expect(evidence.canvasStable).toBe(true);
}

async function appearanceGeometry(page: Page) {
  return page.locator(".appearanceControl").evaluate((control) => {
    const visible = (element: HTMLElement) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    };
    const controls = [...control.querySelectorAll<HTMLElement>("summary, button")].filter(visible);
    const targetRects = controls.map((element) => {
      const rect = element.getBoundingClientRect();
      return {
        label: element.getAttribute("aria-label") || element.textContent?.trim().replace(/\s+/g, " ").slice(0, 80) || element.tagName,
        width: rect.width,
        height: rect.height
      };
    });
    const menu = control.querySelector<HTMLElement>(".appearanceControlMenu")?.getBoundingClientRect();
    const root = document.documentElement;
    const body = document.body;
    return {
      targetRects,
      minWidth: Math.min(...targetRects.map((rect) => rect.width)),
      minHeight: Math.min(...targetRects.map((rect) => rect.height)),
      menu: menu ? { left: menu.left, right: menu.right, top: menu.top, bottom: menu.bottom } : null,
      viewport: { width: window.innerWidth, height: window.innerHeight, dpr: window.devicePixelRatio },
      overflow: {
        horizontal: Math.max(root.scrollWidth - root.clientWidth, body.scrollWidth - root.clientWidth),
        vertical: Math.max(root.scrollHeight - root.clientHeight, body.scrollHeight - root.clientHeight)
      }
    };
  });
}

function expectAppearanceGeometry(
  geometry: Awaited<ReturnType<typeof appearanceGeometry>>,
  label: string
) {
  expect.soft(geometry.minWidth, `${label}: narrowest appearance target`).toBeGreaterThanOrEqual(44);
  expect.soft(geometry.minHeight, `${label}: shortest appearance target`).toBeGreaterThanOrEqual(44);
  expect.soft(geometry.overflow.horizontal, `${label}: horizontal document overflow`).toBeLessThanOrEqual(1);
  expect.soft(geometry.overflow.vertical, `${label}: vertical document overflow`).toBeLessThanOrEqual(1);
  expect(geometry.menu).not.toBeNull();
  expect.soft(geometry.menu!.left, `${label}: menu left`).toBeGreaterThanOrEqual(0);
  expect.soft(geometry.menu!.right, `${label}: menu right`).toBeLessThanOrEqual(geometry.viewport.width + 1);
  expect.soft(geometry.menu!.top, `${label}: menu top`).toBeGreaterThanOrEqual(0);
  expect.soft(geometry.menu!.bottom, `${label}: menu bottom`).toBeLessThanOrEqual(geometry.viewport.height + 1);
}

async function attachGeometry(testInfo: TestInfo, name: string, geometry: unknown) {
  await testInfo.attach(`${name}.json`, {
    body: Buffer.from(`${JSON.stringify(geometry, null, 2)}\n`, "utf8"),
    contentType: "application/json"
  });
}

const WORLD_CONTRAST_TARGETS = [
  ["top bar brand", ".topBar > div:first-child > strong"],
  ["top bar repository", ".topBar > div:first-child > span"],
  ["read-only demo banner", ".demoBanner"],
  ["inactive native view", ".runtimeControl:not(.active):not(:disabled)"],
  ["active native view", ".runtimeControl.active"],
  ["overlay select", ".worldRuntimeSelect select"],
  ["appearance panel heading", ".appearanceControlMenu header strong"]
] as const;

async function renderedContrast(
  page: Page,
  targets: readonly (readonly [string, string])[] = WORLD_CONTRAST_TARGETS
) {
  return page.evaluate((contrastTargets) => {
    type Rgba = { r: number; g: number; b: number; a: number };
    const parse = (value: string): Rgba => {
      const text = value.trim();
      const hex = text.match(/^#([0-9a-f]{6})([0-9a-f]{2})?$/i);
      if (hex) {
        return {
          r: Number.parseInt(hex[1].slice(0, 2), 16),
          g: Number.parseInt(hex[1].slice(2, 4), 16),
          b: Number.parseInt(hex[1].slice(4, 6), 16),
          a: hex[2] ? Number.parseInt(hex[2], 16) / 255 : 1
        };
      }
      const rgb = text.match(/^rgba?\(\s*([\d.]+)[, ]+\s*([\d.]+)[, ]+\s*([\d.]+)(?:\s*[,/]\s*([\d.]+)%?)?\s*\)$/i);
      if (rgb) {
        const alpha = rgb[4] === undefined
          ? 1
          : Number(rgb[4]) / (text.includes(`${rgb[4]}%`) ? 100 : 1);
        return { r: Number(rgb[1]), g: Number(rgb[2]), b: Number(rgb[3]), a: alpha };
      }
      const srgb = text.match(/^color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+))?\)$/i);
      if (srgb) {
        return {
          r: Number(srgb[1]) * 255,
          g: Number(srgb[2]) * 255,
          b: Number(srgb[3]) * 255,
          a: srgb[4] === undefined ? 1 : Number(srgb[4])
        };
      }
      throw new Error(`unsupported computed color: ${value}`);
    };
    const composite = (foreground: Rgba, background: Rgba): Rgba => {
      const alpha = foreground.a + background.a * (1 - foreground.a);
      if (alpha <= 0) return { r: 0, g: 0, b: 0, a: 0 };
      return {
        r: (foreground.r * foreground.a + background.r * background.a * (1 - foreground.a)) / alpha,
        g: (foreground.g * foreground.a + background.g * background.a * (1 - foreground.a)) / alpha,
        b: (foreground.b * foreground.a + background.b * background.a * (1 - foreground.a)) / alpha,
        a: alpha
      };
    };
    const luminance = (color: Rgba) => {
      const channel = (value: number) => {
        const normalized = value / 255;
        return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
    };
    const ratio = (left: Rgba, right: Rgba) => {
      const lighter = Math.max(luminance(left), luminance(right));
      const darker = Math.min(luminance(left), luminance(right));
      return (lighter + 0.05) / (darker + 0.05);
    };
    const effectiveBackground = (element: Element) => {
      const rootToken = getComputedStyle(document.documentElement).getPropertyValue("--wiki-bg");
      let result = parse(rootToken);
      const chain: Element[] = [];
      for (let current: Element | null = element; current; current = current.parentElement) chain.unshift(current);
      for (const current of chain) {
        const color = parse(getComputedStyle(current).backgroundColor);
        if (color.a > 0) result = composite(color, result);
      }
      return result;
    };
    return contrastTargets.map(([label, selector]) => {
      const element = document.querySelector<HTMLElement>(selector);
      if (!element) throw new Error(`contrast target is missing: ${selector}`);
      const foreground = parse(getComputedStyle(element).color);
      const background = effectiveBackground(element);
      return {
        label,
        selector,
        foreground,
        background,
        ratio: Number(ratio(foreground, background).toFixed(3))
      };
    });
  }, targets);
}

for (const theme of THEMES) {
  for (const density of DENSITIES) {
    test(`appearance ${theme.id} × ${density} preserves world state, information and hit targets`, async ({ page }, testInfo) => {
      await prepareAppearance(page, { viewport: { width: 1280, height: 900 } });
      const routeBefore = page.url();
      const worldBefore = await page.locator(".worldWorkspace").evaluate((workspace) => ({
        center: workspace.dataset.worldCenter,
        view: workspace.dataset.worldView,
        overlay: workspace.dataset.worldOverlay,
        sourceNodes: workspace.querySelector(".sceneShell")?.getAttribute("data-scene-source-node-count"),
        inputNodes: workspace.querySelector(".sceneShell")?.getAttribute("data-scene-input-node-count")
      }));
      await rememberWorldSurface(page);

      await chooseAppearance(page, theme.id, density);
      await waitForAppearanceSettled(page);
      expect(page.url()).toBe(routeBefore);
      await expectRememberedWorldSurface(page);
      await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", worldBefore.center!);
      await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-view", worldBefore.view!);
      await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-overlay", worldBefore.overlay!);
      const worldAfter = await page.locator(".sceneShell").evaluate((scene) => ({
        sourceNodes: scene.getAttribute("data-scene-source-node-count"),
        inputNodes: scene.getAttribute("data-scene-input-node-count")
      }));
      expect(worldAfter).toEqual({ sourceNodes: worldBefore.sourceNodes, inputNodes: worldBefore.inputNodes });
      await expect.poll(() => page.evaluate(() => JSON.parse(window.localStorage.getItem("wikiCockpitAppearance.v1") || "{}"))).toEqual({
        theme: theme.id,
        density
      });
      expect(await page.locator("html").evaluate((root) => getComputedStyle(root).colorScheme)).toContain(theme.colorScheme);

      const geometry = await appearanceGeometry(page);
      expectAppearanceGeometry(geometry, `${theme.id}/${density}`);
      const contrast = await renderedContrast(page);
      await attachGeometry(testInfo, `appearance-${theme.id}-${density}`, geometry);
      await attachGeometry(testInfo, `appearance-${theme.id}-${density}-contrast`, contrast);
      for (const row of contrast) {
        expect.soft(row.ratio, `${theme.id}/${density}: ${row.label} contrast`).toBeGreaterThanOrEqual(4.5);
      }
      await attachViewportScreenshot(page, testInfo, `appearance-${theme.id}-${density}`);

      await page.reload();
      await expect(page.locator(".worldWorkspace")).toBeVisible({ timeout: 20_000 });
      await expect(page.locator("html")).toHaveAttribute("data-wiki-theme", theme.id);
      await expect(page.locator("html")).toHaveAttribute("data-wiki-density", density);
      expect(page.url()).toBe(routeBefore);
      await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", worldBefore.center!);
      await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-view", worldBefore.view!);
      await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-overlay", worldBefore.overlay!);
    });
  }
}

test("demo gate and validation gallery honor both themes on desktop and mobile with rendered contrast", async ({ page }, testInfo) => {
  const targets = [
    ["demo title", ".demoGateInner h1"],
    ["demo subtitle", ".demoGateSubtitle"],
    ["guided title", ".demoGateDoor.guided strong"],
    ["guided description", ".demoGateDoor.guided span"],
    ["study pack title", ".demoGateDoor.pack.study strong"],
    ["finance pack title", ".demoGateDoor.pack.finance strong"],
    ["lab summary", ".demoValidationLabs > summary strong"],
    ["lab summary description", ".demoValidationLabs > summary small"],
    ["lab title", ".demoValidationLab strong"],
    ["lab description", ".demoValidationLab small"]
  ] as const;

  for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.goto("/demo");
    for (const theme of THEMES) {
      await page.evaluate(({ themeId }) => {
        window.localStorage.setItem(
          "wikiCockpitAppearance.v1",
          JSON.stringify({ theme: themeId, density: "balanced" })
        );
      }, { themeId: theme.id });
      await page.reload();
      await expect(page.locator("html")).toHaveAttribute("data-wiki-theme", theme.id);
      await expect(page.locator(".demoGate")).toBeVisible();
      const labs = page.locator(".demoValidationLabs");
      await labs.locator(":scope > summary").click();
      await expect(labs).toHaveAttribute("open", "");
      await waitForAppearanceSettled(page);

      const contrast = await renderedContrast(page, targets);
      for (const row of contrast) {
        expect.soft(
          row.ratio,
          `${theme.id}/${viewport.width}x${viewport.height}: ${row.label} contrast`
        ).toBeGreaterThanOrEqual(4.5);
      }
      const geometry = await page.locator(".demoGateInner").evaluate((inner) => ({
        viewport: { width: window.innerWidth, height: window.innerHeight },
        left: inner.getBoundingClientRect().left,
        right: inner.getBoundingClientRect().right,
        horizontalOverflow: Math.max(
          document.documentElement.scrollWidth - document.documentElement.clientWidth,
          document.body.scrollWidth - document.documentElement.clientWidth
        ),
        minimumTargetHeight: Math.min(
          ...[...inner.querySelectorAll<HTMLElement>("a, summary")]
            .filter((element) => {
              const rect = element.getBoundingClientRect();
              return rect.width > 0 && rect.height > 0;
            })
            .map((element) => element.getBoundingClientRect().height)
        )
      }));
      expect.soft(geometry.left).toBeGreaterThanOrEqual(0);
      expect.soft(geometry.right).toBeLessThanOrEqual(viewport.width + 1);
      expect.soft(geometry.horizontalOverflow).toBeLessThanOrEqual(1);
      expect.soft(geometry.minimumTargetHeight).toBeGreaterThanOrEqual(44);
      await attachGeometry(testInfo, `demo-gate-${theme.id}-${viewport.width}x${viewport.height}-contrast`, contrast);
      await attachGeometry(testInfo, `demo-gate-${theme.id}-${viewport.width}x${viewport.height}-geometry`, geometry);
      await attachViewportScreenshot(page, testInfo, `demo-gate-${theme.id}-${viewport.width}x${viewport.height}`);
    }
  }
});

test("appearance survives a deterministic 200% effective zoom viewport without clipping or state loss", async ({ page }, testInfo) => {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    mobile: false,
    width: 640,
    height: 450,
    screenWidth: 1280,
    screenHeight: 900,
    deviceScaleFactor: 2
  });
  try {
    await prepareAppearance(page, {
      appearance: { theme: "luminous-observatory", density: "command" }
    });
    const routeBefore = page.url();
    await openAppearance(page);
    const geometry = await appearanceGeometry(page);
    expect(geometry.viewport).toEqual({ width: 640, height: 450, dpr: 2 });
    expect(geometry.viewport.width * geometry.viewport.dpr).toBe(1280);
    expect(geometry.viewport.height * geometry.viewport.dpr).toBe(900);
    expectAppearanceGeometry(geometry, "200% effective zoom");
    expect(page.url()).toBe(routeBefore);
    await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", "root-alex-rivera");
    await attachGeometry(testInfo, "appearance-zoom-200", geometry);
    await attachViewportScreenshot(page, testInfo, "appearance-zoom-200");
  } finally {
    await cdp.detach();
  }
});

test("forced colors preserves selected state, system color adjustment and visible focus", async ({ page }, testInfo) => {
  await page.emulateMedia({ forcedColors: "active" });
  await prepareAppearance(page, {
    viewport: { width: 1280, height: 900 },
    appearance: { theme: "luminous-observatory", density: "command" }
  });
  expect(await page.evaluate(() => window.matchMedia("(forced-colors: active)").matches)).toBe(true);

  const summary = page.locator(".appearanceControl > summary");
  await summary.press("Enter");
  for (let index = 0; index < 5; index += 1) await page.keyboard.press("Tab");
  const selectedDensity = densityButton(page, "command");
  await expect.poll(() => selectedDensity.evaluate((element) => document.activeElement === element)).toBe(true);
  const forcedEvidence = await page.locator(".appearanceControl").evaluate((control) => {
    const selected = control.querySelector<HTMLElement>('.appearanceDensityOptions button[aria-pressed="true"]')!;
    const selectedStyle = getComputedStyle(selected);
    return {
      forcedColorAdjust: selectedStyle.forcedColorAdjust,
      outlineStyle: selectedStyle.outlineStyle,
      outlineWidth: selectedStyle.outlineWidth,
      swatches: [...control.querySelectorAll<HTMLElement>(".appearanceThemeSwatch")].map((swatch) => getComputedStyle(swatch).display),
      selectedTheme: document.documentElement.dataset.wikiTheme,
      selectedDensity: document.documentElement.dataset.wikiDensity
    };
  });
  expect(forcedEvidence.forcedColorAdjust).toBe("auto");
  expect(forcedEvidence.outlineStyle).not.toBe("none");
  expect(Number.parseFloat(forcedEvidence.outlineWidth)).toBeGreaterThanOrEqual(2);
  expect(forcedEvidence.swatches).toEqual(["none", "none"]);
  expect(forcedEvidence.selectedTheme).toBe("luminous-observatory");
  expect(forcedEvidence.selectedDensity).toBe("command");
  expectAppearanceGeometry(await appearanceGeometry(page), "forced colors");
  await attachGeometry(testInfo, "appearance-forced-colors", forcedEvidence);
  await attachViewportScreenshot(page, testInfo, "appearance-forced-colors");
});

test("reduced motion removes appearance animation while preserving the semantic route", async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await prepareAppearance(page, { viewport: { width: 1280, height: 900 } });
  expect(await page.evaluate(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(true);
  const routeBefore = page.url();
  await chooseAppearance(page, "luminous-observatory", "focus");
  await page.waitForTimeout(20);
  const motionEvidence = await page.locator(".appearanceControl").evaluate((control) => {
    const seconds = (value: string) => value.split(",").map((part) => {
      const duration = part.trim();
      return duration.endsWith("ms") ? Number.parseFloat(duration) / 1_000 : Number.parseFloat(duration);
    });
    const rows = [...control.querySelectorAll<HTMLElement>("summary, button, .appearanceControlMenu")].map((element) => {
      const style = getComputedStyle(element);
      return {
        tag: element.tagName,
        animationName: style.animationName,
        animationSeconds: seconds(style.animationDuration),
        transitionSeconds: seconds(style.transitionDuration)
      };
    });
    return {
      rows,
      activeAnimationDurationsMs: control.getAnimations({ subtree: true })
        .filter((animation) => animation.playState === "running")
        .map((animation) => {
          const duration = animation.effect?.getTiming().duration;
          return typeof duration === "number" ? duration : 0;
        })
    };
  });
  for (const duration of motionEvidence.activeAnimationDurationsMs) expect(duration).toBeLessThanOrEqual(0.02);
  for (const row of motionEvidence.rows) {
    expect(row.animationName).toBe("none");
    expect(Math.max(...row.animationSeconds)).toBeLessThanOrEqual(0.000_01);
    expect(Math.max(...row.transitionSeconds)).toBeLessThanOrEqual(0.000_01);
  }
  expect(page.url()).toBe(routeBefore);
  expectAppearanceGeometry(await appearanceGeometry(page), "reduced motion");
  await attachGeometry(testInfo, "appearance-reduced-motion", motionEvidence);
  await attachViewportScreenshot(page, testInfo, "appearance-reduced-motion");
});

test("appearance is operable by Tab, Shift+Tab, Enter and Space with visible focus", async ({ page }, testInfo) => {
  await prepareAppearance(page, { viewport: { width: 1280, height: 900 } });
  const routeBefore = page.url();
  // WorldView intentionally owns focus after route hydration. Move backward
  // once through the real keyboard order to reach the preceding top-bar
  // setting, rather than resetting focus with a pointer action.
  await page.locator(".worldWorkspace").focus();
  await page.keyboard.press("Shift+Tab");
  const summary = page.locator(".appearanceControl > summary");
  await expect.poll(() => summary.evaluate((element) => document.activeElement === element)).toBe(true);
  expect(await summary.evaluate((element) => getComputedStyle(element).boxShadow)).not.toBe("none");
  await page.keyboard.press("Enter");
  await expect(page.locator(".appearanceControl")).toHaveAttribute("open", "");

  await page.keyboard.press("Tab");
  const firstTheme = themeButton(page, "luminous-observatory");
  await expect.poll(() => firstTheme.evaluate((element) => document.activeElement === element)).toBe(true);
  expect(await firstTheme.evaluate((element) => getComputedStyle(element).boxShadow)).not.toBe("none");
  await page.keyboard.press("Space");
  await expect(firstTheme).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  const firstDensity = densityButton(page, "focus");
  await expect.poll(() => firstDensity.evaluate((element) => document.activeElement === element)).toBe(true);
  await page.keyboard.press("Space");
  await expect(firstDensity).toHaveAttribute("aria-pressed", "true");
  expect(page.url()).toBe(routeBefore);

  await attachViewportScreenshot(page, testInfo, "appearance-keyboard-focus");
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Shift+Tab");
  await expect.poll(() => summary.evaluate((element) => document.activeElement === element)).toBe(true);
  await page.keyboard.press("Enter");
  await expect(page.locator(".appearanceControl")).not.toHaveAttribute("open", "");
  await expect.poll(() => summary.evaluate((element) => document.activeElement === element)).toBe(true);
});

test("mobile appearance keeps both themes, all densities and 44px controls inside the viewport", async ({ page }, testInfo) => {
  await prepareAppearance(page, { viewport: { width: 390, height: 844 } });
  const routeBefore = page.url();
  await rememberWorldSurface(page);
  await openAppearance(page);

  for (const theme of THEMES) {
    await themeButton(page, theme.id).click();
    await expect(page.locator("html")).toHaveAttribute("data-wiki-theme", theme.id);
  }
  for (const density of DENSITIES) {
    await densityButton(page, density).click();
    await expect(page.locator("html")).toHaveAttribute("data-wiki-density", density);
  }

  expect(page.url()).toBe(routeBefore);
  await expectRememberedWorldSurface(page);
  const geometry = await appearanceGeometry(page);
  expectAppearanceGeometry(geometry, "mobile appearance");
  expect(geometry.viewport).toEqual({ width: 390, height: 844, dpr: 1 });
  await attachGeometry(testInfo, "appearance-mobile", geometry);
  await attachViewportScreenshot(page, testInfo, "appearance-mobile");
});
