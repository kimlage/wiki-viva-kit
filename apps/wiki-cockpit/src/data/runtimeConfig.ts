import { configurePresentation } from "./presentation";
import type { PresentationOverrides } from "./presentation";

export type RuntimeConfig = {
  apiBase: string;
  snapshotBase: string;
  repoLabel: string;
  mode: string;
  language: string;
  strings: Record<string, string>;
  presentation: PresentationOverrides;
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
  codexEnabled: true
};

let runtimeConfigPromise: Promise<RuntimeConfig> | null = null;

function cleanBase(value: string | undefined): string {
  return (value || "").trim().replace(/\/+$/, "");
}

function normalize(raw: RawRuntimeConfig): RuntimeConfig {
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
    codexEnabled: raw.codex?.enabled !== false
  };
}

export async function loadRuntimeConfig(): Promise<RuntimeConfig> {
  if (!runtimeConfigPromise) {
    runtimeConfigPromise = fetch("/wiki-cockpit.config.json", { cache: "no-store", headers: { accept: "application/json" } })
      .then(async (response) => {
        if (!response.ok) return DEFAULT_CONFIG;
        return normalize((await response.json()) as RawRuntimeConfig);
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
