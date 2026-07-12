// @vitest-environment happy-dom

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  APPEARANCE_CONTRACT_VERSION,
  APPEARANCE_DENSITIES,
  APPEARANCE_DENSITY_IDS,
  APPEARANCE_STORAGE_KEY,
  APPEARANCE_THEMES,
  APPEARANCE_THEME_IDS,
  DEFAULT_APPEARANCE,
  applyAppearancePreferences,
  loadAppearancePreferences,
  normalizeAppearancePreferences,
  persistAppearancePreferences
} from "./appearance";

const shellCss = readFileSync(resolve(process.cwd(), "src/shell.css"), "utf8");

function themeToken(theme: string, token: string): string {
  const selector = `html[data-wiki-theme="${theme}"] {`;
  const start = shellCss.indexOf(selector);
  const end = shellCss.indexOf("\n}", start);
  const block = start >= 0 && end > start ? shellCss.slice(start, end) : "";
  const value = block.match(new RegExp(`--wiki-${token}:\\s*(#[0-9a-fA-F]{6})`))?.[1];
  if (!value) throw new Error(`missing ${theme} ${token} token`);
  return value;
}

function channel(value: number): number {
  const normalized = value / 255;
  return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const [red, green, blue] = [1, 3, 5].map((offset) => channel(Number.parseInt(hex.slice(offset, offset + 2), 16)));
  return (0.2126 * red) + (0.7152 * green) + (0.0722 * blue);
}

function contrastRatio(foreground: string, background: string): number {
  const [bright, dark] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (bright + 0.05) / (dark + 0.05);
}

describe("appearance registry", () => {
  it("ships two typed themes and three presentation-only density modes", () => {
    expect(APPEARANCE_CONTRACT_VERSION).toBe("wiki_cockpit_appearance.v1");
    expect(APPEARANCE_THEME_IDS).toEqual(["luminous-observatory", "night-mission-control"]);
    expect(Object.keys(APPEARANCE_THEMES)).toEqual(APPEARANCE_THEME_IDS);
    expect(APPEARANCE_THEMES["luminous-observatory"].colorScheme).toBe("light");
    expect(APPEARANCE_THEMES["night-mission-control"].colorScheme).toBe("dark");

    expect(APPEARANCE_DENSITY_IDS).toEqual(["focus", "balanced", "command"]);
    expect(Object.keys(APPEARANCE_DENSITIES)).toEqual(APPEARANCE_DENSITY_IDS);
    expect(DEFAULT_APPEARANCE).toEqual({ theme: "night-mission-control", density: "balanced" });
  });

  it("fails closed to known values and tolerates unavailable or malformed storage", () => {
    expect(normalizeAppearancePreferences({ theme: "unknown", density: "maximum" })).toEqual(DEFAULT_APPEARANCE);
    expect(loadAppearancePreferences(undefined)).toEqual(DEFAULT_APPEARANCE);
    expect(loadAppearancePreferences({ getItem: () => "not-json" })).toEqual(DEFAULT_APPEARANCE);

    const writes: Record<string, string> = {};
    persistAppearancePreferences(
      { setItem: (key, value) => { writes[key] = value; } },
      { theme: "luminous-observatory", density: "command" }
    );
    expect(JSON.parse(writes[APPEARANCE_STORAGE_KEY])).toEqual({
      theme: "luminous-observatory",
      density: "command"
    });
  });

  it("applies only data and color-scheme presentation state to the document root", () => {
    const root = document.createElement("html");
    applyAppearancePreferences(root, { theme: "luminous-observatory", density: "focus" });
    expect(root.dataset.wikiTheme).toBe("luminous-observatory");
    expect(root.dataset.wikiDensity).toBe("focus");
    expect(root.style.colorScheme).toBe("light");
  });

  it("keeps primary text and signal tokens at WCAG AA contrast in both themes", () => {
    for (const theme of APPEARANCE_THEME_IDS) {
      const backgrounds = [themeToken(theme, "bg"), themeToken(theme, "surface")];
      const foregrounds = ["text", "text-muted", "accent", "accent-strong", "state-good"]
        .map((token) => themeToken(theme, token));
      for (const background of backgrounds) {
        for (const foreground of foregrounds) {
          expect(
            contrastRatio(foreground, background),
            `${theme}: ${foreground} on ${background}`
          ).toBeGreaterThanOrEqual(4.5);
        }
      }
    }
  });

  it("keeps 44px hit targets and explicit reduced-motion and forced-colors fallbacks", () => {
    expect(shellCss).toMatch(/\.appearanceControl > summary \{[\s\S]*?min-width: 44px;[\s\S]*?min-height: 44px;/);
    expect(shellCss).toMatch(/\.appearanceDensityOptions button \{[\s\S]*?min-height: 44px;/);
    expect(shellCss).toContain("@media (prefers-reduced-motion: reduce)");
    expect(shellCss).toContain("@media (forced-colors: active)");
  });
});
