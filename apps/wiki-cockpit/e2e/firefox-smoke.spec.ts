import { attachViewportScreenshot, expect, test } from "./fixtures";

test("Firefox keeps center, source reader and Back/Forward semantics, then degrades to fallback", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.goto("/demo/w/quadrants?center=root-alex-rivera");
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator("canvas")).toHaveCount(1, { timeout: 20_000 });
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", "root-alex-rivera");

  await page.goto("/demo/w/quadrants?center=company-clearpath-labs");
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", "company-clearpath-labs");

  const input = page.locator(".commandSearch input");
  await input.fill("CRM accounts export");
  await input.press("Enter");
  await expect(page).toHaveURL(/reader=1/);
  await expect(page.locator(".readerHead h2")).toHaveText("CRM accounts export");

  await page.goBack();
  await expect(page).not.toHaveURL(/reader=1/);
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", "company-clearpath-labs");
  await page.goForward();
  await expect(page).toHaveURL(/reader=1/);
  await expect(page.locator(".readerHead h2")).toHaveText("CRM accounts export");

  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/, { timeout: 10_000 });
  await expect(page.locator("canvas")).toHaveCount(0);
  await expect(page).not.toHaveURL(/[?&]visual=1/);
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", "company-clearpath-labs");
  await attachViewportScreenshot(page, testInfo, "firefox-history-fallback");
});
