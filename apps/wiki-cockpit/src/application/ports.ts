import type { RuntimeConfig } from "../data/runtimeConfig";
import type { Route, WorldPatch, WorldRoute } from "../router";
import type {
  OperatorCommandRunResult,
  BriefRecord,
  BriefSpec,
  AgentCapabilities,
  CodexCapability,
  CodexJobRecord,
  GateRunResult,
  IngestionPlan,
  IngestionStepResult,
  PageContent,
  SnapshotBundle,
  SourceOperationPreview,
  SourceOperationReceipt,
  WorkflowRunResult
} from "../types";

export type SnapshotLoadOptions = { demo?: boolean; stage?: number | null; demoScenario?: string | null; signal?: AbortSignal };
export type OperatorReadOptions = { signal?: AbortSignal };
export type TemporalGraphReadOptions = { signal?: AbortSignal };
export type SnapshotLoadResult = { bundle: SnapshotBundle; source: string; runtime: RuntimeConfig };
export type ContentLoadOptions = {
  demo?: boolean;
  snapshotSource?: string;
  snapshotId?: string;
  integrity?: SnapshotBundle["manifest"]["integrity"];
  signal?: AbortSignal;
};
export type DiffLoadResult = {
  ok: boolean;
  path?: string;
  tracked?: boolean;
  truncated?: boolean;
  diff?: string[];
  error?: string;
};
export type IntakeCopyResult = {
  ok: boolean;
  path?: string;
  context?: string;
  filename?: string;
  error?: string;
  reason?: string;
};
export type SourceBriefResult = { ok: boolean; spec?: BriefSpec; pending?: number; error?: string };

// Concrete fetch/HTTP code implements this port at the composition root. UI
// surfaces receive the port (or a narrower member) and can be tested without a
// browser transport; they never import the operator client itself.
export interface OperatorPort {
  loadSnapshotBundle(options?: SnapshotLoadOptions): Promise<SnapshotLoadResult>;
  loadPageContent(pageId: string, options?: ContentLoadOptions): Promise<PageContent>;
  loadTemporalGraph(
    bundle: SnapshotBundle,
    options?: TemporalGraphReadOptions
  ): Promise<NonNullable<SnapshotBundle["temporalGraph"]>>;
  loadCodexCapability(runtime: RuntimeConfig, options?: OperatorReadOptions): Promise<CodexCapability>;
  loadAgentCapabilities(runtime: RuntimeConfig, options?: OperatorReadOptions): Promise<AgentCapabilities>;
  composeBrief(spec: BriefSpec): Promise<BriefRecord>;
  listBriefs(options?: OperatorReadOptions): Promise<BriefRecord[]>;
  getBrief(briefId: string, options?: OperatorReadOptions): Promise<BriefRecord | null>;
  saveBriefText(briefId: string, text: string): Promise<BriefRecord>;
  discardBrief(briefId: string): Promise<BriefRecord>;
  spawnCodexJob(
    briefId: string,
    briefSha: string,
    options?: { dryRun?: boolean; force?: boolean; parentJobId?: string; agent?: "codex" | "claude" }
  ): Promise<CodexJobRecord>;
  listCodexJobs(options?: OperatorReadOptions): Promise<CodexJobRecord[]>;
  streamCodexLog(jobId: string, options?: OperatorReadOptions): Promise<string>;
  returnCodexJob(jobId: string, feedback: string): Promise<BriefRecord>;
  cancelCodexJob(jobId: string): Promise<CodexJobRecord | null>;
  loadFileDiff(path: string, options?: OperatorReadOptions): Promise<DiffLoadResult>;
  intakeCopy(sourcePath: string, context: string): Promise<IntakeCopyResult>;
  runGate(gateId: string): Promise<GateRunResult>;
  runOperatorCommand(actionId: string, dryRun?: boolean): Promise<OperatorCommandRunResult>;
  runGitWorkflow(
    operation: string,
    payload?: Record<string, unknown>,
    dryRun?: boolean
  ): Promise<WorkflowRunResult>;
  composeSourceBrief(sourceId: string): Promise<SourceBriefResult>;
  previewSourceOperation(sourceId: string, streamId: string, updates: Record<string, unknown>): Promise<SourceOperationPreview>;
  applySourceOperation(
    sourceId: string,
    streamId: string,
    updates: Record<string, unknown>,
    previewToken: string
  ): Promise<SourceOperationReceipt>;
  listSourceOperationReceipts(sourceId: string, options?: OperatorReadOptions): Promise<SourceOperationReceipt[]>;
  previewSourceRefresh(sourceId: string, streamId: string, rawPath?: string): Promise<SourceOperationPreview>;
  runSourceRefresh(
    sourceId: string,
    streamId: string,
    rawPath: string,
    previewToken: string
  ): Promise<SourceOperationReceipt>;
  buildIngestionPlan(source: string, context?: string): Promise<IngestionPlan>;
  runIngestionStep(source: string, context: string, stepId: string, dryRun?: boolean): Promise<IngestionStepResult>;
}

export type NavigationIntent =
  | { type: "navigate"; target: Route | string; replace?: boolean }
  | { type: "patch-world"; route: WorldRoute; patch: WorldPatch; replace?: boolean }
  | { type: "retreat-world"; route: WorldRoute; replace?: boolean }
  | { type: "history-back" };

// Navigation writes are commands, never helper calls from components. Pure
// URL grammar helpers live on the same injected boundary so renderer code does
// not become coupled to the compatibility router module.
export interface NavigationPort {
  subscribe(listener: () => void): () => void;
  getSnapshot(): string;
  getServerSnapshot(): string;
  attachLinkInterceptor(): () => void;
  parseUrl(url: string): Route;
  toWorld(route: Route): WorldRoute;
  href(route: Route): string;
  patch(route: WorldRoute, patch: WorldPatch): WorldRoute;
  hrefForPatch(route: WorldRoute, patch: WorldPatch): string;
  dispatch(intent: NavigationIntent): void;
}

export type ApplicationPorts = {
  navigation: NavigationPort;
  operator: OperatorPort;
};
