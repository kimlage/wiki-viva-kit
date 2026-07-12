import type { Page } from "@playwright/test";
import { attachViewportScreenshot, expect, test } from "./fixtures";

test.describe.configure({ timeout: 60_000 });

async function forcePortugueseWiki(page: Page) {
  await page.route("**/sample-snapshot/manifest.json", async (route) => {
    const response = await route.fetch();
    const manifest = await response.json() as { repo: { language: string } };
    manifest.repo.language = "pt-BR";
    await route.fulfill({ response, json: manifest });
  });
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
    window.localStorage.setItem("wikiCockpitVisualControl.v2", JSON.stringify({
      glow: 1,
      contrast: 1,
      density: 1,
      spacing: 1,
      motion: 0,
      uiScale: 1,
      glass: 1,
      labels: "balanced",
      particles: false
    }));
  });
}

async function waitForWorld(page: Page) {
  await expect(page.locator(".worldRouteLoading, .sceneLoading")).toHaveCount(0, {
    timeout: 20_000
  });
  await expect(page.locator(".worldWorkspace")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByLabel("Barra de comando")).toBeVisible();
  await expect(page.getByLabel("Buscar conteúdo")).toBeVisible();
}

test("pt-BR proves one functional WebGL world and its explicit topology-equivalent fallback", async ({ page }, testInfo) => {
  await forcePortugueseWiki(page);
  await page.goto("/demo/w/quadrants?center=root-alex-rivera&tour=0");
  await waitForWorld(page);

  const scene = page.locator(".sceneShell");
  await expect(scene).not.toHaveClass(/fallbackMode/);
  await expect(scene).toHaveAttribute("data-scene-fallback-reason", "");
  await expect(scene.locator("canvas")).toHaveCount(1);
  const webgl = await scene.locator("canvas").evaluate((canvas) => {
    const element = canvas as HTMLCanvasElement;
    const context = element.getContext("webgl2") || element.getContext("webgl");
    if (!context) return null;
    return {
      drawingBufferHeight: context.drawingBufferHeight,
      drawingBufferWidth: context.drawingBufferWidth,
      lost: context.isContextLost(),
      version: String(context.getParameter(context.VERSION))
    };
  });
  expect(webgl).not.toBeNull();
  expect(webgl?.drawingBufferWidth).toBeGreaterThan(0);
  expect(webgl?.drawingBufferHeight).toBeGreaterThan(0);
  expect(webgl?.lost).toBe(false);
  expect(webgl?.version).toMatch(/WebGL/i);
  // WebGL/fonts are platform-rendered. Keep the reviewed macOS pixels strict;
  // Linux still executes the semantic GPU/context proof and emits an evidence
  // attachment instead of comparing against a knowingly false copied raster.
  if (process.platform === "darwin") {
    await expect(page).toHaveScreenshot("pt-br-webgl-functional.png", {
      animations: "disabled",
      fullPage: false
    });
  }
  await attachViewportScreenshot(page, testInfo, "pt-br-webgl-functional");

  await page.goto("/demo/w/quadrants?center=root-alex-rivera&visual=1&tour=0");
  await waitForWorld(page);
  await expect(scene).toHaveClass(/fallbackMode/);
  await expect(scene).toHaveAttribute("data-scene-fallback-reason", "visual_test");
  await expect(scene.locator("canvas")).toHaveCount(0);
  const fallback = scene.getByLabel("Mapa de conteúdo");
  await expect(fallback).toBeVisible();
  await expect(fallback.locator(".fallbackCore")).toContainText("Conteúdo aprovado");
  await expect(fallback.locator(".fallbackCore")).toContainText(/Espaço (aprovado|atual)/);
  await expect(page.locator(".worldWorkspace")).toHaveAttribute(
    "data-world-center",
    "root-alex-rivera"
  );
  if (process.platform === "darwin") {
    await expect(page).toHaveScreenshot("pt-br-explicit-fallback.png", {
      animations: "disabled",
      fullPage: false
    });
  }
  await attachViewportScreenshot(page, testInfo, "pt-br-explicit-fallback");
});

test("pt-BR browser journey keeps long guidance, reader, approval warning and mobile controls localized", async ({ page }, testInfo) => {
  await forcePortugueseWiki(page);
  await page.goto("/demo/w/quadrants?center=root-alex-rivera&visual=1&tour=0");
  await waitForWorld(page);

  const commandSearch = page.getByLabel("Buscar conteúdo");
  await commandSearch.fill("/god_mode");
  await commandSearch.press("Enter");
  const visualLab = page.getByRole("dialog", {
    name: "Controles visuais do modo mestre"
  });
  await expect(visualLab).toBeVisible();
  await expect(visualLab).toContainText("Ajuste o mundo ao vivo");
  await expect(visualLab).toContainText("Movimento");
  await expect(visualLab).toContainText("Sobreposições de partículas");
  await expect(visualLab.getByRole("button", { name: "Linha de base" })).toBeVisible();
  await visualLab.getByRole("button", { name: "Fechar controles visuais" }).click();

  await page.locator(".worldNavigatorLearn").click();
  const guide = page.getByRole("region", { name: "Como ler este mundo" });
  await expect(guide).toBeVisible();
  await expect(guide).toContainText(
    "Combine uma visão, uma lente e uma sobreposição para responder outra pergunta operacional"
  );
  await expect(guide).toContainText(
    "Um mapa 2×2 estável de intenção, prática, relações e sistemas"
  );
  await page.locator(".worldNavigatorClose").click();

  const search = page.getByLabel("Buscar conteúdo");
  await search.fill("Alex Rivera");
  await search.press("Enter");
  const reader = page.locator(".pageReader");
  await expect(reader).toBeVisible();
  await expect(reader).toHaveAttribute("aria-label", /Leitor:/);
  await expect(reader.getByRole("button", { name: "Fechar leitor (Esc)" })).toBeVisible();
  await reader.getByRole("button", { name: "Fechar leitor (Esc)" }).click();

  await page.goto(
    "/demo/w/quadrants?center=root-alex-rivera&dock=approve&visual=1&tour=0"
  );
  await waitForWorld(page);
  const approval = page.getByRole("dialog", { name: "Aprovar mudanças" });
  await expect(approval).toBeVisible();
  await expect(approval).toContainText(
    "O cockpit prepara o pedido; o sim/não final acontece no GitHub."
  );
  await expect(approval).toContainText(/passou|falhou|não rodou|parcial/);
  await attachViewportScreenshot(page, testInfo, "pt-br-reader-and-approval");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/demo/w/quadrants?center=root-alex-rivera&visual=1&tour=0");
  await waitForWorld(page);
  await page.locator(".worldNavigatorLearn").click();
  await expect(guide).toBeVisible();
  const mobileGeometry = await page.evaluate(() => {
    const panel = document.querySelector<HTMLElement>(".worldNavigatorPanel");
    const controls = [...document.querySelectorAll<HTMLElement>(
      ".worldCommandBar button, .worldCommandBar summary, .worldNavigatorPanel button"
    )].filter((element) => {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden";
    });
    if (!panel || controls.length === 0) return null;
    const panelRect = panel.getBoundingClientRect();
    return {
      documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      minimumControlHeight: Math.min(...controls.map((control) => control.getBoundingClientRect().height)),
      shortControls: controls
        .map((control) => ({
          className: control.className,
          height: control.getBoundingClientRect().height,
          label: control.getAttribute("aria-label") || control.textContent?.trim().slice(0, 80) || ""
        }))
        .filter((control) => control.height < 44),
      panel: {
        bottom: panelRect.bottom,
        left: panelRect.left,
        right: panelRect.right,
        top: panelRect.top
      },
      viewport: { height: window.innerHeight, width: window.innerWidth }
    };
  });
  expect(mobileGeometry).not.toBeNull();
  expect(mobileGeometry?.documentOverflow).toBeLessThanOrEqual(1);
  expect(mobileGeometry?.shortControls).toEqual([]);
  expect(mobileGeometry?.minimumControlHeight).toBeGreaterThanOrEqual(44);
  expect(mobileGeometry?.panel.left).toBeGreaterThanOrEqual(0);
  expect(mobileGeometry?.panel.right).toBeLessThanOrEqual(mobileGeometry?.viewport.width ?? 0);
  expect(mobileGeometry?.panel.top).toBeGreaterThanOrEqual(0);
  expect(mobileGeometry?.panel.bottom).toBeLessThanOrEqual(mobileGeometry?.viewport.height ?? 0);
  await attachViewportScreenshot(page, testInfo, "pt-br-mobile-long-copy");
});
