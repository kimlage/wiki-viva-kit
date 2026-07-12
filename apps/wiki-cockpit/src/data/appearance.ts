export const APPEARANCE_CONTRACT_VERSION = "wiki_cockpit_appearance.v1";

export const APPEARANCE_THEME_IDS = [
  "luminous-observatory",
  "night-mission-control"
] as const;

export const APPEARANCE_DENSITY_IDS = ["focus", "balanced", "command"] as const;

export type AppearanceThemeId = (typeof APPEARANCE_THEME_IDS)[number];
export type AppearanceDensityId = (typeof APPEARANCE_DENSITY_IDS)[number];

export type AppearanceTheme = {
  id: AppearanceThemeId;
  labelKey: `appearance.theme.${AppearanceThemeId}`;
  descriptionKey: `appearance.theme.${AppearanceThemeId}.description`;
  colorScheme: "light" | "dark";
};

export type AppearanceDensity = {
  id: AppearanceDensityId;
  labelKey: `appearance.density.${AppearanceDensityId}`;
  descriptionKey: `appearance.density.${AppearanceDensityId}.description`;
};

export type AppearancePreferences = {
  theme: AppearanceThemeId;
  density: AppearanceDensityId;
};

export const APPEARANCE_THEMES: Readonly<Record<AppearanceThemeId, AppearanceTheme>> = {
  "luminous-observatory": {
    id: "luminous-observatory",
    labelKey: "appearance.theme.luminous-observatory",
    descriptionKey: "appearance.theme.luminous-observatory.description",
    colorScheme: "light"
  },
  "night-mission-control": {
    id: "night-mission-control",
    labelKey: "appearance.theme.night-mission-control",
    descriptionKey: "appearance.theme.night-mission-control.description",
    colorScheme: "dark"
  }
};

export const APPEARANCE_DENSITIES: Readonly<Record<AppearanceDensityId, AppearanceDensity>> = {
  focus: {
    id: "focus",
    labelKey: "appearance.density.focus",
    descriptionKey: "appearance.density.focus.description"
  },
  balanced: {
    id: "balanced",
    labelKey: "appearance.density.balanced",
    descriptionKey: "appearance.density.balanced.description"
  },
  command: {
    id: "command",
    labelKey: "appearance.density.command",
    descriptionKey: "appearance.density.command.description"
  }
};

export const DEFAULT_APPEARANCE: AppearancePreferences = {
  theme: "night-mission-control",
  density: "balanced"
};

export const APPEARANCE_STORAGE_KEY = "wikiCockpitAppearance.v1";

function isThemeId(value: unknown): value is AppearanceThemeId {
  return typeof value === "string" && APPEARANCE_THEME_IDS.includes(value as AppearanceThemeId);
}

function isDensityId(value: unknown): value is AppearanceDensityId {
  return typeof value === "string" && APPEARANCE_DENSITY_IDS.includes(value as AppearanceDensityId);
}

export function normalizeAppearancePreferences(value: unknown): AppearancePreferences {
  if (!value || typeof value !== "object") return DEFAULT_APPEARANCE;
  const candidate = value as Partial<AppearancePreferences>;
  return {
    theme: isThemeId(candidate.theme) ? candidate.theme : DEFAULT_APPEARANCE.theme,
    density: isDensityId(candidate.density) ? candidate.density : DEFAULT_APPEARANCE.density
  };
}

export function loadAppearancePreferences(
  storage: Pick<Storage, "getItem"> | null | undefined
): AppearancePreferences {
  if (!storage) return DEFAULT_APPEARANCE;
  try {
    const raw = storage.getItem(APPEARANCE_STORAGE_KEY);
    return raw ? normalizeAppearancePreferences(JSON.parse(raw)) : DEFAULT_APPEARANCE;
  } catch {
    return DEFAULT_APPEARANCE;
  }
}

export function persistAppearancePreferences(
  storage: Pick<Storage, "setItem"> | null | undefined,
  preferences: AppearancePreferences
): void {
  if (!storage) return;
  try {
    storage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify(normalizeAppearancePreferences(preferences)));
  } catch {
    // Storage can be disabled or full. The current in-memory selection remains
    // valid and route changes still keep the mounted App state.
  }
}

export function applyAppearancePreferences(
  root: HTMLElement | null | undefined,
  preferences: AppearancePreferences
): void {
  if (!root) return;
  const normalized = normalizeAppearancePreferences(preferences);
  root.dataset.wikiTheme = normalized.theme;
  root.dataset.wikiDensity = normalized.density;
  root.style.colorScheme = APPEARANCE_THEMES[normalized.theme].colorScheme;
}
