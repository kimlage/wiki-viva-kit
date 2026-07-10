import { expect, type Page } from "@playwright/test";

type SpatialCardRect = {
  bottom: number;
  index: number;
  label: string;
  left: number;
  right: number;
  top: number;
};

export async function expectSpatialCardsWithinSafeArea(
  page: Page,
  options: { expectedPrimary: number; expectedTotal: number }
) {
  await page.locator(".spatialCard").first().evaluate(async (element) => {
    const finite = element.getAnimations().filter((animation) => animation.effect?.getTiming().iterations !== Infinity);
    await Promise.all(finite.map((animation) => animation.finished.catch(() => undefined)));
  });
  const result = await page.evaluate(() => {
    const viewport = { width: window.innerWidth, height: window.innerHeight };
    const topStrip = document.querySelector(".worldTopStrip")?.getBoundingClientRect();
    const commandBar = document.querySelector(".worldCommandBar")?.getBoundingClientRect();
    const palette = document.querySelector<HTMLElement>(".seedPalettePlate")?.getBoundingClientRect();
    const cards: SpatialCardRect[] = Array.from(document.querySelectorAll<HTMLElement>(".spatialCard"))
      .map((element, index) => {
        const rect = element.getBoundingClientRect();
        return {
          bottom: rect.bottom,
          index,
          label: element.textContent?.trim().replace(/\s+/g, " ").slice(0, 120) ?? `card-${index}`,
          left: rect.left,
          right: rect.right,
          top: rect.top
        };
      });
    const violations: { card: string; reason: string; value?: number }[] = [];
    const safeTop = Math.max(8, (topStrip?.bottom ?? 0) + 8);
    const safeBottom = Math.min(viewport.height - 8, (commandBar?.top ?? viewport.height) - 8);
    for (const card of cards) {
      if (card.left < 8) violations.push({ card: card.label, reason: "left viewport", value: card.left });
      if (card.right > viewport.width - 8) violations.push({ card: card.label, reason: "right viewport", value: card.right });
      if (card.top < safeTop) violations.push({ card: card.label, reason: "top HUD", value: card.top - safeTop });
      if (card.bottom > safeBottom) violations.push({ card: card.label, reason: "command bar", value: card.bottom - safeBottom });
    }
    for (let first = 0; first < cards.length; first += 1) {
      for (let second = first + 1; second < cards.length; second += 1) {
        const a = cards[first];
        const b = cards[second];
        if (!a || !b) continue;
        const width = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
        const height = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
        const area = width * height;
        if (area > 16) violations.push({ card: `${a.label} ↔ ${b.label}`, reason: "card overlap", value: Math.round(area) });
      }
    }
    return {
      cards,
      palette: palette
        ? { bottom: palette.bottom, left: palette.left, right: palette.right, top: palette.top }
        : null,
      primaryCount: document.querySelectorAll(".spatialCardType").length,
      safeTop,
      safeBottom,
      viewport,
      violations
    };
  });

  expect(result.primaryCount, "all curated primary types must be rendered").toBe(options.expectedPrimary);
  expect(result.cards, "primary cards plus explicit More types control").toHaveLength(options.expectedTotal);
  expect(result.safeBottom - result.safeTop, "world safe area must have usable height").toBeGreaterThan(240);
  expect(result.palette, "the complete spatial create palette must be rendered").not.toBeNull();
  if (result.palette) {
    expect.soft(result.palette.left, "create palette left viewport bound").toBeGreaterThanOrEqual(8);
    expect.soft(result.palette.right, "create palette right viewport bound").toBeLessThanOrEqual(result.viewport.width - 8);
    expect.soft(result.palette.top, "create palette must clear the top HUD").toBeGreaterThanOrEqual(result.safeTop - 1);
    expect.soft(result.palette.bottom, "create palette must clear the command bar").toBeLessThanOrEqual(result.safeBottom + 1);
  }
  expect(result.violations, "every spatial create card must be reachable without overlap").toEqual([]);
}
