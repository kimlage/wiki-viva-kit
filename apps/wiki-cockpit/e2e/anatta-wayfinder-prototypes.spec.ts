import { expect, test } from "@playwright/test";

test.describe("Anatta Worlds Wayfinder comparison", () => {
  test("one session survives variants and commits only the receipt-authorized East mutation", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto("/prototype/anatta-worlds?variant=organism");
    const prototype = page.locator(".awPrototype");
    await expect(prototype).toHaveAttribute("data-prototype-variant", "organism");
    await expect(prototype).toHaveAttribute("data-prototype-phase", "quiet");
    await expect(page.locator("canvas")).toHaveCount(1);

    await page.getByRole("button", { name: "Ver o diff" }).click();
    await expect(prototype).toHaveAttribute("data-prototype-phase", "diff_available");

    await page.getByRole("button", { name: "Próximo protótipo" }).click();
    await expect(prototype).toHaveAttribute("data-prototype-variant", "table");
    await expect(prototype).toHaveAttribute("data-prototype-phase", "diff_available");
    await expect(page).toHaveURL(/[?&]variant=table(?:&|$)/);
    await expect(page.locator("canvas")).toHaveCount(1);

    await page.getByRole("button", { name: "Focar a tensão" }).click();
    await page.getByRole("button", { name: "Hidrografia" }).click();
    await page.getByRole("button", { name: "Clima" }).click();
    await page.getByRole("button", { name: "Comparar" }).click();
    await page.getByRole("button", { name: "Abrir missão possível" }).click();
    await page.getByRole("button", { name: /^Fazer/ }).click();
    await expect(prototype).toHaveAttribute("data-prototype-phase", "offscreen_action");

    await page.getByRole("button", { name: "Simular retorno da fonte sintética" }).click();
    await page.getByRole("button", { name: "Ver proposta do agente" }).click();
    await page.getByRole("button", { name: "Abrir gate humano" }).click();
    await expect(prototype).toHaveAttribute("data-prototype-phase", "human_gate");

    const claims = page.locator(".awClaimList article");
    await claims.nth(0).getByRole("button", { name: "aceitar" }).click();
    await claims.nth(1).getByRole("button", { name: "corrigir" }).click();
    await claims.nth(2).getByRole("button", { name: "rejeitar" }).click();
    await page.getByRole("button", { name: "Emitir receipt" }).click();
    await expect(prototype).toHaveAttribute("data-prototype-phase", "receipt_issued");
    await expect(page.locator(".awNotice").getByText("Receipt parcial emitido. A mutação ainda não foi aplicada.")).toBeVisible();

    await page.getByRole("button", { name: "Próximo protótipo" }).click();
    await expect(prototype).toHaveAttribute("data-prototype-variant", "scales");
    await expect(prototype).toHaveAttribute("data-prototype-phase", "receipt_issued");

    await page.getByRole("button", { name: "Aplicar mutação autorizada" }).click();
    await expect(prototype).toHaveAttribute("data-prototype-phase", "mutation_committed");
    await expect(page.locator(".awScalesWorldMetrics article.recovering")).toContainText("Leste");
    await expect(page.locator(".awScalesWorldMetrics article.recovering")).toContainText("26%");
    await expect(page.locator(".awScalesNavigation")).toContainText("entity.bed-east");

    await page.getByRole("button", { name: "ver equivalente 2D" }).click();
    await expect(prototype).toHaveAttribute("data-renderer-mode", "2d");
    await expect(page.locator(".awSemanticMap")).toBeVisible();
    await expect(page.locator(".awBed.east")).toHaveClass(/recovering/);
    await expect(page.locator(".awBed.east")).toContainText("26%");
    await expect(page.locator(".awBed.west")).toContainText("31%");
    await expect(page.locator(".awReservoir")).toContainText("62%");

    expect(pageErrors).toEqual([]);
  });

  test("non-canonical choices never fabricate a world mutation", async ({ page }) => {
    await page.goto("/prototype/anatta-worlds?variant=organism&renderer=2d");
    const prototype = page.locator(".awPrototype");
    await page.getByRole("button", { name: "Ver o diff" }).click();
    await page.getByRole("button", { name: "Focar a tensão" }).click();
    await page.getByRole("button", { name: "Abrir missão possível" }).click();

    await page.getByRole("button", { name: /^Delegar/ }).click();
    await expect(prototype).toHaveAttribute("data-prototype-phase", "mission_selected");
    await expect(page.locator(".awNotice").getByText(/Bloqueado pelo grant/)).toBeVisible();

    await page.getByRole("button", { name: /^Compostar/ }).click();
    await expect(prototype).toHaveAttribute("data-prototype-phase", "receipt_issued");
    await expect(page.locator(".awBed.east")).not.toHaveClass(/recovering/);
    await expect(page.getByText(/Nenhuma geografia mudou|sem mutação/i).first()).toBeVisible();
  });

  test("mobile and reduced motion retain a bounded, keyboard-operable 2D equivalent", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/prototype/anatta-worlds?variant=table&renderer=2d");

    await expect(page.locator(".awSemanticMap")).toBeVisible();
    await expect(page.getByRole("button", { name: "Ver o diff" })).toBeVisible();
    const switcherButton = page.getByRole("button", { name: "Próximo protótipo" });
    const bounds = await switcherButton.boundingBox();
    expect(bounds?.width).toBeGreaterThanOrEqual(44);
    expect(bounds?.height).toBeGreaterThanOrEqual(44);

    const overflow = await page.evaluate(() => ({
      x: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      reduced: window.matchMedia("(prefers-reduced-motion: reduce)").matches
    }));
    expect(overflow).toEqual({ x: 0, reduced: true });

    await page.keyboard.press("ArrowRight");
    await expect(page.locator(".awPrototype")).toHaveAttribute("data-prototype-variant", "scales");
    await expect(page.locator(".awPrototype")).toHaveAttribute("data-prototype-phase", "quiet");
  });
});
