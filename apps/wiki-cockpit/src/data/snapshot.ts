import type {
  BriefRecord,
  BriefSpec,
  CodexCapability,
  CodexJobRecord,
  GateRunResult,
  IngestionPlan,
  IngestionStepResult,
  OperatorHealth,
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
  bundle.sourceEntities = await fetchJson(`${base}/source_entities.json`).catch(
    () => ({ schema_version: "wiki_web_source_entities.v1", sources: [] })
  ) as SnapshotBundle["sourceEntities"];
  bundle.templates = await fetchJson(`${base}/templates.json`).catch(
    () => ({ schema_version: "wiki_templates.v1", facets_order: [], types: {} })
  ) as SnapshotBundle["templates"];
  // v2 blocks — optional, so pre-v2 snapshots keep loading.
  bundle.blocks = await fetchJson(`${base}/blocks.json`).catch(
    () => ({ schema_version: "wiki_web_blocks.v1", blocks: {}, vocabulary: {}, warnings: [] })
  ) as SnapshotBundle["blocks"];
  bundle.blockStacks = await fetchJson(`${base}/block_stacks.json`).catch(
    () => ({ schema_version: "wiki_web_block_stacks.v1", anchors: {} })
  ) as SnapshotBundle["blockStacks"];
  return bundle;
}

export async function loadSnapshotBundle(
  options: { demo?: boolean; stage?: number | null } = {}
): Promise<{ bundle: SnapshotBundle; source: string; runtime: RuntimeConfig }> {
  // Demo is an in-memory bundle switch: synthetic ids never resolve against
  // the real snapshot, and switching universes never reloads the document.
  if (options.demo ?? demoModeRequested()) {
    // Load the runtime config anyway so presentation overrides still apply to demo data.
    const demoRuntime = await loadRuntimeConfig();
    // Genesis: each tutorial stage is a REAL pre-built snapshot (stages/<k>/) —
    // the world materializes because the data changes, never by UI simulation.
    const base = options.stage != null ? `${SAMPLE_BASE}/stages/${options.stage}` : SAMPLE_BASE;
    return {
      bundle: await loadFromBase(base),
      source: base,
      runtime: { ...demoRuntime, apiBase: "", snapshotBase: base, repoLabel: "wiki-viva-kit demo", mode: "static_demo" }
    };
  }
  const configured = import.meta.env.VITE_WIKI_SNAPSHOT_BASE as string | undefined;
  const runtime = await loadRuntimeConfig();
  const runtimeBase = runtime.snapshotBase || "";
  const apiBase = `${runtime.apiBase}/snapshot`;
  const candidates = [
    { base: configured, sampleFallback: false },
    { base: runtimeBase, sampleFallback: false },
    { base: apiBase, sampleFallback: false },
    { base: SAMPLE_BASE, sampleFallback: true }
  ].filter((candidate): candidate is { base: string; sampleFallback: boolean } => Boolean(candidate.base));
  let lastError: unknown = null;
  const seen = new Set<string>();
  for (const { base, sampleFallback } of candidates) {
    if (seen.has(`${base}:${sampleFallback ? "fallback" : "configured"}`)) continue;
    seen.add(`${base}:${sampleFallback ? "fallback" : "configured"}`);
    try {
      const bundle = await loadFromBase(base);
      if (sampleFallback) {
        // Every REAL base failed and the bundled demo sample loaded instead.
        // Never impersonate the user's wiki: mark the runtime so the shell can
        // label the world as sample data (repo label + demo-style mode).
        return {
          bundle,
          source: base,
          runtime: { ...runtime, repoLabel: "sample data (operator unreachable)", mode: "sample_fallback" }
        };
      }
      return { bundle, source: base, runtime };
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

// The operator handshake. Old operators (process older than the code on disk)
// omit server_version/schema_capabilities entirely, which is how we detect
// staleness and show the honest "restart the operator" state everywhere.
export async function loadHealth(): Promise<OperatorHealth | null> {
  try {
    const response = await fetch(await apiUrl("/health"), { headers: { accept: "application/json" } });
    if (!response.ok) return null;
    return (await response.json()) as OperatorHealth;
  } catch {
    return null;
  }
}

// Live Codex capability, read from /api/health (one fetch — the health payload
// already carries the full probe record). Only the local operator can run
// Codex, so demo/static mode never fetches. A stale operator (no `codex`
// capability) is reported as operator_outdated, NOT as "not installed" — the
// old code lied about a machine where codex is installed and authed.
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
  const health = await loadHealth();
  if (health === null) {
    return { ...CODEX_UNAVAILABLE, reason: "operator not reachable" };
  }
  // An operator that serves a codex probe is trusted — that IS the live reading,
  // even if it predates the schema_capabilities handshake (the handshake gates
  // the OTHER one-world endpoints, not codex itself). Only a codex block that is
  // entirely absent means a truly old operator (predates codex): restart it.
  if (health.codex) {
    return { ...CODEX_UNAVAILABLE, ...health.codex };
  }
  return {
    ...CODEX_UNAVAILABLE,
    operator_outdated: true,
    reason: "the local operator predates the codex API — restart it"
  };
}

export async function loadAgentCapabilities(runtime: RuntimeConfig): Promise<import("../types").AgentCapabilities> {
  const unavailable = { ...CODEX_UNAVAILABLE };
  if (runtime.mode === "static_demo") return { codex: unavailable, claude: { ...unavailable } };
  try {
    const response = await fetch(await apiUrl("/agents/capability"), { headers: { accept: "application/json" } });
    if (!response.ok) return { codex: unavailable, claude: { ...unavailable } };
    const payload = (await response.json()) as { agents?: Partial<import("../types").AgentCapabilities> };
    return {
      codex: { ...CODEX_UNAVAILABLE, ...(payload.agents?.codex ?? {}) },
      claude: { ...CODEX_UNAVAILABLE, ...(payload.agents?.claude ?? {}) }
    };
  } catch {
    return { codex: unavailable, claude: { ...unavailable } };
  }
}

// Work briefs — the agent-neutral compose/edit/save/discard surface. Compose
// is deterministic and zero-token server-side; it also persists a draft so the
// brief is inspectable and (Phase 2) executable by its stable id + sha.
export async function composeBrief(spec: BriefSpec): Promise<BriefRecord> {
  const response = await fetch(await apiUrl("/briefs"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ spec })
  });
  const result = (await response.json()) as BriefRecord;
  if (!response.ok && !result.brief_id) {
    throw new Error(result.error || `brief compose failed: ${response.status}`);
  }
  return result;
}

export async function listBriefs(): Promise<BriefRecord[]> {
  const response = await fetch(await apiUrl("/briefs"), { headers: { accept: "application/json" } });
  if (!response.ok) return [];
  const result = (await response.json()) as { ok: boolean; briefs: BriefRecord[] };
  return result.briefs || [];
}

export async function getBrief(briefId: string): Promise<BriefRecord | null> {
  const response = await fetch(await apiUrl(`/briefs/${encodeURIComponent(briefId)}`), {
    headers: { accept: "application/json" }
  });
  if (!response.ok) return null;
  return (await response.json()) as BriefRecord;
}

export async function saveBriefText(briefId: string, text: string): Promise<BriefRecord> {
  const response = await fetch(await apiUrl(`/briefs/${encodeURIComponent(briefId)}`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text })
  });
  const result = (await response.json()) as BriefRecord;
  // A refused save (e.g. non-draft) comes back ok:false WITH a brief_id — fail
  // closed so callers never treat a rejection as a saved record.
  if (!response.ok || result.ok === false) {
    throw new Error(result.error || `brief save failed: ${response.status}`);
  }
  return result;
}

export async function discardBrief(briefId: string): Promise<BriefRecord> {
  const response = await fetch(await apiUrl(`/briefs/${encodeURIComponent(briefId)}/discard`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({})
  });
  const result = (await response.json()) as BriefRecord;
  if (!response.ok && !result.brief_id) {
    throw new Error(result.error || `brief discard failed: ${response.status}`);
  }
  return result;
}

// Codex jobs — the execute exit. Submit returns the queued job record, or an
// ok:false rejection (codex unusable / sha mismatch / stale targets).
export async function spawnCodexJob(
  briefId: string,
  briefSha: string,
  options: { dryRun?: boolean; force?: boolean; parentJobId?: string; agent?: "codex" | "claude" } = {}
): Promise<CodexJobRecord> {
  const response = await fetch(await apiUrl("/codex/jobs"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      brief_id: briefId,
      brief_sha: briefSha,
      dry_run: options.dryRun ?? false,
      force: options.force ?? false,
      parent_job_id: options.parentJobId,
      agent: options.agent ?? "codex"
    })
  });
  const result = (await response.json()) as CodexJobRecord;
  if (!response.ok && !result.job_id) {
    throw new Error(result.error || `codex job failed: ${response.status}`);
  }
  return result;
}

export async function listCodexJobs(): Promise<CodexJobRecord[]> {
  const response = await fetch(await apiUrl("/codex/jobs"), { headers: { accept: "application/json" } });
  if (!response.ok) return [];
  const result = (await response.json()) as { ok: boolean; jobs: CodexJobRecord[] };
  return result.jobs || [];
}

export async function pollCodexJob(jobId: string): Promise<CodexJobRecord | null> {
  const response = await fetch(await apiUrl(`/codex/jobs/${encodeURIComponent(jobId)}`), {
    headers: { accept: "application/json" }
  });
  if (!response.ok) return null;
  return (await response.json()) as CodexJobRecord;
}

export async function streamCodexLog(jobId: string): Promise<string> {
  const response = await fetch(await apiUrl(`/codex/jobs/${encodeURIComponent(jobId)}/log`), {
    headers: { accept: "application/json" }
  });
  if (!response.ok) return "";
  const result = (await response.json()) as { ok: boolean; log: string };
  return result.log || "";
}

// Return a delivered job with feedback: composes a follow-up brief that
// continues the SAME branch. Returns the brief to open in the studio.
export async function returnCodexJob(jobId: string, feedback: string): Promise<BriefRecord> {
  const response = await fetch(await apiUrl(`/codex/jobs/${encodeURIComponent(jobId)}/return`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ feedback })
  });
  const result = (await response.json()) as BriefRecord;
  if (!response.ok && !result.brief_id) {
    throw new Error(result.error || `return failed: ${response.status}`);
  }
  return result;
}

export async function cancelCodexJob(jobId: string): Promise<CodexJobRecord | null> {
  const response = await fetch(await apiUrl(`/codex/jobs/${encodeURIComponent(jobId)}/cancel`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({})
  });
  if (!response.ok && response.status === 404) return null;
  return (await response.json()) as CodexJobRecord;
}

// Full per-file diff for the Gate dock / reader Diff tab (secret-redacted
// server-side; untracked files diff against /dev/null).
export async function loadFileDiff(
  path: string
): Promise<{ ok: boolean; path?: string; tracked?: boolean; truncated?: boolean; diff?: string[]; error?: string }> {
  try {
    const response = await fetch(await apiUrl(`/diff/file?path=${encodeURIComponent(path)}`), {
      headers: { accept: "application/json" }
    });
    return (await response.json()) as { ok: boolean; diff?: string[] };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "diff failed" };
  }
}

// Intake: copy an external file (local path or repo-relative) into data/raw/,
// secret-scanned and sandboxed server-side. The fix for the ~/Downloads dead-end.
export async function intakeCopy(
  sourcePath: string,
  context: string
): Promise<{ ok: boolean; path?: string; context?: string; filename?: string; error?: string; reason?: string }> {
  const response = await fetch(await apiUrl("/intake/copy"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source_path: sourcePath, context })
  });
  return (await response.json()) as { ok: boolean; path?: string };
}

// Run one honesty gate; the server persists a receipt so the gate turns green.
export async function runGate(gateId: string): Promise<GateRunResult> {
  const response = await fetch(await apiUrl("/gates/run"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ gate_id: gateId })
  });
  // The response carries redacted stdout/stderr — keep them: they are the only
  // failure detail that exists (receipts persist status alone).
  return (await response.json()) as GateRunResult;
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
  // A check that RAN and failed is a RESULT, not a transport error: the
  // operator returns 400 with a full `results[]` (per-step stdout/stderr).
  // Surface it so the UI can show WHICH gate failed — throwing here turned an
  // honest "operation_compile out of date" into a cryptic "action failed: 400".
  // Only a truly malformed response (no results array) is an exception.
  if (!response.ok && !Array.isArray(payload.results)) {
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

export async function composeSourceBrief(
  sourceId: string
): Promise<{ ok: boolean; spec?: import("../types").BriefSpec; pending?: number; error?: string }> {
  const response = await fetch(await apiUrl(`/sources/${encodeURIComponent(sourceId)}/brief`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({})
  });
  return (await response.json()) as { ok: boolean; spec?: import("../types").BriefSpec; pending?: number; error?: string };
}

export async function previewSourceOperation(
  sourceId: string,
  streamId: string,
  updates: Record<string, unknown>
): Promise<import("../types").SourceOperationPreview> {
  const response = await fetch(await apiUrl(`/sources/${encodeURIComponent(sourceId)}/operations/preview`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ stream_id: streamId, updates })
  });
  return (await response.json()) as import("../types").SourceOperationPreview;
}

export async function applySourceOperation(
  sourceId: string,
  streamId: string,
  updates: Record<string, unknown>,
  previewToken: string
): Promise<import("../types").SourceOperationReceipt> {
  const response = await fetch(await apiUrl(`/sources/${encodeURIComponent(sourceId)}/operations/apply`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ stream_id: streamId, updates, preview_token: previewToken })
  });
  return (await response.json()) as import("../types").SourceOperationReceipt;
}

export async function previewSourceGroups(
  groups: import("../types").SourceGroup[]
): Promise<import("../types").SourceGroupsOperationResult> {
  const response = await fetch(await apiUrl("/source-groups/preview"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ groups })
  });
  return (await response.json()) as import("../types").SourceGroupsOperationResult;
}

export async function applySourceGroups(
  groups: import("../types").SourceGroup[],
  previewToken: string
): Promise<import("../types").SourceGroupsOperationResult> {
  const response = await fetch(await apiUrl("/source-groups/apply"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ groups, preview_token: previewToken })
  });
  return (await response.json()) as import("../types").SourceGroupsOperationResult;
}

export async function listSourceOperationReceipts(
  sourceId: string,
  options: { signal?: AbortSignal } = {}
): Promise<import("../types").SourceOperationReceipt[]> {
  const response = await fetch(await apiUrl(`/sources/${encodeURIComponent(sourceId)}/operations`), {
    headers: { accept: "application/json" },
    signal: options.signal
  });
  if (!response.ok) return [];
  const result = (await response.json()) as { receipts?: import("../types").SourceOperationReceipt[] };
  return result.receipts ?? [];
}

export async function previewSourceRefresh(
  sourceId: string,
  streamId: string,
  rawPath = ""
): Promise<import("../types").SourceOperationPreview> {
  const response = await fetch(await apiUrl(`/sources/${encodeURIComponent(sourceId)}/operations/refresh-preview`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ stream_id: streamId, raw_path: rawPath })
  });
  return (await response.json()) as import("../types").SourceOperationPreview;
}

export async function runSourceRefresh(
  sourceId: string,
  streamId: string,
  rawPath: string,
  previewToken: string,
  selectedExternalIds: string[] = []
): Promise<import("../types").SourceOperationReceipt> {
  const response = await fetch(await apiUrl(`/sources/${encodeURIComponent(sourceId)}/operations/refresh-run`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      stream_id: streamId,
      raw_path: rawPath,
      preview_token: previewToken,
      selected_external_ids: selectedExternalIds
    })
  });
  return (await response.json()) as import("../types").SourceOperationReceipt;
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
