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
  await page.locator(".pageReader .readerClose").last().click();
  await expect(page.locator(".pageReader")).toHaveCount(0);
}

test("forced fallback preserves route, first viewport and source/action/person/reader/dock parity", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.goto("/demo/w/quadrants?center=root-alex-rivera&lens=pratica");

  expect(await page.evaluate(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(true);
  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator("canvas")).toHaveCount(0);
  await expect(page).not.toHaveURL(/[?&]visual=1/);
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", "root-alex-rivera");
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-lens", /pratica|q2_pratica/);
  await expect(page.locator(".fallbackCore")).toBeInViewport();
  await expect(page.locator(".fallbackGroupLink:not(.emptyFacet)").first()).toBeVisible();

  await openSearchResult(page, "CRM accounts export");
  await openSearchResult(page, "Clean unsourced region claims");
  await openSearchResult(page, "Caio Prado");

  await page.locator(".dockButton").filter({ hasText: /Sources|Fontes/ }).click();
  await expect(page).toHaveURL(/[?&]dock=source/);
  await expect(page.locator(".sourceDock")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/);
  await page.locator(".sourceDock .readerClose").first().click();
  await expect(page).not.toHaveURL(/[?&]dock=/);

  await page.locator(".fallbackNode:not(.groupNode)").first().click();
  await expect(page).toHaveURL(/reader=1/);
  await expect(page.locator(".pageReader")).toBeVisible({ timeout: 10_000 });
  await attachViewportScreenshot(page, testInfo, "chromium-forced-fallback");
});

test("forced fallback exposes all semantic overlay tokens without moving nodes", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
  });
  await page.goto("/demo/w/quadrants?center=root-alex-rivera&overlay=attention");
  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/, { timeout: 20_000 });
  const evidence = await expectOverlayEncodingMatrix(page, { fallback: true });
  await testInfo.attach("overlay-encoding-fallback.json", {
    body: Buffer.from(`${JSON.stringify(evidence, null, 2)}\n`, "utf8"),
    contentType: "application/json"
  });
  await attachViewportScreenshot(page, testInfo, "chromium-fallback-overlay-quality");
});
