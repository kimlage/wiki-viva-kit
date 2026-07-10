import type { Page } from "@playwright/test";
import { inflateSync } from "node:zlib";
import { expect, test } from "./fixtures";
import { expectSpatialCardsWithinSafeArea } from "./spatial-assertions";

// This suite proves persistent-canvas interaction. Recording every frame can
// itself push the bounded runtime below the product budget and correctly swap
// to the safe 2D map, which would test a different contract. Dedicated
// performance and fallback specs cover that branch with explicit evidence.
test.use({ trace: "off", video: "off" });

test.describe.configure({ timeout: 60000 });

async function prepareWorld(page: Page, path = "/demo/w/quadrants") {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
    window.localStorage.removeItem("wikiCockpitVisualControl.v1");
    window.localStorage.removeItem("wikiCockpitVisualControl.v2");
  });
  await page.goto(path);
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20000 });
  await expect(page.locator("canvas")).toHaveCount(1, { timeout: 20000 });
  await expect(page.locator(".worldCommandBar")).toBeVisible({ timeout: 20000 });
  await page.waitForTimeout(900);
  await expectWorldCanvasHasSignal(page);
  await expectCompactControlsFit(page);
}

async function expectSingleWorld(page: Page) {
  await expect(page.locator("canvas")).toHaveCount(1);
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/);
  await expect(page.locator(".sceneCanvasFrame")).toBeVisible();
  await expect(page.locator(".worldCommandBar")).toBeVisible();
}

async function expectWorldCanvasHasSignal(page: Page) {
  const screenshot = await page.locator("canvas").screenshot({ animations: "disabled" });
  expect(pngLitPixelCount(screenshot)).toBeGreaterThan(18);
}

async function expectCompactControlsFit(page: Page) {
  const selectors = [
    ".worldCommandBar .dockButton small",
    ".worldCommandBar .glyphButton small",
    ".worldCommandBar .workButton span",
    ".worldCommandBar .missionsButton span",
    ".worldCommandBar .missionsButton .dockBadge",
    ".dockTelemetryTop small",
    ".dockTelemetryTop strong"
  ];
  const offenders = await page.evaluate((compactSelectors) => {
    const seen = new Set<Element>();
    return compactSelectors.flatMap((selector) => Array.from(document.querySelectorAll<HTMLElement>(selector))
      .filter((element) => {
        if (seen.has(element)) return false;
        seen.add(element);
        const style = getComputedStyle(element);
        if (style.display === "none" || style.visibility === "hidden") return false;
        const rect = element.getBoundingClientRect();
        if (rect.width <= 1 || rect.height <= 1) return false;
        const horizontalOverflow = element.scrollWidth > element.clientWidth + 1;
        const verticalOverflow = element.scrollHeight > element.clientHeight + 1;
        return horizontalOverflow || verticalOverflow;
      })
      .map((element) => ({
        selector,
        text: (element.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 80),
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
        clientHeight: element.clientHeight,
        scrollHeight: element.scrollHeight
      })));
  }, selectors);
  expect(offenders).toEqual([]);
}

async function expectCanonicalWilberGrid(page: Page) {
  const compass = page.locator(".quadrantCompass");
  await expect(compass).toBeVisible();
  await expect(compass.locator(".quadrantGrid")).toHaveCount(1);
  await expect(compass.locator(".quadrantTextGrid")).toHaveCount(1);
  await expect(compass.locator("button[data-wilber-quadrant]")).toHaveCount(4);
  await expect(compass.locator(".quadrantTextCell")).toHaveCount(4);
  await expect(compass.locator(".quadrantCell")).toHaveCount(0);
  await expect(compass.locator(".quadrantHealthRing")).toHaveCount(0);
  await expect(page.locator(".quadrantAreaNav")).toHaveCount(0);
  const contract = await compass.locator(".quadrantGrid").evaluate((grid) => {
    const columns = getComputedStyle(grid).gridTemplateColumns.split(" ").filter(Boolean);
    return {
      columns: columns.length,
      labels: Array.from(grid.querySelectorAll<HTMLElement>(".quadrantTextCell")).map((cell) => ({
        quadrant: cell.dataset.wilberQuadrant ?? "",
        text: (cell.textContent ?? "").trim().replace(/\s+/g, " ")
      }))
    };
  });
  expect(contract.columns).toBe(2);
  expect(contract.labels.map((item) => item.quadrant)).toEqual(["1", "2", "3", "4"]);
  expect(contract.labels.map((item) => item.text)).toEqual([
    expect.stringContaining("Q1 · I"),
    expect.stringContaining("Q2 · It"),
    expect.stringContaining("Q3 · We"),
    expect.stringContaining("Q4 · Its")
  ]);
  expect(contract.labels.map((item) => item.text)).toEqual([
    expect.stringContaining("interior individual"),
    expect.stringContaining("exterior individual"),
    expect.stringMatching(/interior (collective|coletivo)/),
    expect.stringMatching(/exterior (collective|coletivo)/)
  ]);
}

async function expectInteractiveCardsDoNotOverlap(page: Page, selector: string) {
  const overlaps = await page.evaluate((cardSelector) => {
    const cards = Array.from(document.querySelectorAll<HTMLElement>(cardSelector))
      .filter((element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 1 && rect.height > 1;
      })
      .map((element, index) => {
        const rect = element.getBoundingClientRect();
        return {
          index,
          text: (element.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 80),
          left: rect.left,
          right: rect.right,
          top: rect.top,
          bottom: rect.bottom
        };
      });
    const result: { a: string; b: string; area: number }[] = [];
    for (let first = 0; first < cards.length; first += 1) {
      for (let second = first + 1; second < cards.length; second += 1) {
        const a = cards[first];
        const b = cards[second];
        if (!a || !b) continue;
        const width = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
        const height = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
        const area = width * height;
        if (area > 24) result.push({ a: a.text, b: b.text, area: Math.round(area) });
      }
    }
    return result;
  }, selector);
  expect(overlaps).toEqual([]);
}

function pngLitPixelCount(buffer: Buffer): number {
  const chunks: Buffer[] = [];
  let width = 0;
  let height = 0;
  let bitDepth = 0;
  let colorType = 0;
  let offset = 8;
  while (offset < buffer.length) {
    const length = buffer.readUInt32BE(offset);
    const type = buffer.toString("ascii", offset + 4, offset + 8);
    const data = buffer.subarray(offset + 8, offset + 8 + length);
    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      bitDepth = data[8] ?? 0;
      colorType = data[9] ?? 0;
    } else if (type === "IDAT") {
      chunks.push(data);
    } else if (type === "IEND") {
      break;
    }
    offset += length + 12;
  }
  if (bitDepth !== 8 || width <= 0 || height <= 0 || chunks.length === 0) return 0;
  const channels = colorType === 6 ? 4 : colorType === 2 ? 3 : 0;
  if (channels === 0) return 0;
  const rowLength = width * channels;
  const inflated = inflateSync(Buffer.concat(chunks));
  const rows = new Uint8Array(height * rowLength);
  let sourceOffset = 0;
  for (let y = 0; y < height; y += 1) {
    const filter = inflated[sourceOffset] ?? 0;
    sourceOffset += 1;
    const rowStart = y * rowLength;
    for (let x = 0; x < rowLength; x += 1) {
      const raw = inflated[sourceOffset + x] ?? 0;
      const left = x >= channels ? rows[rowStart + x - channels] ?? 0 : 0;
      const up = y > 0 ? rows[rowStart + x - rowLength] ?? 0 : 0;
      const upLeft = y > 0 && x >= channels ? rows[rowStart + x - rowLength - channels] ?? 0 : 0;
      const predictor =
        filter === 1 ? left :
        filter === 2 ? up :
        filter === 3 ? Math.floor((left + up) / 2) :
        filter === 4 ? paeth(left, up, upLeft) :
        0;
      rows[rowStart + x] = (raw + predictor) & 255;
    }
    sourceOffset += rowLength;
  }
  let lit = 0;
  const stride = Math.max(channels, channels * Math.floor(width / 48));
  for (let index = 0; index < rows.length; index += stride) {
    const alpha = channels === 4 ? rows[index + 3] ?? 0 : 255;
    const energy = (rows[index] ?? 0) + (rows[index + 1] ?? 0) + (rows[index + 2] ?? 0);
    if (alpha > 0 && energy > 18) lit += 1;
  }
  return lit;
}

function paeth(left: number, up: number, upLeft: number): number {
  const p = left + up - upLeft;
  const pa = Math.abs(p - left);
  const pb = Math.abs(p - up);
  const pc = Math.abs(p - upLeft);
  if (pa <= pb && pa <= pc) return left;
  if (pb <= pc) return up;
  return upLeft;
}

async function sceneContract(page: Page) {
  return page.locator(".sceneShell").evaluate((shell) => ({
    center: shell.getAttribute("data-scene-center") ?? "",
    group: shell.getAttribute("data-scene-group") ?? "",
    level: shell.getAttribute("data-scene-level") ?? "",
    perspective: shell.getAttribute("data-scene-perspective") ?? "",
    quadrant: shell.getAttribute("data-scene-quadrant") ?? "",
    centerHasQuadrants: shell.getAttribute("data-scene-center-has-quadrants") ?? ""
  }));
}

async function closeSurface(page: Page) {
  await page.keyboard.press("Escape");
  await expect(page).not.toHaveURL(/[?&]dock=/);
  await expect(page.locator(".appDockPresence")).toHaveCount(0);
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-primary-surface-open", "false");
  await expectSingleWorld(page);
}

async function openDock(page: Page, label: string, dock: string, visibleSelector: string) {
  await page.locator(".dockButton", { hasText: label }).first().click();
  await expect(page).toHaveURL(new RegExp(`[?&]dock=${dock}`));
  if (visibleSelector) await expect(page.locator(visibleSelector).first()).toBeVisible({ timeout: 10000 });
  await expectSingleWorld(page);
}

test("desktop cockpit modules keep one 3D world while navigating", async ({ page }) => {
  await prepareWorld(page);

  await page.locator(".glyphButton", { hasText: "Atlas" }).click();
  await expect(page).toHaveURL(/\/demo\/w\/atlas(?:\?|$)/);
  await expectSingleWorld(page);
  await expectWorldCanvasHasSignal(page);

  await page.locator(".glyphButton", { hasText: "Quadrants" }).click();
  await expect(page).toHaveURL(/\/demo\/w\/quadrants(?:\?|$)/);
  await expect(page.locator(".quadrantCompass")).toBeVisible();
  await expectCanonicalWilberGrid(page);
  await expectSingleWorld(page);
  await expectWorldCanvasHasSignal(page);
  await expectCompactControlsFit(page);

  const quadrantUrl = page.url();
  const beforeQuadrantHover = await sceneContract(page);
  expect(beforeQuadrantHover.center).not.toMatch(/^region:/);
  expect(beforeQuadrantHover.centerHasQuadrants).toBe("true");
  await page.locator(".quadrantCompass button").first().hover();
  await page.waitForTimeout(350);
  expect(page.url()).toBe(quadrantUrl);
  expect(await sceneContract(page)).toEqual(beforeQuadrantHover);
  await expect(page).not.toHaveURL(/region%3A|region:/);
  await expectSingleWorld(page);

  await page.locator(".quadrantTextCell").nth(1).hover();
  await page.waitForTimeout(250);
  expect(page.url()).toBe(quadrantUrl);
  expect(await sceneContract(page)).toEqual(beforeQuadrantHover);

  await page.locator(".quadrantTextCell").nth(1).click();
  await expect(page).toHaveURL(/[?&]lens=/);
  await expect(page).not.toHaveURL(/region%3A|region:/);
  const afterQuadrantClick = await sceneContract(page);
  expect(afterQuadrantClick.center).toBe(beforeQuadrantHover.center);
  expect(afterQuadrantClick.center).not.toMatch(/^region:/);
  expect(afterQuadrantClick.perspective).toBe("quadrants");
  expect(afterQuadrantClick.quadrant).not.toBe("");
  await expectCanonicalWilberGrid(page);
  await expectSingleWorld(page);

  const activeLensScene = await sceneContract(page);
  await page.locator(".quadrantTextCell.active").click();
  // The selected cell is also the compact, discoverable way back to the whole
  // world. It clears only the lens; center, view and mounted canvas stay put.
  await expect(page).toHaveURL(/[?&]lens=all(?:&|$)/);
  expect(await sceneContract(page)).toEqual({ ...activeLensScene, quadrant: "" });
  await expectSingleWorld(page);

  await expect(page.locator(".operationStation")).toHaveCount(0);
  await openDock(page, "Sources", "source", ".sourceDock");
  await expect(page.locator(".sourceDock .dockTelemetry")).toBeVisible();
  await expect(page.locator(".sourceDock .dockTelemetryItem")).toHaveCount(4);
  await expectCompactControlsFit(page);
  // The active surface makes the world underneath inert. Close it explicitly
  // before opening another dock instead of clicking through its backdrop.
  await closeSurface(page);
  await openDock(page, "Health", "gates", ".gatesDock");
  await expect(page.locator(".gatesDock .dockTelemetry")).toBeVisible();
  await expect(page.locator(".gatesDock .dockTelemetryItem")).toHaveCount(4);
  await expectCompactControlsFit(page);
  await closeSurface(page);
  await openDock(page, "Approve", "approve", ".gateDock");
  await expect(page.locator(".gateDock > .dockTelemetry")).toBeVisible();
  await expect(page.locator(".gateDock > .dockTelemetry .dockTelemetryItem")).toHaveCount(4);
  await expectCompactControlsFit(page);
  await closeSurface(page);

  await page.locator(".workButton").click();
  await expect(page).toHaveURL(/[?&]dock=work/);
  await expect(page.locator(".workDockPanel")).toBeVisible({ timeout: 10000 });
  await expect(page.locator(".workDockPanel .dockTelemetry")).toBeVisible();
  await expect(page.locator(".workDockPanel .dockTelemetryItem")).toHaveCount(4);
  await expectSingleWorld(page);
  await expectCompactControlsFit(page);
  await closeSurface(page);

  await page.locator(".missionsButton").click();
  await expect(page.locator(".missionsPanel")).toBeVisible({ timeout: 10000 });
  await expect(page.locator(".missionsPanel .dockTelemetry")).toBeVisible();
  await expect(page.locator(".missionsPanel .dockTelemetryItem")).toHaveCount(4);
  await expectSingleWorld(page);
  await expectCompactControlsFit(page);
  await page.keyboard.press("Escape");

  await openDock(page, "Blocks", "blocks", ".blocksDock");
  await expect(page.locator(".blocksDock .dockTelemetry")).toBeVisible();
  await expect(page.locator(".blocksDock .dockTelemetryItem")).toHaveCount(4);
  await expectCompactControlsFit(page);
  await closeSurface(page);
  await openDock(page, "Add", "intake", ".intakeDock");
  await expect(page.locator(".intakeDock .dockTelemetry")).toBeVisible();
  await expect(page.locator(".intakeDock .dockTelemetryItem")).toHaveCount(4);
  await expectCompactControlsFit(page);
  await closeSurface(page);

  await page.locator(".dockButton", { hasText: "Create" }).first().click();
  await expect(page).toHaveURL(/[?&]dock=create/);
  await expectSingleWorld(page);
  await page.waitForTimeout(500);
  await expectSpatialCardsWithinSafeArea(page, { expectedPrimary: 7, expectedTotal: 8 });
  const createUrl = page.url();
  const createScene = await sceneContract(page);
  await page.locator(".spatialCardType").first().hover();
  await page.waitForTimeout(250);
  expect(page.url()).toBe(createUrl);
  expect(await sceneContract(page)).toEqual(createScene);
  await closeSurface(page);

  await page.locator(".commandSearch input").fill("Alex Rivera");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/reader=1/, { timeout: 10000 });
  await expect(page.locator(".pageReader")).toBeVisible({ timeout: 10000 });
  await expectSingleWorld(page);
  await expectCompactControlsFit(page);
});

test("visual control easter egg is local configuration, not world navigation", async ({ page }) => {
  await prepareWorld(page);

  await page.locator(".commandSearch input").fill("/god_mode");
  await page.keyboard.press("Enter");

  await expect(page.locator(".visualControlPanel")).toBeVisible({ timeout: 10000 });
  await expect(page).not.toHaveURL(/god_mode|abrachaindabra/);
  await expectSingleWorld(page);
  const visualJson = page.getByRole("textbox", { name: "Visual config JSON" });
  const visualDefaultSnippet = page.getByRole("textbox", { name: "Default visual config snippet" });
  await expect(visualJson).toContainText("wiki_cockpit_visual_config.v1");
  await expect(visualJson).toContainText("0.1.109");
  await expect(page.locator(".visualControlPresetGrid button")).toHaveCount(4);
  await expect(visualJson).toContainText("DEFAULT_VISUAL_CONTROL_CONFIG");
  await expect(visualDefaultSnippet).toContainText("DEFAULT_VISUAL_CONTROL_CONFIG");
  await expect(visualJson).toContainText("/abrachaindabra");

  await page.locator(".visualControlPresetGrid button", { hasText: "debug dense" }).click();
  await expect(visualJson).toContainText('"labels": "dense"');
  await expect(visualDefaultSnippet).toContainText('"labels": "dense"');

  await visualJson.fill('{"config":{"glow":1.2,"contrast":1.1,"density":0.9,"motion":0.4,"uiScale":1,"glass":0.8,"labels":"quiet","particles":false}}');
  await page.locator(".visualControlActions button", { hasText: "Aplicar JSON" }).click();
  await expect(visualJson).toContainText('"particles": false');
  await expect(visualDefaultSnippet).toContainText('"particles": false');

  await page.locator(".readerClose[title='Close visual controls']").click();
  await page.locator(".commandSearch input").fill("/abrachaindabra");
  await page.keyboard.press("Enter");
  await expect(page.locator(".visualControlPanel")).toBeVisible({ timeout: 10000 });
  await expect(page).not.toHaveURL(/god_mode|abrachaindabra/);

  await page.locator(".commandSearch input").fill("Alex Rivera");
  await page.keyboard.press("Enter");
  await expect(page.locator(".pageReader")).toBeVisible({ timeout: 10000 });
  await expect(page.locator(".visualControlPanel")).toHaveCount(0);
});

test("hovering real scene objects inspects without navigating the world", async ({ page }) => {
  await prepareWorld(page, "/demo/w/quadrants?center=root-alex-rivera&lens=pratica&group=family%3Asource");

  await expectSingleWorld(page);
  const beforeUrl = page.url();
  const beforeScene = await sceneContract(page);
  expect(beforeScene.center).toBe("root-alex-rivera");
  expect(beforeScene.group).toBe("family:source");

  const diegeticObject = page.locator("button.nodeGroupLabel, .clusterStarLabel button, .radarRimPill button").first();
  await expect(diegeticObject).toBeVisible({ timeout: 10000 });
  await diegeticObject.hover();
  await page.waitForTimeout(350);

  expect(page.url()).toBe(beforeUrl);
  expect(await sceneContract(page)).toEqual(beforeScene);
  await expect(page.locator("canvas")).toHaveCount(1);
  await expect(page.locator(".pageReader")).toHaveCount(0);
  await expect(page).not.toHaveURL(/reader=1|region%3A[^?]*$/);
  await expectSingleWorld(page);
});

test("selecting a page keeps the declared quadrant center and its lenses", async ({ page }) => {
  await prepareWorld(page, "/demo/w/quadrants/system/family%3Aperson/person-caio-prado?center=root-alex-rivera&lens=pratica&group=family%3Aperson");

  await expectSingleWorld(page);
  await expect(page.locator(".sceneShell")).toHaveAttribute("data-scene-perspective", "quadrants");
  await expect(page.locator(".sceneShell")).toHaveAttribute("data-scene-center", "root-alex-rivera");
  await expect(page.locator(".sceneShell")).toHaveAttribute("data-scene-center-has-quadrants", "true");
  await expect(page.locator(".quadrantCompass")).toBeVisible();
  await expect(page.locator(".quadrantScopeChip")).toHaveCount(0);
  await expect(page.locator(".worldBreadcrumbs")).toContainText("Caio Prado");
});

test("real group drill-down keeps the real page centered and demotes conceptual lenses", async ({ page }) => {
  await prepareWorld(page, "/demo/w/quadrants?center=root-alex-rivera&lens=pratica&group=family%3Asource");

  await expectSingleWorld(page);
  await expect(page.locator(".sceneShell")).toHaveAttribute("data-scene-center", "root-alex-rivera");
  await expect(page.locator(".sceneShell")).toHaveAttribute("data-scene-group", "family:source");
  await expect(page.locator(".sceneShell")).toHaveAttribute("data-scene-center-has-quadrants", "true");
  await expect(page.locator(".quadrantCompass")).toHaveClass(/familyDrillMode/);
  await expectCanonicalWilberGrid(page);
  await expect(page.locator(".quadrantAreaNav")).toHaveCount(0);
  await expect(page.locator(".worldBreadcrumbs")).toContainText("Alex Rivera");
  await expect(page.locator(".worldBreadcrumbs")).toContainText("data sources");
  await expect(page).not.toHaveURL(/region%3A|region:/);
  await expect(page.locator(".nodeGroupLabel").filter({ hasText: /data sources/i })).toHaveCount(0);
  await expect(page.locator("canvas")).toHaveCount(1);
});
