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
};

export type SnapshotBundle = {
  manifest: {
    schema_version: string;
    generated_at: string;
    mode: string;
    source_commit: string | null;
    repo: {
      repo_id: string;
      language: string;
      memory_root: string;
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
