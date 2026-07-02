import type {
  CodexCapability,
  IngestionPlan,
  IngestionStepResult,
  PageContent,
  SnapshotBundle,
  SourceTriageResult,
  WorkflowRunResult
} from "../types";
import { CODEX_UNAVAILABLE } from "../types";
import type { RuntimeConfig } from "./runtimeConfig";
import { apiUrl, loadRuntimeConfig } from "./runtimeConfig";

const FILES = {
  manifest: "manifest.json",
  operations: "operations.json",
  graph: "graph.json",
  pages: "pages.json",
  actions: "actions.json",
  freshness: "freshness.json",
  gates: "gates.json",
  git: "git.json",
  timeline: "timeline.json",
  diff: "diff.json",
  sources: "sources.json",
  decisions: "decisions.json",
  ingestion: "ingestion.json",
  quality: "quality.json",
  commands: "commands.json"
} as const;

export const SAMPLE_BASE = "/sample-snapshot";

function demoModeRequested(): boolean {
  if (typeof window === "undefined") return false;
  return window.location.pathname.startsWith("/demo") || new URLSearchParams(window.location.search).get("demo") === "1";
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

const EMPTY_SCORE = {
  schema_version: "wiki_web_score.v1",
  enabled: false,
  event_count: 0,
  total: 0,
  level: null,
  level_labels: {},
  by_dimension: {},
  badges: [],
  vitality: {}
};

async function loadFromBase(base: string): Promise<SnapshotBundle> {
  const entries = await Promise.all(
    Object.entries(FILES).map(async ([key, file]) => [key, await fetchJson(`${base}/${file}`)])
  );
  const bundle = Object.fromEntries(entries) as SnapshotBundle;
  // Optional read models keep old snapshots loadable.
  bundle.score = await fetchJson(`${base}/score.json`).catch(() => EMPTY_SCORE) as SnapshotBundle["score"];
  return bundle;
}

export async function loadSnapshotBundle(
  options: { demo?: boolean } = {}
): Promise<{ bundle: SnapshotBundle; source: string; runtime: RuntimeConfig }> {
  // Demo is an in-memory bundle switch: synthetic ids never resolve against
  // the real snapshot, and switching universes never reloads the document.
  if (options.demo ?? demoModeRequested()) {
    // Load the runtime config anyway so presentation overrides still apply to demo data.
    const demoRuntime = await loadRuntimeConfig();
    return {
      bundle: await loadFromBase(SAMPLE_BASE),
      source: SAMPLE_BASE,
      runtime: { ...demoRuntime, apiBase: "", snapshotBase: SAMPLE_BASE, repoLabel: "wiki-viva-kit demo", mode: "static_demo" }
    };
  }
  const configured = import.meta.env.VITE_WIKI_SNAPSHOT_BASE as string | undefined;
  const runtime = await loadRuntimeConfig();
  const runtimeBase = runtime.snapshotBase || "";
  const apiBase = `${runtime.apiBase}/snapshot`;
  const bases = [configured, runtimeBase, apiBase, SAMPLE_BASE].filter((base): base is string => Boolean(base));
  let lastError: unknown = null;
  for (const base of bases) {
    try {
      return { bundle: await loadFromBase(base), source: base, runtime };
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError instanceof Error ? lastError : new Error("snapshot unavailable");
}

// Mirrors wiki_core.web.content.sidecar_name (fnv-1a 32-bit) so the static
// reader can address content/{slug}.{hash}.json without a server.
export function sidecarName(pageId: string): string {
  let hash = 0x811c9dc5;
  const bytes = new TextEncoder().encode(pageId);
  for (const byte of bytes) {
    hash ^= byte;
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  const slug =
    pageId
      .toLowerCase()
      .replace(/[^a-z0-9._-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "page";
  return `${slug}.${hash.toString(16).padStart(8, "0")}.json`;
}

export async function loadPageContent(
  pageId: string,
  options: { demo?: boolean; snapshotSource?: string } = {}
): Promise<PageContent> {
  const attempts: (() => Promise<PageContent>)[] = [];
  if (options.demo) {
    attempts.push(() => fetchJson<PageContent>(`${SAMPLE_BASE}/content/${sidecarName(pageId)}`));
  } else {
    attempts.push(async () => {
      const response = await fetch(await apiUrl(`/pages/${encodeURIComponent(pageId)}/content`), {
        headers: { accept: "application/json" }
      });
      const payload = (await response.json()) as PageContent;
      if (!response.ok && !payload.error) throw new Error(`content failed: ${response.status}`);
      return payload;
    });
    const base = options.snapshotSource;
    if (base && !base.endsWith("/api/snapshot")) {
      attempts.push(() => fetchJson<PageContent>(`${base}/content/${sidecarName(pageId)}`));
    }
  }
  let lastError: unknown = null;
  for (const attempt of attempts) {
    try {
      const payload = await attempt();
      if (payload && payload.ok) return payload;
      if (payload && payload.error) lastError = new Error(payload.error);
    } catch (error) {
      lastError = error;
    }
  }
  return {
    ok: false,
    error: lastError instanceof Error ? lastError.message : "conteúdo indisponível neste modo"
  };
}

// Live Codex capability. Only the local operator can run Codex, so demo/static
// mode never fetches — it reports the honest "unavailable" record straight away.
// A network/parse failure also degrades to unavailable rather than throwing:
// the launch CTA must fail closed, never fake availability.
export async function loadCodexCapability(runtime: RuntimeConfig): Promise<CodexCapability> {
  if (runtime.mode === "static_demo" || !runtime.codexEnabled) {
    return {
      ...CODEX_UNAVAILABLE,
      enabled: runtime.codexEnabled,
      reason: runtime.codexEnabled
        ? "Codex runs only with the local operator — not in this demo."
        : "Codex is turned off for this wiki."
    };
  }
  try {
    const response = await fetch(await apiUrl("/codex/capability"), { headers: { accept: "application/json" } });
    if (!response.ok) return { ...CODEX_UNAVAILABLE, reason: `capability check failed: ${response.status}` };
    const payload = (await response.json()) as CodexCapability;
    return { ...CODEX_UNAVAILABLE, ...payload };
  } catch (error) {
    return { ...CODEX_UNAVAILABLE, reason: error instanceof Error ? error.message : "capability check failed" };
  }
}

export async function runCockpitAction(
  actionId: string,
  dryRun?: boolean
): Promise<import("../types").ActionRunResult> {
  const response = await fetch(await apiUrl("/actions/run"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ action_id: actionId, dry_run: dryRun })
  });
  const payload = (await response.json()) as import("../types").ActionRunResult;
  if (!response.ok) {
    throw new Error(payload.error || `action failed: ${response.status}`);
  }
  return payload;
}

export async function runGitWorkflow(
  operation: string,
  payload: Record<string, unknown> = {},
  dryRun = true
): Promise<WorkflowRunResult> {
  const response = await fetch(await apiUrl("/git/workflow"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ ...payload, operation, dry_run: dryRun })
  });
  const result = (await response.json()) as WorkflowRunResult;
  if (!response.ok && !result.operation) {
    throw new Error(result.error || `workflow failed: ${response.status}`);
  }
  return result;
}

export async function triageSource(source: string, context?: string): Promise<SourceTriageResult> {
  const response = await fetch(await apiUrl("/sources/triage"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source, context })
  });
  const result = (await response.json()) as SourceTriageResult;
  if (!response.ok && !result.risk_flags && !result.error) {
    throw new Error(`source triage failed: ${response.status}`);
  }
  return result;
}

export async function buildIngestionPlan(source: string, context?: string): Promise<IngestionPlan> {
  const response = await fetch(await apiUrl("/ingestion/plan"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source, context })
  });
  const result = (await response.json()) as IngestionPlan;
  if (!response.ok && !result.stages) {
    throw new Error(result.error || `ingestion plan failed: ${response.status}`);
  }
  return result;
}

export async function runIngestionStep(
  source: string,
  context: string,
  stepId: string,
  dryRun = true
): Promise<IngestionStepResult> {
  const response = await fetch(await apiUrl("/ingestion/run"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source, context, step_id: stepId, dry_run: dryRun })
  });
  const result = (await response.json()) as IngestionStepResult;
  if (!response.ok && !result.step_id) {
    throw new Error(result.error || `ingestion step failed: ${response.status}`);
  }
  return result;
}
