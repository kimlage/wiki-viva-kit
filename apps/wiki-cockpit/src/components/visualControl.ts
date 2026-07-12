import { DEFAULT_MOTION_SPEED } from "../world/visual/motionGrammar";

export type VisualLabelMode = "quiet" | "balanced" | "dense";

export type VisualControlConfig = {
  glow: number;
  contrast: number;
  density: number;
  spacing: number;
  motion: number;
  uiScale: number;
  glass: number;
  labels: VisualLabelMode;
  particles: boolean;
};

// v2 introduces the semantic-motion baseline. loadVisualControlConfig keeps
// every v1 user choice and remaps only the former untouched default (1×).
export const VISUAL_CONTROL_STORAGE_KEY = "wikiCockpitVisualControl.v2";
export const LEGACY_VISUAL_CONTROL_STORAGE_KEY = "wikiCockpitVisualControl.v1";
export const VISUAL_CONTROL_SCHEMA = "wiki_cockpit_visual_config.v1";
export const VISUAL_CONTROL_COCKPIT_VERSION = "0.2.0";
export const VISUAL_CONTROL_COMMANDS = ["/god_mode", "/abrachaindabra"] as const;

export const DEFAULT_VISUAL_CONTROL_CONFIG: VisualControlConfig = {
  glow: 1,
  contrast: 1,
  density: 1,
  spacing: 1,
  motion: DEFAULT_MOTION_SPEED,
  uiScale: 1,
  glass: 1,
  labels: "balanced",
  particles: true
};

export const VISUAL_CONTROL_PRESETS: Record<string, VisualControlConfig> = {
  baseline: DEFAULT_VISUAL_CONTROL_CONFIG,
  "city model": {
    glow: 0.95,
    contrast: 1.08,
    density: 0.9,
    spacing: 1.18,
    motion: 0.68,
    uiScale: 0.98,
    glass: 0.9,
    labels: "quiet",
    particles: true
  },
  "debug dense": {
    glow: 1.15,
    contrast: 1.12,
    density: 1.22,
    spacing: 1.28,
    motion: 0.52,
    uiScale: 1.04,
    glass: 0.82,
    labels: "dense",
    particles: true
  },
  cinematic: {
    glow: 1.45,
    contrast: 1.16,
    density: 0.82,
    spacing: 1.05,
    motion: 0.92,
    uiScale: 1,
    glass: 1.08,
    labels: "balanced",
    particles: true
  }
};

function clamp(value: unknown, min: number, max: number, fallback: number): number {
  const numeric = typeof value === "number" && Number.isFinite(value) ? value : fallback;
  return Math.min(max, Math.max(min, numeric));
}

function labelMode(value: unknown): VisualLabelMode {
  return value === "quiet" || value === "dense" || value === "balanced" ? value : DEFAULT_VISUAL_CONTROL_CONFIG.labels;
}

export function isVisualControlCommand(value: string): boolean {
  return VISUAL_CONTROL_COMMANDS.includes(value.trim().toLowerCase() as (typeof VISUAL_CONTROL_COMMANDS)[number]);
}

export function normalizeVisualControlConfig(value: unknown): VisualControlConfig {
  const source = value && typeof value === "object" ? value as Partial<VisualControlConfig> : {};
  return {
    glow: clamp(source.glow, 0.55, 1.8, DEFAULT_VISUAL_CONTROL_CONFIG.glow),
    contrast: clamp(source.contrast, 0.8, 1.35, DEFAULT_VISUAL_CONTROL_CONFIG.contrast),
    density: clamp(source.density, 0.7, 1.35, DEFAULT_VISUAL_CONTROL_CONFIG.density),
    spacing: clamp(source.spacing, 0.72, 1.85, DEFAULT_VISUAL_CONTROL_CONFIG.spacing),
    motion: clamp(source.motion, 0, 1.4, DEFAULT_VISUAL_CONTROL_CONFIG.motion),
    uiScale: clamp(source.uiScale, 0.9, 1.12, DEFAULT_VISUAL_CONTROL_CONFIG.uiScale),
    glass: clamp(source.glass, 0.55, 1.15, DEFAULT_VISUAL_CONTROL_CONFIG.glass),
    labels: labelMode(source.labels),
    particles: typeof source.particles === "boolean" ? source.particles : DEFAULT_VISUAL_CONTROL_CONFIG.particles
  };
}

export function visualControlDefaultSnippet(config: VisualControlConfig): string {
  const normalized = normalizeVisualControlConfig(config);
  return `export const DEFAULT_VISUAL_CONTROL_CONFIG: VisualControlConfig = ${JSON.stringify(normalized, null, 2)};`;
}

export function loadVisualControlConfig(storage: Storage | undefined): VisualControlConfig {
  if (!storage) return DEFAULT_VISUAL_CONTROL_CONFIG;
  try {
    const raw = storage.getItem(VISUAL_CONTROL_STORAGE_KEY);
    if (raw) return normalizeVisualControlConfig(JSON.parse(raw));

    const legacyRaw = storage.getItem(LEGACY_VISUAL_CONTROL_STORAGE_KEY);
    if (!legacyRaw) return DEFAULT_VISUAL_CONTROL_CONFIG;
    const legacy = JSON.parse(legacyRaw) as Partial<VisualControlConfig>;
    // 1× was the old shipped default. Explicit zero and every custom speed are
    // accessibility/user intent and must survive the storage-key migration.
    return normalizeVisualControlConfig({
      ...legacy,
      motion: legacy.motion === 1 ? DEFAULT_MOTION_SPEED : legacy.motion
    });
  } catch {
    return DEFAULT_VISUAL_CONTROL_CONFIG;
  }
}

export function visualControlPayload(config: VisualControlConfig, version: string) {
  const normalized = normalizeVisualControlConfig(config);
  const defaultExportSnippet = visualControlDefaultSnippet(normalized);
  return {
    schema_version: VISUAL_CONTROL_SCHEMA,
    cockpit_version: version,
    purpose: "Local visual tuning draft. Promote to defaults only after visual QA.",
    search_commands: [...VISUAL_CONTROL_COMMANDS],
    promote_to_default: {
      file: "apps/wiki-cockpit/src/components/visualControl.ts",
      export: "DEFAULT_VISUAL_CONTROL_CONFIG",
      snippet: defaultExportSnippet
    },
    css_variables: {
      "--visual-glow": normalized.glow,
      "--visual-contrast": normalized.contrast,
      "--visual-density": normalized.density,
      "--visual-spacing": normalized.spacing,
      "--visual-motion": normalized.motion,
      "--visual-ui-scale": normalized.uiScale,
      "--visual-glass": normalized.glass
    },
    config: normalized
  };
}
