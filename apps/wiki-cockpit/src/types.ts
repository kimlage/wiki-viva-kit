export type FreshnessState = "fresh" | "stale" | "unknown";

export type GitFile = {
  path: string;
  status: string;
  staged: boolean;
  unstaged: boolean;
  known_generated: boolean;
  suggested_stage: boolean;
};

export type GitState = {
  available: boolean;
  default_branch: string;
  current_branch: string;
  branch_prefix: string;
  worktree: {
    clean: boolean;
    changed_files: GitFile[];
  };
  upstream: {
    remote: string;
    ahead: number;
    behind: number;
    name: string;
    last_fetch_at: string | null;
  };
  proposal: {
    is_proposal_branch: boolean;
    theme: string;
    draft_pr_url: string | null;
    human_gate_state: string;
  };
};

export type TimelineEvent = {
  id: string;
  kind: string;
  timestamp: string;
  label: string;
  context: string;
  path: string;
  status: string;
  weight: number;
  commit: string;
};

export type DiffFile = {
  path: string;
  status: string;
  category: string;
  change_sources: string[];
  additions: number;
  deletions: number;
  known_generated: boolean;
  staged: boolean;
  unstaged: boolean;
  risk_hints: string[];
  preview: string[];
};

export type PageRecord = {
  id: string;
  path: string;
  title: string;
  page_type: string;
  context: string;
  visibility: string;
  status: string;
  updated_at: string;
  stale_after_days: string;
  freshness_state: FreshnessState;
  approved_state: string;
  risk_flags: string[];
  source_refs: string[];
  moc_parent: string;
  summary: string;
  summary_truncated?: boolean;
  moc_children_count?: number;
};

export type ResolvedLink =
  | ({ kind: "page"; text: string; href: string } & PageBrief)
  | { kind: "external"; text: string; href: string; domain: string }
  | { kind: "missing"; text: string; href: string; target: string };

export type PageBrief = {
  page_id: string;
  path: string;
  title: string;
  context: string;
  page_type: string;
  freshness_state: FreshnessState;
  approved_state: string;
};

export type PageBacklink = PageBrief & { relation: string };

export type ResolvedSourceRef =
  | ({ ref: string; resolved: true } & PageBrief)
  | { ref: string; resolved: false };

export type PageContent = {
  ok: boolean;
  error?: string;
  schema_version?: string;
  page?: PageBrief & {
    summary: string;
    summary_truncated: boolean;
    updated_at: string;
    moc_parent: string;
  };
  frontmatter?: Record<string, unknown>;
  body?: string;
  resolved_links?: ResolvedLink[];
  backlinks?: PageBacklink[];
  source_refs?: ResolvedSourceRef[];
};

export type GraphNode = {
  id: string;
  path: string;
  title: string;
  page_type: string;
  context: string;
  freshness_state: FreshnessState;
  approved_state: string;
  risk_flags: string[];
  updated_at?: string;
  stale_after_days?: string;
  metrics: {
    inbound_links: number;
    outbound_links: number;
    source_ref_count: number;
  };
};

export type GraphEdge = {
  source: string;
  target: string;
  type: string;
  status: string;
  weight: number;
};

export type ActionCommand = {
  label: string;
  argv: string[];
  writes: boolean;
};

export type ActionCard = {
  id: string;
  kind: string;
  title: string;
  human_reason: string;
  risk_level: "read" | "derive" | "proposal_write" | "external_write" | "destructive";
  default_dry_run: boolean;
  commands: ActionCommand[];
};

export type GateRecord = {
  id: string;
  status: string;
  argv: string[];
  finished_at?: string | null;
};

// The transient response of POST /api/gates/run — unlike the persisted receipt
// it carries the redacted stdout/stderr, which is what makes per-check
// diagnosis (and "fix with Codex") possible.
export type GateRunResult = {
  ok: boolean;
  gate_id?: string;
  returncode?: number | null;
  stdout?: string;
  stderr?: string;
  finished_at?: string;
  error?: string;
};

export type SnapshotBundle = {
  manifest: {
    schema_version: string;
    generated_at: string;
    mode: string;
    content_sidecars?: boolean;
    source_commit: string | null;
    repo: {
      repo_id: string;
      language: string;
      memory_root: string;
      default_context: string;
      karma_enabled: boolean;
      default_branch: string;
      branch_prefix: string;
    };
    files: string[];
  };
  operations: {
    title: string;
    path: string;
    updated_at: string;
    freshness_state: FreshnessState;
    sections: { title: string; body: string; bullets: string[] }[];
  };
  graph: {
    nodes: GraphNode[];
    edges: GraphEdge[];
  };
  pages: {
    pages: PageRecord[];
  };
  actions: {
    actions: ActionCard[];
  };
  freshness: {
    summary: Record<FreshnessState, number>;
    by_context: Record<string, Record<FreshnessState, number>>;
    stale_pages: { path: string; title: string; context: string }[];
  };
  gates: {
    status: string;
    gates: GateRecord[];
  };
  git: GitState;
  timeline: {
    schema_version: string;
    repo_id: string;
    generated_at: string;
    summary: {
      event_count: number;
      first_at: string;
      last_at: string;
      by_kind: Record<string, number>;
      by_context: Record<string, number>;
    };
    bands: Record<string, number>;
    events: TimelineEvent[];
  };
  diff: {
    schema_version: string;
    repo_id: string;
    available: boolean;
    compare: {
      default_branch: string;
      base_ref: string;
      merge_base: string;
      head_commit: string;
      current_branch: string;
    };
    summary: {
      file_count: number;
      branch_file_count: number;
      working_tree_file_count: number;
      insertions: number;
      deletions: number;
      status_counts: Record<string, number>;
      privacy_review_required: boolean;
    };
    commands: string[][];
    files: DiffFile[];
  };
  sources: {
    sources: PageRecord[];
  };
  decisions: {
    decisions: PageRecord[];
  };
  ingestion: Record<string, unknown>;
  quality: {
    summary?: Record<string, number | string | Record<string, number>>;
    quality_flags?: Record<string, unknown[]>;
  };
  commands: {
    commands: ActionCommand[];
  };
  score: ScorePayload;
  sourceEntities: SourceEntitiesPayload;
  templates: TemplatesPayload;
  blocks: BlocksPayload;
  blockStacks: BlockStacksPayload;
};

// --- Modular template blocks (v2) ---
export type BlockDefinition = {
  kind: string;
  family?: string;
  title?: string;
  summary?: string;
  origin?: string;
  surface?: string;
  contract_ref?: string;
  perspectives?: Record<string, string>;
  anchors?: string[];
  scope?: { default_mode?: string; allowed_modes?: string[] };
  config_schema?: Record<string, unknown>;
  contributes?: Record<string, unknown>;
  scene_profile?: { layout?: string | null; overlays?: string[]; fallback?: string };
  gates?: { warnings?: string[]; errors?: string[] };
  skills?: { human?: string[]; agent?: string[] };
};

export type BlockPackage = {
  title: string;
  summary: string;
  blocks: string[];
};

export type BlocksPayload = {
  schema_version: string;
  vocabulary?: Record<string, unknown>;
  blocks: Record<string, BlockDefinition>;
  packages?: Record<string, BlockPackage>;
  warnings?: string[];
  error?: string;
};

export type ResolvedBlock = {
  id: string;
  origin: string;
  scope: string;
  kind: string;
  config: Record<string, unknown>;
  known: boolean;
};

export type BlockInterface = {
  views: { available: string[]; default: string };
  missions: { active?: boolean; providers: string[]; weather_contrib: boolean; quiet: boolean };
  create: {
    catalog: string[];
    arrangement: string;
    obligations_first: boolean;
    obligations: { rel: string; page_type: string; slug: string }[];
    disabled_reason: string;
  };
  intake: { forms: string[] };
  score: { loops: string[]; no_leaderboard: boolean };
  has_quadrants: boolean;
  has_relations: boolean;
};

export type BlockIdentity = {
  landmark: string;
  motif: string;
  ambient: string;
  horizon_label: string;
  horizon_text: string;
  context: string;
};

export type RelationDue = { person: string; title: string; relationship_kind: string; last_interaction: string; overdue_days: number };
export type RelationUpcoming = { person: string; title: string; kind: string; in_days: number };
export type RelationCommitment = { person: string; title: string; ref: string; days_left: number };

export type QuadrantProjection = {
  center: string;
  page: string;
  quadrant: string;
  facet: string;
  sub_lens: string;
  basis: string;
  subject_center: string;
  through_center: string;
  local_quadrant_under_subject: string;
  local_facet_under_subject: string;
  local_sub_lens_under_subject: string;
  reason: string;
};

export type BlockDerived = {
  missions: { provider: string; [key: string]: unknown }[];
  warnings: string[];
  quadrant_assignments?: Record<string, string[]>;
  quadrant_projections?: Record<string, QuadrantProjection[]>;
  quadrant_sub_lens?: Record<string, Record<string, string[]>>;
  empty_quadrants?: string[];
  relations?: { due: RelationDue[]; upcoming_dates: RelationUpcoming[]; open_commitments: RelationCommitment[] };
  missing_subpages?: { rel: string; page_type: string; slug: string }[];
};

export type AnchorRecord = {
  stack: ResolvedBlock[];
  interface: BlockInterface;
  identity: BlockIdentity;
  derived: BlockDerived;
};

export type AnchorTreeNode = {
  id: string;
  path: string;
  title: string;
  page_type: string;
  parent: string;
  children: string[];
};

export type BlockStacksPayload = {
  schema_version: string;
  anchor_tree?: { roots: string[]; nodes: Record<string, AnchorTreeNode> };
  anchors: Record<string, AnchorRecord>;
  error?: string;
};

// --- Source entities (Pillar A) ---
export type SourceStream = {
  id: string;
  label: string;
  selected: boolean;
  privacy: string;
  target_pages: string[];
  skip_reason: string;
  cursor_age_days: number | null;
  freshness_basis?: "stream_cursor" | "versioned_stream_receipt" | "source_receipt" | "versioned_source_sync" | "not_selected";
  cadence_days: number;
  breached: boolean;
  filters?: Record<string, unknown>;
};

export type SourceEventClosure = {
  consolidated_into: string[];
  reviewed_no_change: boolean;
  no_change: string[];
  gate_state: string;
};

export type SourceLifecycleProjection = {
  derived_from_legacy?: boolean;
  state: string;
  freshness_state: string;
  last_attempt_state: string;
  pipeline_stage: string;
  pipeline_stage_timestamps: Record<string, string>;
  adoption_state: string;
  last_sync_success_at: string;
  last_ingested_at: string;
  last_attempt_at: string;
  emitted_page_ids: string[];
  emitted_action_ids: string[];
  proposal_ids: string[];
  raw_artifact_count: number;
  secret_safe_log_refs: string[];
  reviewed_no_change_receipt: string;
  accepted_ref: string;
  blocked_reason: string;
  authoring_error_codes: string[];
};

export type SourceEntity = {
  source_id: string;
  path: string;
  title: string;
  context: string;
  platform: string;
  locator: string;
  source_kind?: "item" | "collection" | "account" | "endpoint" | "repository" | "";
  // Optional source-owned brand identity. The backend only projects local
  // /source-icons assets; older snapshots omit this field and keep the
  // platform-aware semantic fallback.
  visual_identity?: {
    key: string;
    label: string;
    asset_path: string;
    background: "transparent" | "light" | "dark";
  };
  owner: string;
  stewards: { ref?: string; kind?: string; via?: string }[];
  config_ref: string;
  updated_at: string;
  sync: {
    last_run_at: string;
    last_status: string;
    last_event_ref: string;
    derived_from_event?: boolean;
    streams_fresh: number;
    streams_total: number;
    event_closure?: SourceEventClosure;
  };
  lifecycle?: SourceLifecycleProjection;
  recipe_ok: boolean;
  recipe_errors: string[];
  how_to_export: string;
  update_route?: {
    mode: "script" | "deterministic_connector" | "agent_connector" | "manual_export";
    mcp_hint: string;
    runnable: boolean;
    requires_agent: boolean;
  };
  pipelines: { kind: string; cadence_days: number }[];
  streams: SourceStream[];
  pending_streams: number;
  // Rich config (recipe v2): the auth POINTER (never a value), the schedule, and
  // days until the next scheduled sync (negative = overdue).
  auth?: { method: string; ref: string; scopes: string[]; note: string } | null;
  schedule?: { mode: string; cadence_days: number; cron_hint: string } | null;
  next_due_days?: number | null;
};

export type SourceEntitiesPayload = {
  schema_version: string;
  sources: SourceEntity[];
  summary?: { total: number; with_recipe: number; pending: number };
  error?: string;
};

export type SourceOperationChange = { field: string; before: unknown; after: unknown };
export type SourceInventoryRecord = {
  external_id: string;
  label: string;
  filters: Record<string, unknown>;
  status: "new" | "changed" | "enriched" | "unchanged";
  stream_id?: string;
  before?: unknown;
};
export type SourceInventoryDiff = {
  counts: { new: number; changed: number; enriched: number; unchanged: number };
  records: SourceInventoryRecord[];
  fingerprint: string;
};
export type SourceOperationPreview = {
  ok: boolean;
  error?: string;
  schema_version?: string;
  source_id?: string;
  stream_id?: string;
  preview_token?: string;
  config_ref?: string;
  changes?: SourceOperationChange[];
  updates?: Record<string, unknown>;
  raw_inventory?: Record<string, unknown>;
  discovery?: SourceInventoryDiff | null;
  execution?: {
    mode: "script" | "deterministic_connector" | "agent_connector" | "manual_export";
    argv: string[];
    mcp_hint: string;
    how_to_export: string;
    runnable?: boolean;
    requires_agent?: boolean;
  };
  steps?: { id: string; label: string; status: string }[];
};
export type SourceOperationReceipt = {
  ok?: boolean;
  error?: string;
  operation_id: string;
  recorded_at: string;
  source_id: string;
  stream_id: string;
  status: string;
  changes: SourceOperationChange[];
  receipt_path?: string;
  changed_files?: string[];
  source?: SourceEntity;
  stdout?: string;
  stderr?: string;
  returncode?: number | null;
  discovery?: SourceInventoryDiff;
  selected_external_ids?: string[];
  summary?: { new: number; changed: number; enriched: number; unchanged: number; applied: number };
};

// --- Declarative template registry (Pillar B) ---
export type TemplateSpec = {
  page_type: string;
  extends: string | null;
  body_template: string;
  pinned_fields: string[];
  facets: Record<string, string[]>;
  view: { center?: string; panels?: { kind: string; from?: string; label?: string; columns?: string[] }[]; badges?: string[] };
  controls: { kind: string; id?: string; rel?: string }[];
  scene: { shape?: string; emphasis?: string };
  // Palette honesty (v2): false for generated/system/rite-owned types — the
  // create surfaces must never offer them. Absent (old snapshots) = true.
  creatable?: boolean;
};

export type TemplatesPayload = {
  schema_version: string;
  facets_order: string[];
  types: Record<string, TemplateSpec>;
  error?: string;
};

export type ScoreBadge = { id: string; en: string; pt: string; criterion_en?: string; criterion_pt?: string };

export type ScoreVitality = {
  context: string;
  indicadores: Record<string, number>;
  score_aggregado: number;
  eventos: number;
  participantes: string[];
  participacao_distribuida: number;
  indice_vitalidade: number;
};

export type ScorePayload = {
  schema_version: string;
  enabled: boolean;
  event_count: number;
  total: number;
  level: string | null;
  level_labels: Record<string, string>;
  by_dimension: Record<string, number>;
  badges: ScoreBadge[];
  vitality: Record<string, ScoreVitality>;
  error?: string;
};

export type CommandResultEntry = {
  argv: string[];
  ok: boolean;
  returncode: number | null;
  stdout: string;
  stderr: string;
  dry_run: boolean;
};

export type ActionRunResult = {
  ok: boolean;
  action_id: string;
  dry_run: boolean;
  error?: string;
  results: CommandResultEntry[];
};

export type WorkflowRunResult = {
  ok: boolean;
  operation: string;
  dry_run: boolean;
  summary: string;
  error?: string;
  data: Record<string, unknown>;
  results: CommandResultEntry[];
};

// Live Codex capability from GET /api/codex/capability (mirrors
// wiki_core.web.codex_probe). `usable` is the single flag the UI gates the
// launch CTA on; `reason` is a ready-to-show plain-language explanation.
export type CodexCapability = {
  schema_version?: string;
  enabled: boolean;
  installed: boolean;
  runnable: boolean;
  authed: boolean;
  auth_mode: string | null;
  version: string | null;
  usable: boolean;
  reason: string;
  connectors?: string[];
  // The local operator process predates the code on disk (its /api/health lacks
  // the codex capability). This is rung 0 of the diagnostics ladder: restart it.
  operator_outdated?: boolean;
};

export const CODEX_UNAVAILABLE: CodexCapability = {
  enabled: true,
  installed: false,
  runnable: false,
  authed: false,
  auth_mode: null,
  version: null,
  usable: false,
  reason: "",
  operator_outdated: false
};

// The operator handshake from GET /api/health — used to detect a stale operator.
export type OperatorHealth = {
  ok: boolean;
  repo?: string;
  server_version?: string;
  schema_capabilities?: string[];
  codex?: CodexCapability;
  claude?: CodexCapability;
};

export type AgentCapabilities = {
  codex: CodexCapability;
  claude: CodexCapability;
};

// A work-brief spec: what the operator points the composer at. Mirrors
// wiki_core.web.briefs.normalize_spec.
export type BriefSpec = {
  agent?: string;
  mission_kind?: string | null;
  grounding: {
    page_ids?: string[];
    source?: { path: string; context?: string | null } | null;
    attach_context_package?: boolean;
    state_report?: { scope: "missions" | "quality" | "audit"; context?: string | null; limit?: number } | null;
    resume?: { branch: string; parent_job_id?: string | null } | null;
    // Seed a NEW typed page — the page_type drives the template + its mold.
    create?: {
      page_type: string;
      title?: string;
      context?: string | null;
      home_facet?: string | null;
      pinned?: { key: string; label?: string; value?: string; required?: boolean }[];
    } | null;
  };
  intent?: string;
  theme?: string;
  materialize?: "refs" | "full";
};

// A Codex job record (mirrors wiki_core.web.codex_jobs). Also the submit
// response shape (with ok/error on rejection).
export type CodexJobStep = { id: string; label: string; status: string };
export type CodexJobRecord = {
  ok?: boolean;
  error?: string;
  reason?: string;
  agent?: "codex" | "claude";
  job_id: string;
  brief_id: string;
  brief_sha: string;
  parent_job_id: string | null;
  created_at?: string;
  updated_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
  status: "queued" | "running" | "committing" | "delivered" | "returned" | "done" | "failed" | "cancelled" | string;
  dry_run?: boolean;
  mission_kind?: string | null;
  intent?: string;
  theme?: string;
  steps: CodexJobStep[];
  branch: string | null;
  branch_mode?: "fresh" | "resume" | "continue_current" | string | null;
  draft_pr_url: string | null;
  log_path?: string;
  human_gate_state?: string | null;
};

// A composed/persisted work brief (the complete prompt + its metadata).
export type BriefRecord = {
  ok?: boolean;
  brief_id: string;
  created_at?: string;
  updated_at?: string;
  status: "draft" | "executed" | "discarded" | string;
  spec: BriefSpec;
  brief_sha: string;
  size_chars: number;
  snapshot_generated_at: string;
  target_paths: string[];
  target_hashes?: Record<string, string>;
  context_pages: string[];
  job_id: string | null;
  text: string;
  error?: string;
};

export type SourceFinding = {
  kind: string;
  category: string;
  severity: string;
  line: number;
  excerpt: string;
  detector: string;
};

export type SourceTriageResult = {
  ok: boolean;
  error?: string;
  source?: string;
  context?: string;
  available_contexts?: string[];
  manifest?: Record<string, unknown>;
  source_id?: string;
  source_type?: string;
  exists?: boolean | null;
  risk_flags?: string[];
  secret_block?: boolean;
  findings?: SourceFinding[];
  targets?: {
    context: string;
    target_pages: string[];
    target_entities: string[];
  };
  next_steps?: string[];
};

export type IngestionStage = {
  id: string;
  label: string;
  status: "complete" | "ready" | "waiting" | "blocked" | "warning" | string;
  detail: string;
  command: string[] | null;
  writes: boolean;
};

export type IngestionPlan = {
  ok: boolean;
  source: string;
  context: string;
  source_id?: string;
  triage: SourceTriageResult;
  stages: IngestionStage[];
  next_blocked_stage?: IngestionStage;
  error?: string;
};

export type IngestionStepResult = {
  ok: boolean;
  step_id: string;
  dry_run: boolean;
  summary: string;
  error?: string;
  results: CommandResultEntry[];
  plan: IngestionPlan;
};

export type CommandRunResult = ActionRunResult | WorkflowRunResult | IngestionStepResult;
