import {
  Activity,
  BadgeCheck,
  CheckCircle2,
  CircleAlert,
  Clock3,
  ExternalLink,
  FileText,
  GitBranch,
  GitPullRequest,
  Inbox,
  ListChecks,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  TerminalSquare
} from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { SystemScene } from "./components/SystemScene";
import { gitGateLabel, pageById, qualityFlagCount, reviewChecklist, topActions } from "./data/model";
import { buildIngestionPlan, loadSnapshotBundle, runCockpitAction, runGitWorkflow, runIngestionStep } from "./data/snapshot";
import type { RuntimeConfig } from "./data/runtimeConfig";
import type { ActionCard, CommandRunResult, DiffFile, IngestionPlan, IngestionStage, PageRecord, SnapshotBundle, SourceTriageResult, TimelineEvent } from "./types";
import "./styles.css";

type LoadState =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "ready"; bundle: SnapshotBundle; source: string; runtime: RuntimeConfig };

function routeView(): { view: "ops" | "review" | "health" | "sources" | "pages" | "demo"; pageId?: string } {
  const path = window.location.pathname;
  if (path.startsWith("/demo")) return { view: "demo" };
  if (path.startsWith("/review")) return { view: "review" };
  if (path.startsWith("/health")) return { view: "health" };
  if (path.startsWith("/sources")) return { view: "sources" };
  if (path === "/pages") return { view: "pages" };
  if (path.startsWith("/pages/")) return { view: "pages", pageId: decodeURIComponent(path.slice("/pages/".length)) };
  return { view: "ops" };
}

function StatusPill({ tone, children }: { tone: "good" | "warn" | "bad" | "info" | "muted"; children: ReactNode }) {
  return <span className={`pill pill-${tone}`}>{children}</span>;
}

function Stat({ icon, label, value, tone = "info" }: { icon: ReactNode; label: string; value: string | number; tone?: "good" | "warn" | "bad" | "info" | "muted" }) {
  return (
    <div className={`stat stat-${tone}`}>
      <span className="statIcon">{icon}</span>
      <span className="statLabel">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Nav({ active }: { active: string }) {
  const items = [
    { href: "/ops", label: "Ops", icon: <Activity size={17} /> },
    { href: "/review", label: "Review", icon: <GitPullRequest size={17} /> },
    { href: "/sources", label: "Sources", icon: <Inbox size={17} /> },
    { href: "/health", label: "Health", icon: <ShieldCheck size={17} /> },
    { href: "/pages", label: "Pages", icon: <FileText size={17} /> },
    { href: "/demo", label: "Demo", icon: <Sparkles size={17} /> }
  ];
  return (
    <nav className="navRail" aria-label="Cockpit views">
      {items.map((item) => (
        <a className={active === item.label.toLowerCase() ? "navItem active" : "navItem"} href={item.href} key={item.href} title={item.label}>
          {item.icon}
          <span>{item.label}</span>
        </a>
      ))}
    </nav>
  );
}

function ActionButton({ action, onRun }: { action: ActionCard; onRun: (action: ActionCard) => void }) {
  const risky = action.risk_level !== "read";
  return (
    <button className={risky ? "actionButton risky" : "actionButton"} onClick={() => onRun(action)} title={action.human_reason}>
      {risky ? <RefreshCw size={16} /> : <Play size={16} />}
      <span>{action.title}</span>
    </button>
  );
}

function ActionStack({ actions, onRun }: { actions: ActionCard[]; onRun: (action: ActionCard) => void }) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <h2>Do Now</h2>
        <StatusPill tone="info">{actions.length} actions</StatusPill>
      </div>
      <div className="actionStack">
        {actions.map((action) => (
          <article className="actionRow" key={action.id}>
            <div>
              <h3>{action.title}</h3>
              <p>{action.human_reason}</p>
              <code>{action.commands.map((command) => command.argv.join(" ")).join(" && ")}</code>
            </div>
            <ActionButton action={action} onRun={onRun} />
          </article>
        ))}
      </div>
    </section>
  );
}

function CommandOutput({ result }: { result: CommandRunResult | null }) {
  if (!result) return null;
  const label = "summary" in result ? result.summary : result.action_id;
  return (
    <section className="panel outputPanel">
      <div className="panelHeader">
        <h2>Command Log</h2>
        <StatusPill tone={result.ok ? "good" : "bad"}>{result.ok ? "passed" : "failed"}</StatusPill>
      </div>
      <p>{label}</p>
      {result.results.map((entry, index) => (
        <details open={index === 0} key={`${entry.argv.join(" ")}-${index}`}>
          <summary>
            <TerminalSquare size={16} />
            <span>{entry.argv.join(" ")}</span>
          </summary>
          <pre>{[entry.stdout, entry.stderr].filter(Boolean).join("\n") || "No output."}</pre>
        </details>
      ))}
      {result.results.length === 0 && <pre>{result.error || "No command output."}</pre>}
    </section>
  );
}

function formatEventTime(timestamp: string): string {
  if (!timestamp) return "undated";
  return timestamp.replace("T", " ").replace("Z", " UTC").slice(0, 16);
}

function eventTone(event: TimelineEvent): "good" | "warn" | "bad" | "info" | "muted" {
  if (event.status === "stale") return "warn";
  if (event.kind === "snapshot") return "info";
  if (event.kind === "git_commit") return "muted";
  if (event.status === "fresh" || event.status === "committed") return "good";
  return "muted";
}

function TimelineRadar({ bundle }: { bundle: SnapshotBundle }) {
  const bands = [
    { key: "last_7_days", label: "7d" },
    { key: "last_30_days", label: "30d" },
    { key: "older", label: "older" }
  ];
  const maxBand = Math.max(1, ...bands.map((band) => bundle.timeline.bands[band.key] || 0));
  const events = bundle.timeline.events.slice(0, 8);
  return (
    <section className="panel timelinePanel">
      <div className="panelHeader">
        <h2>Timeline Radar</h2>
        <StatusPill tone="info">{bundle.timeline.summary.event_count} events</StatusPill>
      </div>
      <div className="radarBands" aria-label="Timeline activity bands">
        {bands.map((band) => {
          const value = bundle.timeline.bands[band.key] || 0;
          return (
            <div className="radarBand" key={band.key}>
              <span>{band.label}</span>
              <div><i style={{ width: `${Math.max(8, (value / maxBand) * 100)}%` }} /></div>
              <strong>{value}</strong>
            </div>
          );
        })}
      </div>
      <div className="timelineList">
        {events.map((event) => (
          <article className="timelineEvent" key={event.id}>
            <Clock3 size={16} />
            <div>
              <strong>{event.label}</strong>
              <span>{formatEventTime(event.timestamp)} · {event.context}{event.path ? ` · ${event.path}` : ""}</span>
            </div>
            <StatusPill tone={eventTone(event)}>{event.kind.replaceAll("_", " ")}</StatusPill>
          </article>
        ))}
        {events.length === 0 && <p>No timeline events in this snapshot.</p>}
      </div>
    </section>
  );
}

function diffTone(file: DiffFile): "good" | "warn" | "bad" | "info" | "muted" {
  if (file.risk_hints.includes("public_boundary") || file.risk_hints.includes("deletion_review")) return "bad";
  if (file.risk_hints.includes("memory_review") || file.risk_hints.includes("method_contract")) return "warn";
  if (file.known_generated || file.risk_hints.includes("test_coverage")) return "info";
  return "muted";
}

function hintTone(hint: string): "good" | "warn" | "bad" | "info" | "muted" {
  if (hint === "public_boundary" || hint === "deletion_review") return "bad";
  if (hint === "generated_artifact" || hint === "test_coverage") return "info";
  if (hint === "memory_review" || hint === "method_contract") return "warn";
  return "muted";
}

function DiffFrame({ file }: { file: DiffFile }) {
  return (
    <article className="diffFrame">
      <div className="diffFrameHeader">
        <div>
          <strong>{file.path}</strong>
          <span>{file.category} · {file.change_sources.join(", ")}</span>
        </div>
        <StatusPill tone={diffTone(file)}>{file.status || "changed"}</StatusPill>
      </div>
      <div className="diffMeta">
        <span>+{file.additions}</span>
        <span>-{file.deletions}</span>
        {file.staged && <span>staged</span>}
        {file.unstaged && <span>unstaged</span>}
      </div>
      <div className="riskPills">
        {file.risk_hints.map((hint) => (
          <StatusPill tone={hintTone(hint)} key={hint}>{hint.replaceAll("_", " ")}</StatusPill>
        ))}
        {file.risk_hints.length === 0 && <StatusPill tone="muted">no hints</StatusPill>}
      </div>
      {file.preview.length > 0 && <pre className="diffPreview">{file.preview.join("\n")}</pre>}
    </article>
  );
}

function DiffFilmstrip({ bundle }: { bundle: SnapshotBundle }) {
  const files = bundle.diff.files.slice(0, 8);
  return (
    <section className="panel diffFilmstrip">
      <div className="panelHeader">
        <h2>Semantic Diff</h2>
        <StatusPill tone={bundle.diff.summary.privacy_review_required ? "warn" : "good"}>
          {bundle.diff.summary.file_count} files
        </StatusPill>
      </div>
      <div className="diffSummary">
        <span><GitBranch size={16} /> Branch {bundle.diff.summary.branch_file_count}</span>
        <span><ListChecks size={16} /> Local {bundle.diff.summary.working_tree_file_count}</span>
        <span><FileText size={16} /> +{bundle.diff.summary.insertions} / -{bundle.diff.summary.deletions}</span>
        <span><CircleAlert size={16} /> Privacy {bundle.diff.summary.privacy_review_required ? "yes" : "no"}</span>
      </div>
      <dl className="kv diffCompare">
        <dt>Base</dt>
        <dd>{bundle.diff.compare.base_ref || bundle.diff.compare.default_branch || "not available"}</dd>
        <dt>Merge base</dt>
        <dd>{bundle.diff.compare.merge_base || "not available"}</dd>
        <dt>Head</dt>
        <dd>{bundle.diff.compare.head_commit || "not available"}</dd>
      </dl>
      <div className="filmstripTrack" aria-label="Semantic diff filmstrip">
        {files.map((file) => <DiffFrame file={file} key={`${file.status}-${file.path}`} />)}
        {files.length === 0 && <p>No branch or local diff in this snapshot.</p>}
      </div>
      <ul className="plainList commandList diffCommands">
        {bundle.diff.commands.slice(0, 4).map((command) => (
          <li key={command.join(" ")}><code>{command.join(" ")}</code></li>
        ))}
      </ul>
    </section>
  );
}

function OpsView({ bundle, onRun }: { bundle: SnapshotBundle; onRun: (action: ActionCard) => void }) {
  const stale = bundle.freshness.summary.stale ?? 0;
  const fresh = bundle.freshness.summary.fresh ?? 0;
  const changed = bundle.git.worktree.changed_files.length;
  return (
    <main className="workspace">
      <section className="heroBand">
        <div className="heroCopy">
          <StatusPill tone={bundle.git.proposal.is_proposal_branch ? "warn" : "good"}>{gitGateLabel(bundle.git)}</StatusPill>
          <h1>{bundle.operations.title}</h1>
          <p>{bundle.manifest.repo.repo_id} · {bundle.manifest.mode} · {bundle.manifest.generated_at}</p>
        </div>
        <SystemScene nodes={bundle.graph.nodes} git={bundle.git} />
      </section>
      <section className="statGrid" aria-label="Operational summary">
        <Stat icon={<BadgeCheck size={18} />} label="Fresh pages" value={fresh} tone="good" />
        <Stat icon={<Clock3 size={18} />} label="Stale pages" value={stale} tone={stale ? "warn" : "good"} />
        <Stat icon={<GitBranch size={18} />} label="Branch" value={bundle.git.current_branch || "none"} tone={bundle.git.proposal.is_proposal_branch ? "warn" : "info"} />
        <Stat icon={<ListChecks size={18} />} label="Changed files" value={changed} tone={changed ? "warn" : "good"} />
      </section>
      <TimelineRadar bundle={bundle} />
      <div className="twoColumn">
        <ActionStack actions={topActions(bundle)} onRun={onRun} />
        <section className="panel">
          <div className="panelHeader">
            <h2>Alerts</h2>
            <StatusPill tone={stale ? "warn" : "good"}>{stale ? "attention" : "clear"}</StatusPill>
          </div>
          <ul className="plainList">
            {bundle.operations.sections.flatMap((section) => section.bullets).slice(0, 8).map((bullet) => (
              <li key={bullet}>{bullet}</li>
            ))}
            {bundle.operations.sections.length === 0 && <li>No operation sections in snapshot.</li>}
          </ul>
        </section>
      </div>
    </main>
  );
}

function splitPathInput(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((path) => path.trim())
    .filter(Boolean);
}

function GitWorkflowPanel({
  bundle,
  onWorkflow
}: {
  bundle: SnapshotBundle;
  onWorkflow: (operation: string, payload?: Record<string, unknown>, dryRun?: boolean) => void;
}) {
  const defaultTheme = bundle.git.proposal.theme || "system-threejs-operational-dashboard";
  const [theme, setTheme] = useState(defaultTheme);
  const [paths, setPaths] = useState(bundle.git.worktree.changed_files.map((file) => file.path).join("\n"));
  const [message, setMessage] = useState("refine local cockpit git operations");
  const [prTitle, setPrTitle] = useState("Refine local cockpit Git operations");
  const [prBody, setPrBody] = useState("Local cockpit update with source triage and Git human-gate workflows.");
  const [execute, setExecute] = useState(false);
  const dryRun = !execute;

  return (
    <section className="panel workflowPanel">
      <div className="panelHeader">
        <h2>Git Workflow</h2>
        <label className="toggleControl">
          <input type="checkbox" checked={execute} onChange={(event) => setExecute(event.target.checked)} />
          <span>Execute locally</span>
        </label>
      </div>
      <div className="workflowGrid">
        <label className="field">
          <span>Proposal theme</span>
          <input value={theme} onChange={(event) => setTheme(event.target.value)} />
        </label>
        <div className="buttonCluster">
          <button className="secondaryButton" onClick={() => onWorkflow("list_proposals", {}, false)} title="List local proposal branches">
            <ListChecks size={16} />
            <span>List</span>
          </button>
          <button className="secondaryButton" onClick={() => onWorkflow("start_proposal", { theme }, dryRun)} title="Create proposal branch">
            <GitBranch size={16} />
            <span>Branch</span>
          </button>
        </div>
        <label className="field wide">
          <span>Stage paths</span>
          <textarea value={paths} onChange={(event) => setPaths(event.target.value)} rows={4} />
        </label>
        <button className="secondaryButton wide" onClick={() => onWorkflow("stage_paths", { paths: splitPathInput(paths) }, dryRun)} title="Stage selected changed paths">
          <ListChecks size={16} />
          <span>Stage paths</span>
        </button>
        <label className="field">
          <span>Commit message</span>
          <input value={message} onChange={(event) => setMessage(event.target.value)} />
        </label>
        <button className="secondaryButton" onClick={() => onWorkflow("commit_proposal", { message }, dryRun)} title="Commit proposal changes">
          <CheckCircle2 size={16} />
          <span>Commit</span>
        </button>
        <label className="field">
          <span>PR title</span>
          <input value={prTitle} onChange={(event) => setPrTitle(event.target.value)} />
        </label>
        <label className="field">
          <span>PR body</span>
          <textarea value={prBody} onChange={(event) => setPrBody(event.target.value)} rows={4} />
        </label>
        <div className="buttonCluster wide">
          <button className="secondaryButton" onClick={() => onWorkflow("publish_proposal", {}, dryRun)} title="Push proposal branch">
            <RefreshCw size={16} />
            <span>Publish</span>
          </button>
          <button className="secondaryButton" onClick={() => onWorkflow("open_draft_pr", { title: prTitle, body: prBody }, dryRun)} title="Open draft pull request">
            <GitPullRequest size={16} />
            <span>Draft PR</span>
          </button>
        </div>
      </div>
    </section>
  );
}

function ReviewView({
  bundle,
  onRun,
  onWorkflow
}: {
  bundle: SnapshotBundle;
  onRun: (action: ActionCard) => void;
  onWorkflow: (operation: string, payload?: Record<string, unknown>, dryRun?: boolean) => void;
}) {
  const checks = reviewChecklist(bundle);
  const prAction = bundle.actions.actions.find((action) => action.id === "pr-summary");
  return (
    <main className="workspace">
      <section className="panel reviewGate">
        <div className="panelHeader">
          <h1>Human Gate</h1>
          <StatusPill tone={bundle.git.proposal.is_proposal_branch ? "warn" : "info"}>{bundle.git.proposal.human_gate_state}</StatusPill>
        </div>
        <div className="gateGrid">
          <div>
            <h2>Git Proposal</h2>
            <dl className="kv">
              <dt>Branch</dt>
              <dd>{bundle.git.current_branch || "detached/unknown"}</dd>
              <dt>Upstream</dt>
              <dd>{bundle.git.upstream.name || "not configured"}</dd>
              <dt>Ahead / behind</dt>
              <dd>{bundle.git.upstream.ahead} / {bundle.git.upstream.behind}</dd>
              <dt>Worktree</dt>
              <dd>{bundle.git.worktree.clean ? "clean" : "changed"}</dd>
            </dl>
          </div>
          <div>
            <h2>Checklist</h2>
            <ul className="checkList">
              {checks.map((check) => (
                <li key={check.label} className={check.ok ? "ok" : "wait"}>
                  {check.ok ? <CheckCircle2 size={17} /> : <CircleAlert size={17} />}
                  <span>{check.label}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
        {prAction && <ActionButton action={prAction} onRun={onRun} />}
      </section>
      <GitWorkflowPanel bundle={bundle} onWorkflow={onWorkflow} />
      <DiffFilmstrip bundle={bundle} />
      <section className="panel">
        <div className="panelHeader">
          <h2>Changed Files</h2>
          <StatusPill tone={bundle.git.worktree.changed_files.length ? "warn" : "good"}>
            {bundle.git.worktree.changed_files.length}
          </StatusPill>
        </div>
        <div className="fileTable" role="table">
          {bundle.git.worktree.changed_files.map((file) => (
            <div className="fileRow" role="row" key={file.path}>
              <code>{file.status}</code>
              <span>{file.path}</span>
              <StatusPill tone={file.known_generated ? "info" : "muted"}>{file.known_generated ? "generated" : "manual"}</StatusPill>
            </div>
          ))}
          {bundle.git.worktree.changed_files.length === 0 && <p>No local changes in this snapshot.</p>}
        </div>
      </section>
      <section className="panel">
        <div className="panelHeader">
          <h2>Machine Gates</h2>
          <StatusPill tone="muted">{bundle.gates.status}</StatusPill>
        </div>
        <ul className="plainList commandList">
          {bundle.gates.gates.map((gate) => (
            <li key={gate.id}>
              <code>{gate.argv.join(" ")}</code>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}

function HealthView({ bundle }: { bundle: SnapshotBundle }) {
  const qualityFlags = qualityFlagCount(bundle);
  return (
    <main className="workspace">
      <section className="statGrid">
        <Stat icon={<ShieldCheck size={18} />} label="Gates" value={bundle.gates.gates.length} tone="info" />
        <Stat icon={<CircleAlert size={18} />} label="Quality flags" value={qualityFlags} tone={qualityFlags ? "warn" : "good"} />
        <Stat icon={<FileText size={18} />} label="Pages" value={bundle.pages.pages.length} tone="info" />
        <Stat icon={<Search size={18} />} label="Sources" value={bundle.sources.sources.length} tone="info" />
      </section>
      <section className="panel">
        <div className="panelHeader">
          <h1>Context Vitality</h1>
          <StatusPill tone="info">{Object.keys(bundle.freshness.by_context).length} contexts</StatusPill>
        </div>
        <div className="contextGrid">
          {Object.entries(bundle.freshness.by_context).map(([context, stats]) => (
            <article className="contextTile" key={context}>
              <h2>{context}</h2>
              <span>fresh {stats.fresh ?? 0}</span>
              <span>stale {stats.stale ?? 0}</span>
              <span>unknown {stats.unknown ?? 0}</span>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

function sourceResultTone(result: SourceTriageResult | null): "good" | "warn" | "bad" | "muted" {
  if (!result) return "muted";
  if (result.secret_block || result.error) return "bad";
  if ((result.risk_flags || []).length > 0) return "warn";
  return "good";
}

function stageTone(stage: IngestionStage): "good" | "warn" | "bad" | "info" | "muted" {
  if (stage.status === "complete") return "good";
  if (stage.status === "ready") return "info";
  if (stage.status === "warning" || stage.status === "waiting") return "warn";
  if (stage.status === "blocked") return "bad";
  return "muted";
}

function runnableStage(stage: IngestionStage): boolean {
  return Boolean(stage.command) && stage.status !== "blocked";
}

function IngestionPipeline({
  plan,
  executeWrites,
  busyStep,
  onRun
}: {
  plan: IngestionPlan | null;
  executeWrites: boolean;
  busyStep: string;
  onRun: (stage: IngestionStage) => void;
}) {
  if (!plan) return null;
  return (
    <section className="pipelinePanel">
      <div className="panelHeader">
        <h3>Pipeline</h3>
        <StatusPill tone={plan.ok ? "good" : "bad"}>{plan.ok ? "ready" : "blocked"}</StatusPill>
      </div>
      <div className="pipelineRail" aria-label="Ingestion pipeline">
        {plan.stages.map((stage, index) => (
          <article className={`pipelineStage stage-${stage.status}`} key={stage.id}>
            <div className="stageIndex">{index + 1}</div>
            <div>
              <div className="stageTitle">
                <strong>{stage.label}</strong>
                <StatusPill tone={stageTone(stage)}>{stage.status}</StatusPill>
              </div>
              <p>{stage.detail}</p>
              {stage.command && <code>{stage.command.join(" ")}</code>}
            </div>
            {runnableStage(stage) && (
              <button className={stage.writes ? "secondaryButton risky" : "secondaryButton"} onClick={() => onRun(stage)} title={stage.detail}>
                <Play size={16} />
                <span>{busyStep === stage.id ? "Running" : stage.writes && !executeWrites ? "Dry-run" : "Run"}</span>
              </button>
            )}
          </article>
        ))}
      </div>
      {plan.next_blocked_stage && (
        <p className="pipelineNote">
          Next stop: <strong>{plan.next_blocked_stage.label}</strong> · {plan.next_blocked_stage.detail}
        </p>
      )}
    </section>
  );
}

function SourcesView({
  bundle,
  onCommand
}: {
  bundle: SnapshotBundle;
  onCommand: (result: CommandRunResult) => void;
}) {
  const contexts = useMemo(
    () => {
      const values = [...new Set([...Object.keys(bundle.freshness.by_context), ...bundle.pages.pages.map((page) => page.context)])].filter(Boolean);
      return values.length ? values : [bundle.manifest.repo.default_context || "system"];
    },
    [bundle]
  );
  const firstSource = bundle.sources.sources[0];
  const defaultContext = firstSource?.context || bundle.manifest.repo.default_context || contexts[0] || "system";
  const [source, setSource] = useState(firstSource?.path || "");
  const [context, setContext] = useState(defaultContext);
  const [result, setResult] = useState<SourceTriageResult | null>(null);
  const [plan, setPlan] = useState<IngestionPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyStep, setBusyStep] = useState("");
  const [executeWrites, setExecuteWrites] = useState(false);

  const runTriage = async () => {
    setBusy(true);
    try {
      const nextPlan = await buildIngestionPlan(source, context);
      setPlan(nextPlan);
      setResult(nextPlan.triage);
    } catch (error) {
      setPlan(null);
      setResult({ ok: false, error: error instanceof Error ? error.message : "source triage failed" });
    } finally {
      setBusy(false);
    }
  };
  const runStage = async (stage: IngestionStage) => {
    setBusyStep(stage.id);
    try {
      const stepResult = await runIngestionStep(source, context, stage.id, stage.writes ? !executeWrites : false);
      setPlan(stepResult.plan);
      setResult(stepResult.plan.triage);
      onCommand(stepResult);
    } catch (error) {
      onCommand({
        ok: false,
        step_id: stage.id,
        dry_run: stage.writes ? !executeWrites : false,
        summary: stage.label,
        error: error instanceof Error ? error.message : "ingestion step failed",
        results: [],
        plan: plan || {
          ok: false,
          source,
          context,
          triage: result || { ok: false, error: "ingestion step failed" },
          stages: []
        }
      });
    } finally {
      setBusyStep("");
    }
  };

  return (
    <main className="workspace sourcesWorkspace">
      <section className="panel sourceInbox">
        <div className="panelHeader">
          <h1>Sources</h1>
          <StatusPill tone="info">{bundle.sources.sources.length}</StatusPill>
        </div>
        <div className="sourceList">
          {bundle.sources.sources.map((item) => (
            <button
              className={source === item.path ? "sourceCard active" : "sourceCard"}
              key={item.id}
              onClick={() => {
                setSource(item.path);
                setContext(item.context || context);
                setPlan(null);
                setResult(null);
              }}
              title={item.path}
            >
              <span>{item.title}</span>
              <small>{item.context} · {item.path}</small>
            </button>
          ))}
          {bundle.sources.sources.length === 0 && <p>No source pages in this snapshot.</p>}
        </div>
      </section>
      <section className="panel">
        <div className="panelHeader">
          <h2>Ingestion Wizard</h2>
          <StatusPill tone={sourceResultTone(result)}>{result ? (result.ok ? "ready" : "blocked") : "idle"}</StatusPill>
        </div>
        <div className="workflowGrid">
          <label className="field wide">
            <span>Source path or URL</span>
            <input value={source} onChange={(event) => setSource(event.target.value)} />
          </label>
          <label className="field">
            <span>Context</span>
            <select value={context} onChange={(event) => setContext(event.target.value)}>
              {contexts.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <button className="secondaryButton" disabled={!source || busy} onClick={runTriage} title="Run local source triage">
            <Search size={16} />
            <span>{busy ? "Planning" : "Plan ingestion"}</span>
          </button>
          <label className="toggleControl wideToggle">
            <input type="checkbox" checked={executeWrites} onChange={(event) => setExecuteWrites(event.target.checked)} />
            <span>Execute write steps</span>
          </label>
        </div>
        {result && (
          <div className="triageResult">
            <dl className="kv">
              <dt>Source ID</dt>
              <dd>{result.source_id || "not available"}</dd>
              <dt>Type</dt>
              <dd>{result.source_type || "unknown"}</dd>
              <dt>Exists</dt>
              <dd>{String(result.exists)}</dd>
              <dt>Context</dt>
              <dd>{result.context || context}</dd>
            </dl>
            <div className="tagCloud">
              {(result.risk_flags || []).map((flag) => (
                <StatusPill tone={flag === "secret_block" ? "bad" : "warn"} key={flag}>
                  {flag}
                </StatusPill>
              ))}
              {(result.risk_flags || []).length === 0 && <StatusPill tone="good">no flags</StatusPill>}
            </div>
            {result.targets && (
              <div className="targetGrid">
                <div>
                  <h3>Pages</h3>
                  <ul className="plainList compactList">
                    {result.targets.target_pages.map((page) => (
                      <li key={page}>{page}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h3>Entities</h3>
                  <ul className="plainList compactList">
                    {result.targets.target_entities.map((entity) => (
                      <li key={entity}>{entity}</li>
                    ))}
                    {result.targets.target_entities.length === 0 && <li>none</li>}
                  </ul>
                </div>
              </div>
            )}
            <h3>Next Steps</h3>
            <ul className="plainList compactList">
              {(result.next_steps || []).map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ul>
            {(result.findings || []).length > 0 && (
              <>
                <h3>Findings</h3>
                <div className="fileTable">
                  {(result.findings || []).map((finding) => (
                    <div className="fileRow findingRow" key={`${finding.kind}-${finding.line}-${finding.excerpt}`}>
                      <code>{finding.category}</code>
                      <span>{finding.kind} · line {finding.line} · {finding.excerpt}</span>
                      <StatusPill tone={finding.category === "secret" ? "bad" : "warn"}>{finding.severity}</StatusPill>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
        <IngestionPipeline plan={plan} executeWrites={executeWrites} busyStep={busyStep} onRun={runStage} />
      </section>
    </main>
  );
}

function PageList({ pages, selected }: { pages: PageRecord[]; selected: PageRecord | undefined }) {
  return (
    <aside className="pageList" aria-label="Pages">
      {pages.slice(0, 120).map((page) => (
        <a className={selected?.id === page.id ? "pageLink active" : "pageLink"} href={`/pages/${encodeURIComponent(page.id)}`} key={page.id}>
          <span>{page.title}</span>
          <small>{page.context} · {page.page_type || "page"}</small>
        </a>
      ))}
    </aside>
  );
}

function PagesView({ bundle, pageId }: { bundle: SnapshotBundle; pageId?: string }) {
  const selected = pageById(bundle.pages.pages, pageId);
  return (
    <main className="workspace pagesWorkspace">
      <PageList pages={bundle.pages.pages} selected={selected} />
      <section className="panel pageDetail">
        {selected && (
          <>
            <div className="panelHeader">
              <h1>{selected.title}</h1>
              <StatusPill tone={selected.freshness_state === "fresh" ? "good" : selected.freshness_state === "stale" ? "warn" : "muted"}>
                {selected.freshness_state}
              </StatusPill>
            </div>
            <dl className="kv">
              <dt>Path</dt>
              <dd>{selected.path}</dd>
              <dt>Type</dt>
              <dd>{selected.page_type || "unknown"}</dd>
              <dt>Context</dt>
              <dd>{selected.context}</dd>
              <dt>Sources</dt>
              <dd>{selected.source_refs.length ? selected.source_refs.join(", ") : "none listed"}</dd>
            </dl>
            <p className="pageSummary">{selected.summary || "No summary text in snapshot."}</p>
            <a className="externalLink" href={`/${selected.path}`} title="Open Markdown path">
              <ExternalLink size={16} />
              <span>{selected.path}</span>
            </a>
          </>
        )}
      </section>
    </main>
  );
}

export function App() {
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" });
  const [route, setRoute] = useState(routeView());
  const [commandResult, setCommandResult] = useState<CommandRunResult | null>(null);

  useEffect(() => {
    loadSnapshotBundle()
      .then(({ bundle, source, runtime }) => setLoadState({ status: "ready", bundle, source, runtime }))
      .catch((error: Error) => setLoadState({ status: "error", error: error.message }));
  }, []);

  useEffect(() => {
    const onPop = () => setRoute(routeView());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const active = route.view === "pages" ? "pages" : route.view;
  const runAction = async (action: ActionCard) => {
    try {
      setCommandResult(await runCockpitAction(action.id, action.default_dry_run));
    } catch (error) {
      setCommandResult({
        ok: false,
        action_id: action.id,
        dry_run: action.default_dry_run,
        error: error instanceof Error ? error.message : "action failed",
        results: []
      });
    }
  };
  const runWorkflow = async (operation: string, payload: Record<string, unknown> = {}, dryRun = true) => {
    try {
      setCommandResult(await runGitWorkflow(operation, payload, dryRun));
    } catch (error) {
      setCommandResult({
        ok: false,
        operation,
        dry_run: dryRun,
        summary: operation,
        error: error instanceof Error ? error.message : "workflow failed",
        data: {},
        results: []
      });
    }
  };

  const content = useMemo(() => {
    if (loadState.status === "loading") return <main className="workspace"><section className="panel"><h1>Loading cockpit</h1></section></main>;
    if (loadState.status === "error") return <main className="workspace"><section className="panel"><h1>Snapshot unavailable</h1><p>{loadState.error}</p></section></main>;
    const { bundle } = loadState;
    if (route.view === "review") return <ReviewView bundle={bundle} onRun={runAction} onWorkflow={runWorkflow} />;
    if (route.view === "sources") return <SourcesView bundle={bundle} onCommand={setCommandResult} />;
    if (route.view === "health") return <HealthView bundle={bundle} />;
    if (route.view === "pages") return <PagesView bundle={bundle} pageId={route.pageId} />;
    if (route.view === "demo") return <OpsView bundle={bundle} onRun={runAction} />;
    return <OpsView bundle={bundle} onRun={runAction} />;
  }, [loadState, route]);

  return (
    <div className="appShell">
      <Nav active={active} />
      <div className="mainColumn">
        <header className="topBar">
          <div>
            <strong>Wiki Viva Cockpit</strong>
            {loadState.status === "ready" && (
              <span>
                {loadState.runtime.repoLabel || loadState.bundle.manifest.repo.repo_id} · {loadState.runtime.mode || loadState.bundle.manifest.mode} · {loadState.source}
              </span>
            )}
          </div>
          {loadState.status === "ready" && (
            <StatusPill tone={loadState.bundle.git.proposal.is_proposal_branch ? "warn" : "good"}>
              {loadState.bundle.git.current_branch || "no branch"}
            </StatusPill>
          )}
        </header>
        {content}
        <CommandOutput result={commandResult} />
      </div>
    </div>
  );
}
