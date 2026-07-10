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
import { fetchOperatorHealth, operatorPost } from "../world/clients/operatorClient";

const CORE_FILES = {
  operations: "operations.json",
  graph: "graph.json",
  pages: "pages.json",
  // Legacy payload name retained through the v8 compatibility window. The
  // typed records are OperatorCommandCard; domain actions live in work_items.
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

const V2_FILES = {
  operatorCommands: "operator_commands.json",
  workItems: "work_items.json",
  regionGroups: "region_groups.json",
  sourceLifecycle: "source_lifecycle.json",
  snapshotWarnings: "snapshot_warnings.json"
} as const;

const SUPPORTED_SNAPSHOT_VERSIONS = new Set(["wiki_web_snapshot.v1", "wiki_web_snapshot.v2"]);
const REQUIRED_V2_PAYLOADS = new Set([
  ...Object.values(CORE_FILES),
  ...Object.values(V2_FILES),
  "score.json",
  "source_entities.json",
  "templates.json",
  "blocks.json",
  "block_stacks.json"
]);

export type SnapshotCompatibility = NonNullable<SnapshotBundle["manifest"]["compatibility"]>;
export type SnapshotLoadErrorCode = "unsupported" | "partial" | "integrity" | "torn";

export class SnapshotLoadError extends Error {
  constructor(public readonly code: SnapshotLoadErrorCode, message: string) {
    super(message);
    this.name = "SnapshotLoadError";
  }
}

export function classifySnapshotManifest(manifest: SnapshotBundle["manifest"]): SnapshotCompatibility {
  if (!SUPPORTED_SNAPSHOT_VERSIONS.has(manifest.schema_version)) {
    throw new SnapshotLoadError("unsupported", `Unsupported snapshot version: ${manifest.schema_version || "<empty>"}`);
  }
  if (manifest.schema_version === "wiki_web_snapshot.v1") {
    return {
      state: "stale_version",
      warnings: ["Previous snapshot version loaded in compatibility mode; regenerate with wiki_web_snapshot.v2."]
    };
  }
  return { state: "current", warnings: [] };
}

export const SAMPLE_BASE = "/sample-snapshot";

export const DEMO_SCENARIO_BASES = Object.freeze({
  normal_operations: SAMPLE_BASE,
  dense_stress: `${SAMPLE_BASE}/scenarios/dense_stress`
} as const);

export type DemoScenarioId = keyof typeof DEMO_SCENARIO_BASES;

function demoModeRequested(): boolean {
  if (typeof window === "undefined") return false;
  return window.location.pathname.startsWith("/demo") || new URLSearchParams(window.location.search).get("demo") === "1";
}

export function demoSnapshotBase(
  options: { stage?: number | null; search?: string; scenario?: string | null } = {}
): string {
  if (options.stage != null) return `${SAMPLE_BASE}/stages/${options.stage}`;
  const search = options.search ?? (typeof window === "undefined" ? "" : window.location.search);
  const requested = options.scenario || new URLSearchParams(search).get("demo_scenario");
  if (requested && Object.prototype.hasOwnProperty.call(DEMO_SCENARIO_BASES, requested)) {
    return DEMO_SCENARIO_BASES[requested as DemoScenarioId];
  }
  return DEMO_SCENARIO_BASES.normal_operations;
}

async function fetchJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { headers: { accept: "application/json" }, signal });
  const contentType = response.headers.get("content-type") || "";
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  if (!contentType.toLowerCase().includes("application/json")) {
    throw new Error(`${url} returned ${contentType || "unknown content type"} instead of application/json`);
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

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0);
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

async function sha256(value: unknown): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new Error("Snapshot integrity verification is unavailable in this browser");
  const digest = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonicalJson(value)));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function validateSnapshotEnvelope(
  manifest: SnapshotBundle["manifest"],
  payloads: Record<string, unknown>
): Promise<void> {
  classifySnapshotManifest(manifest);
  if (manifest.schema_version !== "wiki_web_snapshot.v2") return;
  const emptyCompat = manifest.capabilities?.includes("empty_world_compat") ?? false;
  if (!manifest.snapshot_id || (!manifest.root_page_id && !emptyCompat) || !manifest.bundle_hash || !manifest.integrity) {
    throw new SnapshotLoadError("partial", "Snapshot v2 envelope is incomplete");
  }
  const missingRequired = [...REQUIRED_V2_PAYLOADS].filter((name) => !(name in manifest.integrity!));
  if (missingRequired.length) {
    throw new SnapshotLoadError("partial", `Snapshot ${manifest.snapshot_id} is partial; missing integrity entries: ${missingRequired.join(", ")}`);
  }
  for (const [name, expected] of Object.entries(manifest.integrity)) {
    // Content sidecars are integrity-checked when the reader fetches them; the
    // initial world load must not eagerly download every page body.
    if (name.startsWith("content/")) continue;
    if (!(name in payloads)) throw new SnapshotLoadError("partial", `Snapshot ${manifest.snapshot_id} is missing required payload ${name}`);
    const actual = await sha256(payloads[name]);
    if (actual !== expected.sha256) throw new SnapshotLoadError("integrity", `Snapshot ${manifest.snapshot_id} failed integrity for ${name}`);
  }
  const pages = (payloads["pages.json"] as SnapshotBundle["pages"] | undefined)?.pages ?? [];
  const ids = new Set<string>();
  for (const page of pages) {
    if (!page.id || ids.has(page.id)) throw new SnapshotLoadError("integrity", `Snapshot ${manifest.snapshot_id} contains a duplicate or empty page id: ${page.id}`);
    ids.add(page.id);
  }
  if (!emptyCompat && !ids.has(manifest.root_page_id!)) throw new SnapshotLoadError("integrity", `Snapshot ${manifest.snapshot_id} root page is missing from pages.json`);
  if (manifest.contract_errors?.length) throw new SnapshotLoadError("integrity", `Snapshot ${manifest.snapshot_id} contract errors: ${manifest.contract_errors.join("; ")}`);
}

async function loadFromBase(base: string, signal?: AbortSignal): Promise<SnapshotBundle> {
  const manifest = await fetchJson<SnapshotBundle["manifest"]>(`${base}/manifest.json`, signal);
  manifest.compatibility = classifySnapshotManifest(manifest);
  const coreEntries = await Promise.all(
    Object.entries(CORE_FILES).map(async ([key, file]) => [key, await fetchJson(`${base}/${file}`, signal), file] as const)
  );
  const v2Entries = manifest.schema_version === "wiki_web_snapshot.v2"
    ? await Promise.all(Object.entries(V2_FILES).map(async ([key, file]) => [key, await fetchJson(`${base}/${file}`, signal), file] as const))
    : [
        ["operatorCommands", { schema_version: "wiki_operator_commands.v1", operator_commands: [] }, "operator_commands.json"],
        ["workItems", { schema_version: "wiki_work_items.v1", actions: [] }, "work_items.json"],
        ["regionGroups", { schema_version: "wiki_region_groups.v2", groups: [] }, "region_groups.json"],
        ["sourceLifecycle", { schema_version: "wiki_source_lifecycle.v2", sources: [] }, "source_lifecycle.json"],
        ["snapshotWarnings", { schema_version: "wiki_snapshot_warnings.v1", warnings: [] }, "snapshot_warnings.json"]
      ] as const;
  const entries = [...coreEntries, ...v2Entries];
  const bundle = Object.fromEntries([["manifest", manifest], ...entries.map(([key, value]) => [key, value])]) as SnapshotBundle;
  const payloads: Record<string, unknown> = Object.fromEntries(entries.map(([, value, file]) => [file, value]));
  // Optional read models keep old snapshots loadable.
  bundle.score = await fetchJson(`${base}/score.json`, signal).catch(() => EMPTY_SCORE) as SnapshotBundle["score"];
  payloads["score.json"] = bundle.score;
  bundle.sourceEntities = await fetchJson(`${base}/source_entities.json`, signal).catch(
    () => ({ schema_version: "wiki_web_source_entities.v1", sources: [] })
  ) as SnapshotBundle["sourceEntities"];
  payloads["source_entities.json"] = bundle.sourceEntities;
  bundle.templates = await fetchJson(`${base}/templates.json`, signal).catch(
    () => ({ schema_version: "wiki_templates.v1", facets_order: [], types: {} })
  ) as SnapshotBundle["templates"];
  payloads["templates.json"] = bundle.templates;
  // v2 blocks — optional, so pre-v2 snapshots keep loading.
  bundle.blocks = await fetchJson(`${base}/blocks.json`, signal).catch(
    () => ({ schema_version: "wiki_web_blocks.v1", blocks: {}, vocabulary: {}, warnings: [] })
  ) as SnapshotBundle["blocks"];
  payloads["blocks.json"] = bundle.blocks;
  bundle.blockStacks = await fetchJson(`${base}/block_stacks.json`, signal).catch(
    () => ({ schema_version: "wiki_web_block_stacks.v1", anchors: {} })
  ) as SnapshotBundle["blockStacks"];
  payloads["block_stacks.json"] = bundle.blockStacks;
  await validateSnapshotEnvelope(bundle.manifest, payloads);
  const confirmation = await fetchJson<SnapshotBundle["manifest"]>(`${base}/manifest.json`, signal);
  if (bundle.manifest.snapshot_id && confirmation.snapshot_id !== bundle.manifest.snapshot_id) {
    throw new SnapshotLoadError("torn", `Snapshot changed while loading (${bundle.manifest.snapshot_id} -> ${confirmation.snapshot_id || "unknown"})`);
  }
  return bundle;
}

export async function loadSnapshotBundle(
  options: { demo?: boolean; stage?: number | null; demoScenario?: string | null; signal?: AbortSignal } = {}
): Promise<{ bundle: SnapshotBundle; source: string; runtime: RuntimeConfig }> {
  // Demo is an in-memory bundle switch: synthetic ids never resolve against
  // the real snapshot, and switching universes never reloads the document.
  if (options.demo ?? demoModeRequested()) {
    // Load the runtime config anyway so presentation overrides still apply to demo data.
    const demoRuntime = await loadRuntimeConfig();
    // Genesis: each tutorial stage is a REAL pre-built snapshot (stages/<k>/) —
    // the world materializes because the data changes, never by UI simulation.
    // Scenario routing is deliberately an allowlist. A query value can select
    // a committed public fixture, never become a path fragment.
    const base = demoSnapshotBase({ stage: options.stage, scenario: options.demoScenario });
    return {
      bundle: await loadFromBase(base, options.signal),
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
    { base: apiBase, sampleFallback: false }
  ].filter((candidate): candidate is { base: string; sampleFallback: boolean } => Boolean(candidate.base));
  let lastError: unknown = null;
  const seen = new Set<string>();
  for (const { base, sampleFallback } of candidates) {
    if (seen.has(`${base}:${sampleFallback ? "fallback" : "configured"}`)) continue;
    seen.add(`${base}:${sampleFallback ? "fallback" : "configured"}`);
    try {
      const bundle = await loadFromBase(base, options.signal);
      return { bundle, source: base, runtime };
    } catch (error) {
      lastError = error;
    }
  }
  const detail = lastError instanceof Error ? lastError.message : "snapshot unavailable";
  throw new Error(
    `Real cockpit snapshot unavailable. Start the operator backend and Vite API proxy; sample fallback is blocked outside /demo. Last error: ${detail}`
  );
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
  options: {
    demo?: boolean;
    snapshotSource?: string;
    snapshotId?: string;
    integrity?: SnapshotBundle["manifest"]["integrity"];
    signal?: AbortSignal;
  } = {}
): Promise<PageContent> {
  const attempts: (() => Promise<PageContent>)[] = [];
  if (options.demo) {
    attempts.push(() => fetchJson<PageContent>(`${options.snapshotSource || SAMPLE_BASE}/content/${sidecarName(pageId)}`, options.signal));
  } else {
    attempts.push(async () => {
      const response = await fetch(await apiUrl(`/pages/${encodeURIComponent(pageId)}/content`), {
        headers: { accept: "application/json" },
        signal: options.signal
      });
      const payload = (await response.json()) as PageContent;
      if (!response.ok && !payload.error) throw new Error(`content failed: ${response.status}`);
      return payload;
    });
    const base = options.snapshotSource;
    if (base && !base.endsWith("/api/snapshot")) {
      attempts.push(() => fetchJson<PageContent>(`${base}/content/${sidecarName(pageId)}`, options.signal));
    }
  }
  let lastError: unknown = null;
  for (const attempt of attempts) {
    try {
      const payload = await attempt();
      if (payload && payload.ok) {
        if (options.snapshotId && payload.snapshot_id && payload.snapshot_id !== options.snapshotId) {
          throw new Error(`Content revision mismatch (${payload.snapshot_id} != ${options.snapshotId})`);
        }
        const sidecarPath = `content/${sidecarName(pageId)}`;
        const expected = options.integrity?.[sidecarPath]?.sha256;
        if (options.demo && options.integrity && !expected) {
          throw new Error(`Content sidecar is absent from snapshot integrity: ${sidecarPath}`);
        }
        if (expected && (await sha256(payload)) !== expected) {
          throw new Error(`Content sidecar failed integrity: ${sidecarPath}`);
        }
        return payload;
      }
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
  return fetchOperatorHealth();
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

// Work briefs — the agent-neutral compose/edit/save/discard surface. Compose
// is deterministic and zero-token server-side; it also persists a draft so the
// brief is inspectable and (Phase 2) executable by its stable id + sha.
export async function composeBrief(spec: BriefSpec): Promise<BriefRecord> {
  const response = await operatorPost("/briefs", { spec });
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
  const response = await operatorPost(`/briefs/${encodeURIComponent(briefId)}`, { text });
  const result = (await response.json()) as BriefRecord;
  // A refused save (e.g. non-draft) comes back ok:false WITH a brief_id — fail
  // closed so callers never treat a rejection as a saved record.
  if (!response.ok || result.ok === false) {
    throw new Error(result.error || `brief save failed: ${response.status}`);
  }
  return result;
}

export async function discardBrief(briefId: string): Promise<BriefRecord> {
  const response = await operatorPost(`/briefs/${encodeURIComponent(briefId)}/discard`, {});
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
  options: { dryRun?: boolean; force?: boolean; parentJobId?: string } = {}
): Promise<CodexJobRecord> {
  const response = await operatorPost("/codex/jobs", {
      brief_id: briefId,
      brief_sha: briefSha,
      dry_run: options.dryRun ?? false,
      force: options.force ?? false,
      parent_job_id: options.parentJobId
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
  const response = await operatorPost(`/codex/jobs/${encodeURIComponent(jobId)}/return`, { feedback });
  const result = (await response.json()) as BriefRecord;
  if (!response.ok && !result.brief_id) {
    throw new Error(result.error || `return failed: ${response.status}`);
  }
  return result;
}

export async function cancelCodexJob(jobId: string): Promise<CodexJobRecord | null> {
  const response = await operatorPost(`/codex/jobs/${encodeURIComponent(jobId)}/cancel`, {});
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
  const response = await operatorPost("/intake/copy", { source_path: sourcePath, context });
  return (await response.json()) as { ok: boolean; path?: string };
}

// Run one honesty gate; the server persists a receipt so the gate turns green.
export async function runGate(gateId: string): Promise<GateRunResult> {
  const response = await operatorPost("/gates/run", { gate_id: gateId });
  // The response carries redacted stdout/stderr — keep them: they are the only
  // failure detail that exists (receipts persist status alone).
  return (await response.json()) as GateRunResult;
}

export async function runOperatorCommand(
  actionId: string,
  dryRun?: boolean
): Promise<import("../types").OperatorCommandRunResult> {
  const response = await operatorPost("/actions/run", { action_id: actionId, dry_run: dryRun });
  const payload = (await response.json()) as import("../types").OperatorCommandRunResult;
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
  const response = await operatorPost("/git/workflow", { ...payload, operation, dry_run: dryRun });
  const result = (await response.json()) as WorkflowRunResult;
  if (!response.ok && !result.operation) {
    throw new Error(result.error || `workflow failed: ${response.status}`);
  }
  return result;
}

export async function composeSourceBrief(
  sourceId: string
): Promise<{ ok: boolean; spec?: import("../types").BriefSpec; pending?: number; error?: string }> {
  const response = await operatorPost(`/sources/${encodeURIComponent(sourceId)}/brief`, {});
  return (await response.json()) as { ok: boolean; spec?: import("../types").BriefSpec; pending?: number; error?: string };
}

export async function triageSource(source: string, context?: string): Promise<SourceTriageResult> {
  const response = await operatorPost("/sources/triage", { source, context });
  const result = (await response.json()) as SourceTriageResult;
  if (!response.ok && !result.risk_flags && !result.error) {
    throw new Error(`source triage failed: ${response.status}`);
  }
  return result;
}

export async function buildIngestionPlan(source: string, context?: string): Promise<IngestionPlan> {
  const response = await operatorPost("/ingestion/plan", { source, context });
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
  const response = await operatorPost("/ingestion/run", { source, context, step_id: stepId, dry_run: dryRun });
  const result = (await response.json()) as IngestionStepResult;
  if (!response.ok && !result.step_id) {
    throw new Error(result.error || `ingestion step failed: ${response.status}`);
  }
  return result;
}
