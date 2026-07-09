import { expect, test } from "./fixtures";

test("non-demo cockpit blocks missing operator instead of rendering sample data", async ({ page }) => {
  await page.goto("/w/radar");
  const alert = page.getByRole("alert");
  await expect(alert).toBeVisible({ timeout: 10000 });
  await expect(alert).toContainText("Real snapshot required");
  await expect(alert).toContainText(/sample fallback is blocked outside \/demo/i);
  await expect(page.locator("canvas")).toHaveCount(0);
});

test("demo cockpit can still render the bundled sample universe", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.goto("/demo/w/radar");
  await expect(page.locator(".demoBanner")).toContainText("synthetic sample data", { timeout: 10000 });
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20000 });
});

test("configured operator snapshot endpoint serves the expected real repo", async ({ request }) => {
  const url = process.env.WIKI_COCKPIT_SNAPSHOT_URL;
  const expectedRepo = process.env.WIKI_COCKPIT_EXPECT_REPO_ID;
  const minPages = Number(process.env.WIKI_COCKPIT_MIN_PAGES || "1");
  test.skip(!url || !expectedRepo, "set WIKI_COCKPIT_SNAPSHOT_URL and WIKI_COCKPIT_EXPECT_REPO_ID for downstream validation");

  const response = await request.get(url!, { headers: { accept: "application/json" } });
  expect(response.headers()["content-type"] || "").toContain("application/json");
  expect(response.ok()).toBe(true);
  const payload = await response.json();
  expect(payload.repo_id || payload.repo?.repo_id).toBe(expectedRepo);
  expect(Array.isArray(payload.pages) ? payload.pages.length : 0).toBeGreaterThanOrEqual(minPages);
});

test("configured real cockpit UI renders the expected repo instead of sample", async ({ page }) => {
  const baseUrl = process.env.WIKI_COCKPIT_REAL_BASE_URL;
  const expectedRepo = process.env.WIKI_COCKPIT_EXPECT_REPO_ID;
  const minPages = Number(process.env.WIKI_COCKPIT_MIN_PAGES || "1");
  test.skip(!baseUrl || !expectedRepo, "set WIKI_COCKPIT_REAL_BASE_URL and WIKI_COCKPIT_EXPECT_REPO_ID for downstream UI validation");

  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.goto(`${baseUrl!.replace(/\/+$/, "")}/w/quadrants`);
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.locator(".topBar")).toContainText(expectedRepo!, { timeout: 20000 });
  await expect(page.locator(".topBar")).toContainText("local operator");
  await expect(page.locator(".demoBanner")).toHaveCount(0);
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20000 });
  await expect(page.locator("canvas")).toHaveCount(1, { timeout: 20000 });
  await expect(page.locator(".worldMeta")).toContainText(new RegExp(`${minPages}\\s+pages|${minPages}\\s+páginas`));
});
