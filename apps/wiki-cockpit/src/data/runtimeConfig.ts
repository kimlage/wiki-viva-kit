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

export function applyRuntimeEnv(
  config: RuntimeConfig,
  env: Record<string, unknown>
): RuntimeConfig {
  const value = (key: string): string | undefined =>
    typeof env[key] === "string" ? String(env[key]) : undefined;
  const apiBase = value("VITE_WIKI_API_BASE");
  const snapshotBase = value("VITE_WIKI_SNAPSHOT_BASE");
  const repoLabel = value("VITE_WIKI_REPO_LABEL");
  const mode = value("VITE_WIKI_RUNTIME_MODE");
  return {
    ...config,
    apiBase: apiBase === undefined ? config.apiBase : cleanBase(apiBase),
    snapshotBase:
      snapshotBase === undefined ? config.snapshotBase : cleanBase(snapshotBase),
    repoLabel: repoLabel === undefined ? config.repoLabel : repoLabel.trim(),
    mode:
      mode === undefined
        ? config.mode
        : mode.trim() || DEFAULT_CONFIG.mode
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
        const resolved = applyRuntimeEnv(config, import.meta.env);
        configurePresentation(resolved.presentation);
        return resolved;
      });
  }
  return runtimeConfigPromise;
}

export async function apiUrl(path: string): Promise<string> {
  const config = await loadRuntimeConfig();
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${config.apiBase}${suffix}`;
}
