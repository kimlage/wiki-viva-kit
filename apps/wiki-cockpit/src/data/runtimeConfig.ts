import { configurePresentation } from "./presentation";
import type { PresentationOverrides } from "./presentation";

// Presentation feature flags (plan §17.2): the public runtime file may only
// toggle how things LOOK — it can never grant capability, role or session.
// The easter egg ships on by default; the companion waits for the operator
// session work and stays off until then.
export type RuntimeFeatureFlags = {
  takezoEasterEgg: boolean;
  takezoCompanion: boolean;
};

export type RuntimeConfig = {
  apiBase: string;
  snapshotBase: string;
  repoLabel: string;
  mode: string;
  language: string;
  strings: Record<string, string>;
  presentation: PresentationOverrides;
  features: RuntimeFeatureFlags;
  codexEnabled: boolean;
};

type RawRuntimeConfig = {
  api_base?: string;
  snapshot_base?: string;
  repo_label?: string;
  mode?: string;
  language?: string;
  strings?: Record<string, string>;
  page_types?: PresentationOverrides["page_types"];
  contexts?: PresentationOverrides["contexts"];
  trust_colors?: PresentationOverrides["trust_colors"];
  features?: { takezo_easter_egg?: boolean; takezo_companion?: boolean };
  codex?: { enabled?: boolean };
};

const DEFAULT_CONFIG: RuntimeConfig = {
  apiBase: "/api",
  snapshotBase: "",
  repoLabel: "",
  mode: "local_operator",
  language: "",
  strings: {},
  presentation: {},
  features: { takezoEasterEgg: true, takezoCompanion: false },
  codexEnabled: true
};

let runtimeConfigPromise: Promise<RuntimeConfig> | null = null;

function cleanBase(value: string | undefined): string {
  return (value || "").trim().replace(/\/+$/, "");
}

export function normalizeRuntimeConfig(raw: RawRuntimeConfig): RuntimeConfig {
  const hasApiBase = Object.prototype.hasOwnProperty.call(raw, "api_base");
  return {
    apiBase: hasApiBase ? cleanBase(raw.api_base) : DEFAULT_CONFIG.apiBase,
    snapshotBase: cleanBase(raw.snapshot_base),
    repoLabel: String(raw.repo_label || "").trim(),
    mode: String(raw.mode || DEFAULT_CONFIG.mode).trim() || DEFAULT_CONFIG.mode,
    language: String(raw.language || "").trim(),
    strings: raw.strings || {},
    presentation: {
      page_types: raw.page_types || {},
      contexts: raw.contexts || {},
      trust_colors: raw.trust_colors || {}
    },
    features: {
      takezoEasterEgg: raw.features?.takezo_easter_egg !== false,
      takezoCompanion: raw.features?.takezo_companion === true
    },
    codexEnabled: raw.codex?.enabled !== false
  };
}

export async function loadRuntimeConfig(): Promise<RuntimeConfig> {
  if (!runtimeConfigPromise) {
    runtimeConfigPromise = fetch("/wiki-cockpit.config.json", { cache: "no-store", headers: { accept: "application/json" } })
      .then(async (response) => {
        if (!response.ok) return DEFAULT_CONFIG;
        return normalizeRuntimeConfig((await response.json()) as RawRuntimeConfig);
      })
      .catch(() => DEFAULT_CONFIG)
      .then((config) => {
        configurePresentation(config.presentation);
        return config;
      });
  }
  return runtimeConfigPromise;
}

export async function apiUrl(path: string): Promise<string> {
  const config = await loadRuntimeConfig();
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${config.apiBase}${suffix}`;
}
