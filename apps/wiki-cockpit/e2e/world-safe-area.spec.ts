import { expect, test } from "./fixtures";

type Rect = {
  bottom: number;
  height: number;
  label: string;
  left: number;
  right: number;
  selector: string;
  top: number;
  width: number;
};

type Violation = {
  label: string;
  reason: string;
  rect: Rect;
};

type OverlapViolation = {
  a: string;
  b: string;
  area: number;
  ratio: number;
};

type ClipViolation = {
  clientHeight: number;
  clientWidth: number;
  scrollHeight: number;
  scrollWidth: number;
  text: string;
};

const IN_WORLD_LABEL_SELECTORS = [
  ".sceneHtmlLabel",
  ".sceneHtmlLabel button",
  ".sceneHtmlLabel .nodeLabelBody",
  ".radarLabel",
  ".radarRimPill",
  ".horizonBeacon",
  ".questMarkerWrap",
  ".parentDrillGateLabel",
  ".sceneClusterLabel"
] as const;

test("3D quadrant drill keeps diegetic labels legible and out of fixed HUD safe areas", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
  });
  await page.goto("/demo/w/quadrants/~/region%3Apratica%3Afamily%3Asource?center=company-clearpath-labs");
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20000 });
  await expect(page.locator("canvas")).toHaveCount(1, { timeout: 20000 });
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-runtime-mode", "compat");
  await page.waitForTimeout(1600);

  const result = await page.evaluate((selectors) => {
    const viewport = { width: window.innerWidth, height: window.innerHeight };
    const commandBar = document.querySelector(".worldCommandBar")?.getBoundingClientRect();
    const minimap = document.querySelector(".worldMinimap:not(.expanded)")?.getBoundingClientRect();
    const topStrip = document.querySelector(".worldTopStrip")?.getBoundingClientRect();
    const toRect = (element: Element, selector: string): Rect => {
      const rect = element.getBoundingClientRect();
      const label =
        element.getAttribute("aria-label") ||
        element.getAttribute("title") ||
        element.textContent?.replace(/\s+/g, " ").trim() ||
        selector;
      return {
        bottom: rect.bottom,
        height: rect.height,
        label,
        left: rect.left,
        right: rect.right,
        selector,
        top: rect.top,
        width: rect.width
      };
    };
    const visible = (rect: Rect) =>
      rect.width > 2 &&
      rect.height > 2 &&
      rect.right > 0 &&
      rect.bottom > 0 &&
      rect.left < viewport.width &&
      rect.top < viewport.height;
    const intersects = (
      a: Rect,
      b: Pick<DOMRect, "bottom" | "left" | "right" | "top">,
      pad: number
    ) => !(a.right + pad < b.left || a.left - pad > b.right || a.bottom + pad < b.top || a.top - pad > b.bottom);
    const seen = new Set<string>();
    const rects = selectors.flatMap((selector) =>
      Array.from(document.querySelectorAll(selector)).map((element) => toRect(element, selector))
    ).filter((rect) => {
      const key = `${Math.round(rect.left)}:${Math.round(rect.top)}:${Math.round(rect.width)}:${Math.round(rect.height)}:${rect.label}`;
      if (seen.has(key) || !visible(rect)) return false;
      seen.add(key);
      return true;
    });
    const violations: Violation[] = [];
    for (const rect of rects) {
      if (commandBar && rect.bottom > commandBar.top - 10) {
        violations.push({ label: rect.label, reason: "command bar safe area", rect });
      }
      if (topStrip && rect.top < topStrip.bottom + 8) {
        violations.push({ label: rect.label, reason: "top strip safe area", rect });
      }
      if (minimap && intersects(rect, minimap, 8)) {
        violations.push({ label: rect.label, reason: "minimap safe area", rect });
      }
    }
    const labelRoots = Array.from(document.querySelectorAll(".sceneHtmlLabel"))
      .map((element) => toRect(element, ".sceneHtmlLabel"))
      .filter((rect) => visible(rect) && rect.width > 8 && rect.height > 8);
    const overlapViolations: OverlapViolation[] = [];
    const overlapArea = (a: Rect, b: Rect) => {
      const x = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
      const y = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
      return x * y;
    };
    for (let i = 0; i < labelRoots.length; i += 1) {
      for (let j = i + 1; j < labelRoots.length; j += 1) {
        const a = labelRoots[i];
        const b = labelRoots[j];
        const area = overlapArea(a, b);
        if (area <= 120) continue;
        const minArea = Math.max(1, Math.min(a.width * a.height, b.width * b.height));
        const ratio = area / minArea;
        if (ratio > 0.42) {
          overlapViolations.push({ a: a.label, b: b.label, area: Math.round(area), ratio: Number(ratio.toFixed(3)) });
        }
      }
    }
    const clippedGroupTitles: ClipViolation[] = Array.from(document.querySelectorAll<HTMLElement>(".nodeGroupLabel strong"))
      .filter((element) => {
        const style = window.getComputedStyle(element);
        if (style.overflow === "visible") return false;
        return element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1;
      })
      .map((element) => ({
        text: element.textContent?.replace(/\s+/g, " ").trim() || "",
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
        clientHeight: element.clientHeight,
        scrollHeight: element.scrollHeight
      }));
    return {
      labelCount: rects.length,
      clippedGroupTitles,
      overlapViolations,
      violations
    };
  }, IN_WORLD_LABEL_SELECTORS);

  expect(result.labelCount).toBeGreaterThan(0);
  expect(result.violations).toEqual([]);
  expect(result.overlapViolations).toEqual([]);
  expect(result.clippedGroupTitles).toEqual([]);
});
