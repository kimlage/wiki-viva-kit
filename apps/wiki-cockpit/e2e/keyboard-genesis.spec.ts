import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

test.use({ trace: "off", video: "off" });
test.describe.configure({ timeout: 90_000 });

async function prepare(page: Page, path: string) {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.goto(path);
  await expect(page.getByText("Loading cockpit")).toHaveCount(0, { timeout: 20_000 });
}

test("Genesis 0 is a real centerless world and one founding action advances exactly one stage", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await prepare(page, "/demo/genesis");

  const workspace = page.locator(".worldWorkspace");
  await expect(workspace).toHaveAttribute("data-world-empty", "true");
  await expect(workspace).not.toHaveAttribute("data-world-center", /.+/);
  await expect(page.locator(".sceneShell")).toHaveAttribute("data-scene-input-node-count", "0");
  await expect(page.locator(".worldTopStrip, .worldCommandBar, .quadrantCompass, .worldMissionCard, .pageReader")).toHaveCount(0);
  await expect(page.locator(".sceneShell")).not.toContainText("Invalid center");

  const personChoice = page.getByRole("button", { name: /A person|Uma pessoa/i });
  await expect(personChoice).toBeVisible({ timeout: 20_000 });
  await personChoice.click();
  const nameInput = page.locator(".questionPlateBody input, .genesisVoid input");
  await expect(nameInput).toBeVisible();
  await nameInput.fill("Genesis test root");
  await page.getByRole("button", { name: /Found the root|Fundar a raiz/i }).click();

  await expect(page).toHaveURL(/[?&]stage=1(?:&|$)/);
  await expect(workspace).toHaveAttribute("data-world-empty", "false");
  await expect(workspace).toHaveAttribute("data-world-center", "root-alex-rivera");
  expect(pageErrors).toEqual([]);
});

test("native Tab crosses scene, world controls and search, then reader Escape restores its invoker", async ({ page }) => {
  await prepare(page, "/demo/w?center=root-alex-rivera&view=quadrants&lens=all&overlay=actions&tour=0");
  await expect(page.locator(".sceneShell")).toBeVisible({ timeout: 20_000 });
  await expect.poll(() => page.locator("[data-world-target-kind]").evaluateAll((elements) =>
    elements.filter((element) => {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    }).length
  )).toBeGreaterThan(0);
  expect(await page.evaluate(() => document.activeElement === document.body)).toBe(true);

  const visited = new Set<string>();
  const sequence: string[] = [];
  for (let index = 0; index < 140; index += 1) {
    await page.keyboard.press("Tab");
    const active = await page.evaluate(() => {
      const element = document.activeElement as HTMLElement | null;
      if (!element || element === document.body) return "BODY";
      if (element.matches(".commandSearch input")) return "search";
      if (element.closest("[data-world-target-kind]")) return "scene-target";
      if (element.closest(".worldNavigator")) return "navigator";
      if (element.closest(".worldCommandBar")) return "command-bar";
      if (element.closest(".quadrantCompass")) return "quadrant";
      if (element.closest(".worldBreadcrumbs")) return "breadcrumbs";
      return `${element.tagName.toLowerCase()}.${element.className}`;
    });
    sequence.push(active);
    expect(active, `native focus sequence: ${sequence.join(" -> ")}`).not.toBe("BODY");
    visited.add(active);
    if (visited.has("scene-target") && visited.has("navigator") && active === "search") break;
  }

  expect(visited.has("scene-target")).toBe(true);
  expect(visited.has("navigator")).toBe(true);
  expect(visited.has("search")).toBe(true);
  await expect(page.locator(".commandSearch input")).toBeFocused();
  await page.keyboard.type("CRM accounts export");
  await page.keyboard.press("Enter");
  await expect(page.locator(".pageReader")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".pageReader")).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(page.locator(".pageReader")).toHaveCount(0);
  await expect(page.locator(".commandSearch input")).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  expect(await page.evaluate(() => document.activeElement === document.body)).toBe(false);
});
