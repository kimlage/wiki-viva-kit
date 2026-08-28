import type { Page } from "@playwright/test";
import { expect } from "./fixtures";

export const OVERLAY_IDS = ["attention", "freshness", "actions", "ownership", "evidence", "quality"] as const;

export async function expectCollapsedFilterClearance(page: Page) {
  const collapsed = page.locator(".radarStatusStrip.collapsed .stripToggle");
  await expect(collapsed).toBeVisible();
  const geometry = await collapsed.evaluate((toggle) => {
    const commandBar = document.querySelector<HTMLElement>(".worldCommandBar");
    const commandSearch = document.querySelector<HTMLElement>(".commandSearch");
    const toggleRect = toggle.getBoundingClientRect();
    const commandBarRect = commandBar?.getBoundingClientRect();
    const commandSearchRect = commandSearch?.getBoundingClientRect();
    const centerTarget = document.elementFromPoint(
      toggleRect.left + toggleRect.width / 2,
      toggleRect.top + toggleRect.height / 2
    );
    return {
      clearanceToBar: commandBarRect ? commandBarRect.top - toggleRect.bottom : null,
      clearanceToSearch: commandSearchRect ? commandSearchRect.top - toggleRect.bottom : null,
      ownsCenterTarget: Boolean(centerTarget && (centerTarget === toggle || toggle.contains(centerTarget)))
    };
  });
  expect(geometry.clearanceToBar, "collapsed filter must stay clear of the command bar").not.toBeNull();
  expect(geometry.clearanceToBar!).toBeGreaterThanOrEqual(4);
  expect(geometry.clearanceToSearch, "collapsed filter must stay clear of command search").not.toBeNull();
  expect(geometry.clearanceToSearch!).toBeGreaterThanOrEqual(4);
  expect(geometry.ownsCenterTarget, "collapsed filter center must remain pointer-reachable").toBe(true);
  return geometry;
}

async function openRichLegend(page: Page) {
  if (await page.getByTestId("overlay-legend").count()) return;
  const collapsed = page.locator(".radarStatusStrip.collapsed .stripToggle");
  if (await collapsed.count()) {
    await expectCollapsedFilterClearance(page);
    await collapsed.click();
  }
  await page.locator(".radarStatusStrip .keyChip").click();
  await expect(page.getByTestId("overlay-legend")).toBeVisible();
}

export async function expectOverlayEncodingMatrix(page: Page, options: { fallback: boolean }) {
  const scene = page.locator(".sceneShell");
  const workspace = page.locator(".worldWorkspace");
  const overlaySelect = page.locator(".worldRuntimeSelect select").last();
  await expect(scene).toHaveAttribute("data-overlay-token-version", "wiki_semantic_visual_tokens.v1");
  const strongAttentionCount = Number(await scene.getAttribute("data-strong-attention-count"));
  expect(strongAttentionCount).toBeGreaterThanOrEqual(0);
  expect(strongAttentionCount).toBeLessThanOrEqual(12);
  const originalSignature = await scene.getAttribute("data-layout-position-signature");
  expect(originalSignature?.length ?? 0).toBeGreaterThan(10);
  if (!options.fallback) await openRichLegend(page);

  const observedColors = new Set<string>();
  for (const overlay of OVERLAY_IDS) {
    await overlaySelect.selectOption(overlay);
    await expect(workspace).toHaveAttribute("data-world-overlay", overlay);
    await expect(scene).toHaveAttribute("data-scene-overlay", overlay);
    await expect(scene).toHaveAttribute("data-layout-position-signature", originalSignature!);

    const legend = page.getByTestId("overlay-legend");
    await expect(legend).toHaveAttribute("data-overlay", overlay);
    await expect(legend).toHaveAttribute("data-overlay-token-version", "wiki_semantic_visual_tokens.v1");
    const legendEntries = legend.locator("[data-overlay-state]");
    expect(await legendEntries.count(), `${overlay} legend states`).toBeGreaterThanOrEqual(3);
    expect((await legendEntries.allTextContents()).every((text) => text.trim().length > 1)).toBe(true);

    const encodedNode = options.fallback
      ? page.locator(`.fallbackNode[data-overlay="${overlay}"]`).first()
      : page.locator(`.nodeOverlaySignal[data-overlay="${overlay}"]`).first();
    await expect(encodedNode).toBeAttached();
    const color = await encodedNode.evaluate((element) =>
      getComputedStyle(element).getPropertyValue("--overlay-color").trim() || getComputedStyle(element).borderColor
    );
    expect(color.length).toBeGreaterThan(0);
    observedColors.add(color);
  }
  expect(observedColors.size, "active overlays should produce distinct body/label tokens").toBeGreaterThanOrEqual(4);
  return { layoutPositionSignature: originalSignature, observedColors: [...observedColors] };
}
