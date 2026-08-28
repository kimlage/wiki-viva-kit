import { describe, expect, it } from "vitest";
import {
  DEFAULT_VISUAL_CONTROL_CONFIG,
  isVisualControlCommand,
  LEGACY_VISUAL_CONTROL_STORAGE_KEY,
  loadVisualControlConfig,
  normalizeVisualControlConfig,
  visualControlDefaultSnippet,
  VISUAL_CONTROL_COCKPIT_VERSION,
  VISUAL_CONTROL_PRESETS,
  VISUAL_CONTROL_STORAGE_KEY,
  visualControlPayload
} from "./visualControl";

describe("visual control command", () => {
  it("recognizes the hidden search commands", () => {
    expect(isVisualControlCommand("/god_mode")).toBe(true);
    expect(isVisualControlCommand(" /ABRACHAINDABRA ")).toBe(true);
    expect(isVisualControlCommand("god_mode")).toBe(false);
    expect(isVisualControlCommand("/quadrants")).toBe(false);
  });

  it("normalizes visual config ranges for safe defaults", () => {
    const config = normalizeVisualControlConfig({
      glow: 99,
      contrast: 0,
      density: 0.1,
      spacing: 99,
      motion: -5,
      uiScale: 3,
      glass: "opaque",
      labels: "verbose",
      particles: false
    });
    expect(config).toEqual({
      ...DEFAULT_VISUAL_CONTROL_CONFIG,
      glow: 1.8,
      contrast: 0.8,
      density: 0.7,
      spacing: 1.85,
      motion: 0,
      uiScale: 1.12,
      particles: false
    });
  });

  it("exports a versioned payload that can be promoted to defaults", () => {
    const payload = visualControlPayload({ ...DEFAULT_VISUAL_CONTROL_CONFIG, labels: "dense" }, VISUAL_CONTROL_COCKPIT_VERSION);
    expect(payload.schema_version).toBe("wiki_cockpit_visual_config.v1");
    expect(payload.cockpit_version).toBe("0.2.0");
    expect(payload.search_commands).toEqual(["/god_mode", "/abrachaindabra"]);
    expect(payload.promote_to_default.export).toBe("DEFAULT_VISUAL_CONTROL_CONFIG");
    expect(payload.promote_to_default.snippet).toContain("DEFAULT_VISUAL_CONTROL_CONFIG");
    expect(payload.promote_to_default.snippet).toContain('"labels": "dense"');
    expect(payload.css_variables["--visual-glow"]).toBe(1);
    expect(payload.css_variables["--visual-spacing"]).toBe(1);
    expect(payload.config.labels).toBe("dense");
  });

  it("exports the default promotion snippet directly", () => {
    const snippet = visualControlDefaultSnippet({ ...DEFAULT_VISUAL_CONTROL_CONFIG, spacing: 1.2, labels: "quiet" });
    expect(snippet).toContain("export const DEFAULT_VISUAL_CONTROL_CONFIG");
    expect(snippet).toContain('"spacing": 1.2');
    expect(snippet).toContain('"labels": "quiet"');
  });

  it("ships practical presets that remain inside safe ranges", () => {
    expect(Object.keys(VISUAL_CONTROL_PRESETS)).toEqual(["baseline", "city model", "debug dense", "cinematic"]);
    for (const preset of Object.values(VISUAL_CONTROL_PRESETS)) {
      expect(normalizeVisualControlConfig(preset)).toEqual(preset);
    }
    expect(DEFAULT_VISUAL_CONTROL_CONFIG.motion).toBe(0.78);
    expect(VISUAL_CONTROL_PRESETS["debug dense"].motion).toBeLessThan(VISUAL_CONTROL_PRESETS["city model"].motion);
    expect(VISUAL_CONTROL_PRESETS["city model"].motion).toBeLessThan(DEFAULT_VISUAL_CONTROL_CONFIG.motion);
    expect(VISUAL_CONTROL_PRESETS.cinematic.motion).toBeGreaterThan(DEFAULT_VISUAL_CONTROL_CONFIG.motion);
  });

  it("migrates v1 settings without re-enabling motion or losing tuning", () => {
    const storage = (values: Record<string, string>) => ({
      getItem: (key: string) => values[key] ?? null
    }) as Storage;

    const disabled = loadVisualControlConfig(storage({
      [LEGACY_VISUAL_CONTROL_STORAGE_KEY]: JSON.stringify({ ...DEFAULT_VISUAL_CONTROL_CONFIG, motion: 0, spacing: 1.4 })
    }));
    expect(disabled.motion).toBe(0);
    expect(disabled.spacing).toBe(1.4);

    const formerDefault = loadVisualControlConfig(storage({
      [LEGACY_VISUAL_CONTROL_STORAGE_KEY]: JSON.stringify({ ...DEFAULT_VISUAL_CONTROL_CONFIG, motion: 1, glow: 1.3 })
    }));
    expect(formerDefault.motion).toBe(DEFAULT_VISUAL_CONTROL_CONFIG.motion);
    expect(formerDefault.glow).toBe(1.3);

    const current = loadVisualControlConfig(storage({
      [LEGACY_VISUAL_CONTROL_STORAGE_KEY]: JSON.stringify({ ...DEFAULT_VISUAL_CONTROL_CONFIG, motion: 0 }),
      [VISUAL_CONTROL_STORAGE_KEY]: JSON.stringify({ ...DEFAULT_VISUAL_CONTROL_CONFIG, motion: 1.2 })
    }));
    expect(current.motion).toBe(1.2);
  });
});
