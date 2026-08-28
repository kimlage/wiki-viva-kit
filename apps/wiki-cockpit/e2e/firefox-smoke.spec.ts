import { attachViewportScreenshot, expect, test } from "./fixtures";

test("Firefox keeps center, source reader and Back/Forward semantics across 3D or automatic fallback", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.goto("/demo/w?view=quadrants&center=root-alex-rivera");
  const scene = page.locator(".sceneShell");
  await expect(scene).toBeVisible({ timeout: 20_000 });
  const startedInFallback = await scene.evaluate((element) => element.classList.contains("fallbackMode"));
  await expect(page.locator("canvas")).toHaveCount(startedInFallback ? 0 : 1, { timeout: 20_000 });
  if (startedInFallback) {
    const performanceOutput = page.getByTestId("runtime-performance");
    await expect(performanceOutput).toHaveAttribute("data-performance-ready", "true", { timeout: 10_000 });
    const fallbackEvidence = await performanceOutput.evaluate((output: HTMLOutputElement) => {
      const raw = output.value || output.textContent || "";
      return raw ? JSON.parse(raw) as { counters?: { fallbackReason?: string | null } } : null;
    });
    expect(fallbackEvidence?.counters?.fallbackReason).toBe("webgl_unavailable");
  }
  const workspace = page.locator(".worldWorkspace");
  await expect(workspace).toHaveAttribute("data-runtime-mode", "v8");
  await expect(workspace).toHaveAttribute("data-world-center", "root-alex-rivera");

  await page.goto("/demo/w?view=quadrants&center=company-clearpath-labs");
  await expect(workspace).toHaveAttribute("data-runtime-mode", "v8");
  await expect(workspace).toHaveAttribute("data-world-center", "company-clearpath-labs");

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
  await expect(scene).toHaveClass(/fallbackMode/, { timeout: 10_000 });
  await expect(page.locator("canvas")).toHaveCount(0);
  await expect(page).not.toHaveURL(/[?&]visual=1/);
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-center", "company-clearpath-labs");
  await attachViewportScreenshot(page, testInfo, "firefox-history-fallback");
});
