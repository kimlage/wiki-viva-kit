export type RuntimeConfig = {
  apiBase: string;
  snapshotBase: string;
  repoLabel: string;
  mode: string;
};

type RawRuntimeConfig = {
  api_base?: string;
  snapshot_base?: string;
  repo_label?: string;
  mode?: string;
};

const DEFAULT_CONFIG: RuntimeConfig = {
  apiBase: "/api",
  snapshotBase: "",
  repoLabel: "",
  mode: "local_operator"
};

let runtimeConfigPromise: Promise<RuntimeConfig> | null = null;

function cleanBase(value: string | undefined): string {
  return (value || "").trim().replace(/\/+$/, "");
}

function normalize(raw: RawRuntimeConfig): RuntimeConfig {
  return {
    apiBase: cleanBase(raw.api_base) || DEFAULT_CONFIG.apiBase,
    snapshotBase: cleanBase(raw.snapshot_base),
    repoLabel: String(raw.repo_label || "").trim(),
    mode: String(raw.mode || DEFAULT_CONFIG.mode).trim() || DEFAULT_CONFIG.mode
  };
}

export async function loadRuntimeConfig(): Promise<RuntimeConfig> {
  if (!runtimeConfigPromise) {
    runtimeConfigPromise = fetch("/wiki-cockpit.config.json", { cache: "no-store", headers: { accept: "application/json" } })
      .then(async (response) => {
        if (!response.ok) return DEFAULT_CONFIG;
        return normalize((await response.json()) as RawRuntimeConfig);
      })
      .catch(() => DEFAULT_CONFIG);
  }
  return runtimeConfigPromise;
}

export async function apiUrl(path: string): Promise<string> {
  const config = await loadRuntimeConfig();
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${config.apiBase}${suffix}`;
}
