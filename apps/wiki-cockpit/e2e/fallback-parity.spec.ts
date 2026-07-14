import type { Page } from "@playwright/test";
import { attachViewportScreenshot, expect, test } from "./fixtures";
import { expectOverlayEncodingMatrix } from "./overlay-assertions";

async function openSearchResult(page: Page, title: string) {
  const input = page.locator(".commandSearch input");
  await input.fill(title);
  await input.press("Enter");
  await expect(page.locator(".pageReader")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".readerHead h2")).toHaveText(title);
  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/);
  await expect(page.locator(".quadrantCompass")).toBeHidden();
  await expect(page.locator(".worldNavigator")).toBeHidden();
  await page.locator(".pageReader").evaluate(async (reader) => {
    const finite = reader
      .getAnimations({ subtree: true })
      .filter((animation) => animation.effect?.getTiming().iterations !== Infinity);
    await Promise.all(finite.map((animation) => animation.finished.catch(() => undefined)));
  });
  const readerGeometry = await page.locator(".pageReader").evaluate((reader) => {
    const rect = reader.getBoundingClientRect();
    return {
      left: rect.left,
      right: rect.right,
      viewportWidth: window.innerWidth,
      documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth
    };
  });
  expect(readerGeometry.left).toBeGreaterThanOrEqual(-1);
  expect(readerGeometry.right).toBeLessThanOrEqual(readerGeometry.viewportWidth + 1);
  expect(readerGeometry.documentOverflow).toBeLessThanOrEqual(1);
  await page.locator(".pageReader .readerClose").last().click();
  await expect(page.locator(".pageReader")).toHaveCount(0);
}

test("forced fallback preserves route, first viewport and source/action/person/reader/dock parity", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.goto("/demo/w?view=quadrants&center=root-alex-rivera&lens=pratica");

  expect(await page.evaluate(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(true);
  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator("canvas")).toHaveCount(0);
  await expect(page).not.toHaveURL(/[?&]visual=1/);
  const workspace = page.locator(".worldWorkspace");
  await expect(workspace).toHaveAttribute("data-runtime-mode", "v8");
  await expect(workspace).toHaveAttribute("data-world-center", "root-alex-rivera");
  await expect(workspace).toHaveAttribute("data-world-lens", /pratica|q2_pratica/);
  await expect(page.locator(".fallbackCore")).toBeInViewport();
  await expect(page.locator(".fallbackGroupLink:not(.emptyFacet)").first()).toBeVisible();
  const scrollContract = await page.locator(".sceneShell").evaluate((shell) => {
    const fallback = shell.querySelector<HTMLElement>(".sceneFallback");
    const verticalScrollports = [shell, fallback].filter((element) => {
      if (!element) return false;
      const overflowY = getComputedStyle(element).overflowY;
      return ["auto", "scroll"].includes(overflowY) && element.scrollHeight > element.clientHeight + 1;
    }).length;
    return {
      shellOverflowX: getComputedStyle(shell).overflowX,
      fallbackOverflowY: fallback ? getComputedStyle(fallback).overflowY : "missing",
      verticalScrollports,
      documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth
    };
  });
  expect(scrollContract).toEqual({
    shellOverflowX: "hidden",
    fallbackOverflowY: "visible",
    verticalScrollports: 1,
    documentOverflow: 0
  });

  await openSearchResult(page, "CRM accounts export");
  await openSearchResult(page, "Clean unsourced region claims");
  await openSearchResult(page, "Caio Prado");

  await page.locator(".dockButton").filter({ hasText: /Sources|Fontes/ }).click();
  await expect(page).toHaveURL(/[?&]dock=source/);
  await expect(page.locator(".sourceDock")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/);
  await page.locator(".sourceDock .readerClose").first().click();
  await expect(page).not.toHaveURL(/[?&]dock=/);
  await expect(page.locator(".appDockPresence")).toHaveCount(0);

  const fallbackNode = page.locator(".fallbackNode:not(.groupNode)").first();
  await fallbackNode.scrollIntoViewIfNeeded();
  await expect(fallbackNode).toBeVisible();
  await fallbackNode.click();
  await expect(page).toHaveURL(/reader=1/);
  await expect(page.locator(".pageReader")).toBeVisible({ timeout: 10_000 });
  await attachViewportScreenshot(page, testInfo, "chromium-forced-fallback");
});

test("forced fallback exposes all semantic overlay tokens without moving nodes", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
  });
  await page.goto("/demo/w?view=quadrants&center=root-alex-rivera&overlay=attention");
  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-runtime-mode", "v8");
  const evidence = await expectOverlayEncodingMatrix(page, { fallback: true });
  await testInfo.attach("overlay-encoding-fallback.json", {
    body: Buffer.from(`${JSON.stringify(evidence, null, 2)}\n`, "utf8"),
    contentType: "application/json"
  });
  await attachViewportScreenshot(page, testInfo, "chromium-fallback-overlay-quality");
});
