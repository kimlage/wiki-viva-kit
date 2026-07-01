import type { SnapshotBundle, SourceTriageResult, WorkflowRunResult } from "../types";

const FILES = {
  manifest: "manifest.json",
  operations: "operations.json",
  graph: "graph.json",
  pages: "pages.json",
  actions: "actions.json",
  freshness: "freshness.json",
  gates: "gates.json",
  git: "git.json",
  sources: "sources.json",
  decisions: "decisions.json",
  ingestion: "ingestion.json",
  quality: "quality.json",
  commands: "commands.json"
} as const;

export const SAMPLE_BASE = "/sample-snapshot";

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

async function loadFromBase(base: string): Promise<SnapshotBundle> {
  const entries = await Promise.all(
    Object.entries(FILES).map(async ([key, file]) => [key, await fetchJson(`${base}/${file}`)])
  );
  return Object.fromEntries(entries) as SnapshotBundle;
}

export async function loadSnapshotBundle(): Promise<{ bundle: SnapshotBundle; source: string }> {
  const configured = import.meta.env.VITE_WIKI_SNAPSHOT_BASE as string | undefined;
  const bases = configured ? [configured, "/api/snapshot", SAMPLE_BASE] : ["/api/snapshot", SAMPLE_BASE];
  let lastError: unknown = null;
  for (const base of bases) {
    try {
      return { bundle: await loadFromBase(base), source: base };
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError instanceof Error ? lastError : new Error("snapshot unavailable");
}

export async function runCockpitAction(
  actionId: string,
  dryRun?: boolean
): Promise<import("../types").ActionRunResult> {
  const response = await fetch("/api/actions/run", {
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
  const response = await fetch("/api/git/workflow", {
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
  const response = await fetch("/api/sources/triage", {
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
