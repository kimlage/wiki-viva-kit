import { Check, Gauge, Palette } from "lucide-react";
import { useEffect, useLayoutEffect, useState } from "react";
import {
  APPEARANCE_DENSITIES,
  APPEARANCE_DENSITY_IDS,
  APPEARANCE_STORAGE_KEY,
  APPEARANCE_THEMES,
  APPEARANCE_THEME_IDS,
  applyAppearancePreferences,
  loadAppearancePreferences,
  normalizeAppearancePreferences,
  persistAppearancePreferences
} from "../data/appearance";
import type { AppearanceDensityId, AppearancePreferences, AppearanceThemeId } from "../data/appearance";
import { t } from "../data/i18n";

function browserStorage(): Storage | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

export function AppearanceControl() {
  const [preferences, setPreferences] = useState<AppearancePreferences>(() =>
    loadAppearancePreferences(typeof window === "undefined" ? undefined : browserStorage())
  );

  useLayoutEffect(() => {
    applyAppearancePreferences(document.documentElement, preferences);
  }, [preferences]);

  useEffect(() => {
    persistAppearancePreferences(browserStorage(), preferences);
  }, [preferences]);

  useEffect(() => {
    const syncStoredAppearance = (event: StorageEvent) => {
      if (event.key !== APPEARANCE_STORAGE_KEY || !event.newValue) return;
      try {
        setPreferences(normalizeAppearancePreferences(JSON.parse(event.newValue)));
      } catch {
        // Ignore malformed writes from another tab and keep the valid local state.
      }
    };
    window.addEventListener("storage", syncStoredAppearance);
    return () => window.removeEventListener("storage", syncStoredAppearance);
  }, []);

  const chooseTheme = (theme: AppearanceThemeId) => {
    setPreferences((current) => ({ ...current, theme }));
  };
  const chooseDensity = (density: AppearanceDensityId) => {
    setPreferences((current) => ({ ...current, density }));
  };

  return (
    <details className="appearanceControl">
      <summary aria-label={t("appearance.open")} title={t("appearance.open")}>
        <Palette size={16} aria-hidden="true" />
        <span className="appearanceControlSummaryText">{t("appearance.shortLabel")}</span>
      </summary>
      <div className="appearanceControlMenu" aria-label={t("appearance.panel")} role="region">
        <header>
          <Palette size={16} aria-hidden="true" />
          <div>
            <strong>{t("appearance.title")}</strong>
            <small>{t("appearance.description")}</small>
          </div>
        </header>

        <fieldset>
          <legend>{t("appearance.theme.label")}</legend>
          <div className="appearanceOptionGrid">
            {APPEARANCE_THEME_IDS.map((themeId) => {
              const theme = APPEARANCE_THEMES[themeId];
              const selected = preferences.theme === themeId;
              return (
                <button
                  aria-label={t("appearance.theme.use", { theme: t(theme.labelKey) })}
                  aria-pressed={selected}
                  className={selected ? "appearanceOption selected" : "appearanceOption"}
                  key={themeId}
                  onClick={() => chooseTheme(themeId)}
                  type="button"
                >
                  <span className={`appearanceThemeSwatch appearanceThemeSwatch--${themeId}`} aria-hidden="true" />
                  <span>
                    <strong>{t(theme.labelKey)}</strong>
                    <small>{t(theme.descriptionKey)}</small>
                  </span>
                  {selected && <Check className="appearanceSelectedIcon" size={15} aria-hidden="true" />}
                </button>
              );
            })}
          </div>
        </fieldset>

        <fieldset>
          <legend>
            <Gauge size={14} aria-hidden="true" />
            {t("appearance.density.label")}
          </legend>
          <div className="appearanceDensityOptions" role="group" aria-label={t("appearance.density.group")}>
            {APPEARANCE_DENSITY_IDS.map((densityId) => {
              const density = APPEARANCE_DENSITIES[densityId];
              const selected = preferences.density === densityId;
              return (
                <button
                  aria-label={t("appearance.density.use", { density: t(density.labelKey) })}
                  aria-pressed={selected}
                  className={selected ? "selected" : ""}
                  key={densityId}
                  onClick={() => chooseDensity(densityId)}
                  title={t(density.descriptionKey)}
                  type="button"
                >
                  {t(density.labelKey)}
                  {selected && <Check size={13} aria-hidden="true" />}
                </button>
              );
            })}
          </div>
          <p className="appearanceDensityDescription">
            {t(APPEARANCE_DENSITIES[preferences.density].descriptionKey)}
          </p>
        </fieldset>
      </div>
    </details>
  );
}
