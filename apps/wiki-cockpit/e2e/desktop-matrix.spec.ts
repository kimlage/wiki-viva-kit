import { attachViewportScreenshot, expect, test } from "./fixtures";
import { expectSpatialCardsWithinSafeArea } from "./spatial-assertions";
import { expectCollapsedFilterClearance, expectOverlayEncodingMatrix } from "./overlay-assertions";

const REQUIRED_DESKTOP_VIEWPORTS = [
  { width: 1440, height: 960 },
  { width: 1280, height: 900 },
  // At this width the command bar wraps on both macOS and Linux. Its measured
  // safe area must remain just as pointer-reachable as the single-row bar.
  { width: 1100, height: 900 }
] as const;

test("Chromium desktop covers the required v8 viewports without clipping the world chrome", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });

  for (const viewport of REQUIRED_DESKTOP_VIEWPORTS) {
    await page.setViewportSize(viewport);
    await page.goto("/demo/w?view=quadrants&center=root-alex-rivera");
    await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });
    await expect(page.locator("canvas")).toHaveCount(1, { timeout: 20_000 });
    const workspace = page.locator(".worldWorkspace");
    await expect(workspace).toHaveAttribute("data-runtime-mode", "v8");
    await expect(workspace).toHaveAttribute("data-world-center", "root-alex-rivera");

    const layout = await page.evaluate(() => {
      const visible = (element: HTMLElement) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 1 && rect.height > 1;
      };
      const clipped = [
        ".worldCommandBar button small",
        ".worldBreadcrumbs strong",
        ".worldMeta span",
        ".quadrantTextCell strong",
        ".quadrantTextCell small"
      ].flatMap((selector) => Array.from(document.querySelectorAll<HTMLElement>(selector))
        .filter(visible)
        .filter((element) => element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1)
        .map((element) => ({
          selector,
          text: element.textContent?.trim().replace(/\s+/g, " ").slice(0, 120) ?? "",
          clientWidth: element.clientWidth,
          scrollWidth: element.scrollWidth,
          clientHeight: element.clientHeight,
          scrollHeight: element.scrollHeight
        })));
      const canvas = document.querySelector(".sceneCanvasFrame")?.getBoundingClientRect();
      return {
        clipped,
        documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        canvas: canvas ? { width: canvas.width, height: canvas.height } : null
      };
    });

    expect.soft(layout.documentOverflow, `${viewport.width}x${viewport.height} document overflow`).toBeLessThanOrEqual(1);
    expect.soft(layout.clipped, `${viewport.width}x${viewport.height} clipped labels`).toEqual([]);
    expect.soft(layout.canvas?.width ?? 0, `${viewport.width}x${viewport.height} canvas width`).toBeGreaterThan(640);
    expect.soft(layout.canvas?.height ?? 0, `${viewport.width}x${viewport.height} canvas height`).toBeGreaterThan(480);
    await expectCollapsedFilterClearance(page);
    await attachViewportScreenshot(page, testInfo, `chromium-${viewport.width}x${viewport.height}`);
  }
});

test("Chromium desktop keeps every curated Create card inside the world safe area", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.goto("/demo/w?view=quadrants&center=root-alex-rivera");
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-runtime-mode", "v8");
  await page.locator(".dockButton").filter({ hasText: /Create|Criar/ }).click();
  await expect(page).toHaveURL(/[?&]dock=create/);
  await expect(page.locator(".spatialCardType")).toHaveCount(7, { timeout: 10_000 });
  await expectSpatialCardsWithinSafeArea(page, { expectedPrimary: 7, expectedTotal: 8 });
  await attachViewportScreenshot(page, testInfo, "chromium-create-safe-area");
});

test("Chromium desktop applies all six semantic overlays without relayout", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
  });
  await page.goto("/demo/w?view=quadrants&center=root-alex-rivera&overlay=attention");
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-runtime-mode", "v8");
  const evidence = await expectOverlayEncodingMatrix(page, { fallback: false });
  await testInfo.attach("overlay-encoding-desktop.json", {
    body: Buffer.from(`${JSON.stringify(evidence, null, 2)}\n`, "utf8"),
    contentType: "application/json"
  });
  await attachViewportScreenshot(page, testInfo, "chromium-overlay-quality");
});
