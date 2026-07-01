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
import type { MouseEvent, ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { SystemScene } from "./components/SystemScene";
import { gitGateLabel, pageById, qualityFlagCount, reviewChecklist, topActions } from "./data/model";
import { buildIngestionPlan, loadSnapshotBundle, runCockpitAction, runGitWorkflow, runIngestionStep } from "./data/snapshot";
import type { RuntimeConfig } from "./data/runtimeConfig";
import type { ActionCard, CommandResultEntry, CommandRunResult, DiffFile, IngestionPlan, IngestionStage, PageRecord, SnapshotBundle, SourceFinding, SourceTriageResult, TimelineEvent } from "./types";
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

function modeLabel(mode: string): string {
  const labels: Record<string, string> = {
    static: "read-only",
    static_demo: "demo data",
    local_operator: "local operator",
    github_connected: "review connected",
    controlled_operator: "controlled operator"
  };
  return labels[mode] || mode.replaceAll("_", " ");
}

function gateStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    approved: "approved",
    clear: "clear",
    clean: "none",
    dirty: "needs review",
    linked: "linked",
    needs_publish: "needs send",
    pass: "passed",
    published: "sent",
    ready: "ready",
    warn: "needs attention",
    fail: "blocked",
    not_run: "not checked",
    not_opened: "not opened",
    outside_flow: "outside review flow",
    unknown: "not checked"
  };
  return labels[status] || status.replaceAll("_", " ");
}

function workspaceDisplayLabel(git: SnapshotBundle["git"]): string {
  if (git.proposal.is_proposal_branch) return git.proposal.theme ? `review: ${git.proposal.theme}` : "review workspace";
  if (git.current_branch === git.default_branch) return "approved content";
  return git.current_branch ? "current workspace" : "not detected";
}

function sharedCopyLabel(git: SnapshotBundle["git"]): string {
  if (git.upstream.name && git.proposal.theme) return `sent review: ${git.proposal.theme}`;
  return git.upstream.name || git.upstream.remote || "not configured";
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
    { href: "/ops", id: "ops", label: "Home", icon: <Activity size={17} /> },
    { href: "/review", id: "review", label: "Approve", icon: <GitPullRequest size={17} /> },
    { href: "/sources", id: "sources", label: "Add", icon: <Inbox size={17} /> },
    { href: "/health", id: "health", label: "Health", icon: <ShieldCheck size={17} /> },
    { href: "/pages", id: "pages", label: "Content", icon: <FileText size={17} /> },
    { href: "/demo", id: "demo", label: "Demo", icon: <Sparkles size={17} /> }
  ];
  return (
    <nav className="navRail" aria-label="Cockpit views">
      {items.map((item) => (
        <a className={active === item.id ? "navItem active" : "navItem"} href={item.href} key={item.href} title={item.label}>
          {item.icon}
          <span>{item.label}</span>
        </a>
      ))}
    </nav>
  );
}

function actionTitle(action: ActionCard): string {
  const labels: Record<string, string> = {
    "git-status": "Check workspace",
    "review-local-changes": "Review content changes",
    "run-honesty-gates": "Run approval checks",
    "pr-summary": "Build review packet",
    "graph-check": "Check content map"
  };
  return labels[action.id] || action.title;
}

function actionReason(action: ActionCard): string {
  const labels: Record<string, string> = {
    "review-local-changes": "Shows changed content before saving a version or preparing approval.",
    "run-honesty-gates": "Runs the deterministic checks that should be green before human approval.",
    "pr-summary": "Builds the review packet from changed content, affected areas and privacy notes.",
    "graph-check": "Checks whether related content and impact links still make sense."
  };
  return labels[action.id] || action.human_reason;
}

function actionWhenLabel(action: ActionCard): string {
  const labels: Record<string, string> = {
    "git-status": "When you need to know whether the local workspace is clean.",
    "review-local-changes": "Before asking someone to approve the current changes.",
    "run-honesty-gates": "Before relying on the wiki or moving a request forward.",
    "pr-summary": "When the approval request needs a human-readable packet.",
    "graph-check": "When related content may have been missed."
  };
  return labels[action.id] || "When this step is the next useful check.";
}

function actionResultLabel(action: ActionCard): string {
  const labels: Record<string, string> = {
    "git-status": "Workspace state",
    "review-local-changes": "Changed content list",
    "run-honesty-gates": "Pass/fail validation",
    "pr-summary": "Review packet",
    "graph-check": "Link and impact signal"
  };
  return labels[action.id] || "Local result";
}

function ActionButton({ action, onRun }: { action: ActionCard; onRun: (action: ActionCard) => void }) {
  const risky = action.risk_level !== "read";
  const title = actionTitle(action);
  return (
    <button className={risky ? "actionButton risky" : "actionButton"} onClick={() => onRun(action)} title={actionReason(action)}>
      {risky ? <RefreshCw size={16} /> : <Play size={16} />}
      <span>{title}</span>
    </button>
  );
}

function ActionStack({ actions, onRun }: { actions: ActionCard[]; onRun: (action: ActionCard) => void }) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <h2>Next Steps</h2>
        <StatusPill tone="info">{actions.length} ready</StatusPill>
      </div>
      <div className="actionStack">
        {actions.map((action) => (
          <article className="actionRow" key={action.id}>
            <div>
              <h3>{actionTitle(action)}</h3>
              <p>{actionReason(action)}</p>
              <dl className="actionFacts">
                <dt>Use when</dt>
                <dd>{actionWhenLabel(action)}</dd>
                <dt>Gives you</dt>
                <dd>{actionResultLabel(action)}</dd>
              </dl>
              <details className="inlineDetails">
                <summary>Technical command</summary>
                <code>{action.commands.map((command) => command.argv.join(" ")).join(" && ")}</code>
              </details>
            </div>
            <ActionButton action={action} onRun={onRun} />
          </article>
        ))}
      </div>
    </section>
  );
}

function commandResultTitle(result: CommandRunResult): string {
  if ("summary" in result && result.summary) return result.summary;
  if ("operation" in result) return result.operation.replaceAll("_", " ");
  if ("action_id" in result) {
    const labels: Record<string, string> = {
      "git-status": "Workspace check finished",
      "review-local-changes": "Content review finished",
      "run-honesty-gates": "Approval checks finished",
      "pr-summary": "Review packet prepared",
      "graph-check": "Content map check finished"
    };
    return labels[result.action_id] || result.action_id.replaceAll("_", " ");
  }
  return "Action finished";
}

function commandResultMode(result: CommandRunResult): string {
  return result.dry_run ? "preview only" : "applied";
}

function commandEntryLabel(entry: CommandResultEntry, index: number): string {
  return `Step ${index + 1} ${entry.ok ? "completed" : "needs attention"}`;
}

function CommandOutput({ result }: { result: CommandRunResult | null }) {
  if (!result) return null;
  const passedCount = result.results.filter((entry) => entry.ok).length;
  const failedCount = result.results.length - passedCount;
  return (
    <section className="panel outputPanel">
      <div className="panelHeader">
        <h2>Action Result</h2>
        <StatusPill tone={result.ok ? "good" : "bad"}>{result.ok ? "completed" : "needs attention"}</StatusPill>
      </div>
      <div className="outputSummary">
        <strong>{commandResultTitle(result)}</strong>
        <p>
          {result.ok ? "The local action finished. Review the step output only if something looks unexpected." : "The action did not finish cleanly. Use the details below to diagnose it."}
        </p>
      </div>
      <div className="outputFacts" aria-label="Action result facts">
        <span>
          <strong>{commandResultMode(result)}</strong>
          Mode
        </span>
        <span>
          <strong>{passedCount}/{result.results.length}</strong>
          Steps completed
        </span>
        <span>
          <strong>{failedCount}</strong>
          Needs attention
        </span>
      </div>
      {result.error && <p className="outputError">{result.error}</p>}
      <div className="outputStepList">
        {result.results.map((entry, index) => (
          <details className="auditDetails outputStep" key={`${entry.argv.join(" ")}-${index}`}>
            <summary>
              <TerminalSquare size={16} />
              <span>{commandEntryLabel(entry, index)}</span>
              <StatusPill tone={entry.ok ? "good" : "bad"}>{entry.ok ? "ok" : "failed"}</StatusPill>
            </summary>
            <div className="commandMeta">
              <span>{entry.dry_run ? "preview only" : "applied"}</span>
              <code>{entry.argv.join(" ")}</code>
            </div>
            <pre>{[entry.stdout, entry.stderr].filter(Boolean).join("\n") || "No output."}</pre>
          </details>
        ))}
      </div>
      {result.results.length === 0 && !result.error && <p className="outputEmpty">No terminal output was returned.</p>}
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

function eventKindLabel(kind: string): string {
  const labels: Record<string, string> = {
    git_commit: "saved change",
    snapshot: "snapshot",
    source_ingested: "new source",
    source_reviewed: "source review",
    gate_run: "check run",
    page_updated: "content update"
  };
  return labels[kind] || kind.replaceAll("_", " ");
}

function timelineDecision(bundle: SnapshotBundle): { label: string; detail: string; tone: "good" | "warn" | "bad" | "info" | "muted" } {
  const stale = bundle.freshness.summary.stale ?? 0;
  const recent = bundle.timeline.bands.last_7_days || 0;
  if (stale > 0) {
    return { label: "Review before relying", detail: `${stale} content item(s) need refresh. Use activity only as context, not proof.`, tone: "warn" };
  }
  if (recent > 0) {
    return { label: "Recent signal exists", detail: `${recent} activity item(s) in the last 7 days. Check the list before approving.`, tone: "good" };
  }
  return { label: "No recent signal", detail: "No recent activity is visible. Refresh or verify important content before relying on it.", tone: "warn" };
}

function TimelineRadar({ bundle }: { bundle: SnapshotBundle }) {
  const bands = [
    { key: "last_7_days", label: "This week" },
    { key: "last_30_days", label: "This month" },
    { key: "older", label: "Older" }
  ];
  const maxBand = Math.max(1, ...bands.map((band) => bundle.timeline.bands[band.key] || 0));
  const events = bundle.timeline.events.slice(0, 8);
  const decision = timelineDecision(bundle);
  return (
    <section className="panel timelinePanel">
      <div className="panelHeader">
        <h2>Activity Signal</h2>
        <StatusPill tone={decision.tone}>{decision.label}</StatusPill>
      </div>
      <p className="panelLead">{decision.detail}</p>
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
              <span>{formatEventTime(event.timestamp)} · {event.context || "system"}</span>
            </div>
            <StatusPill tone={eventTone(event)}>{eventKindLabel(event.kind)}</StatusPill>
          </article>
        ))}
        {events.length === 0 && <p>No timeline events in this view.</p>}
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

function changeStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    M: "changed",
    A: "new",
    D: "removed",
    R: "renamed",
    C: "copied",
    "??": "new local file",
    modified: "changed",
    added: "new",
    deleted: "removed"
  };
  return labels[status] || status.replaceAll("_", " ") || "changed";
}

function changeSourceLabel(source: string): string {
  const labels: Record<string, string> = {
    branch: "saved review",
    working_tree: "still local",
    worktree: "still local",
    staged: "included",
    unstaged: "not included yet"
  };
  return labels[source] || source.replaceAll("_", " ");
}

function changeAreaLabel(category: string): string {
  const labels: Record<string, string> = {
    cli: "command tools",
    core: "wiki rules",
    docs: "documentation",
    memory: "memory pages",
    repo: "repo setup",
    scripts: "command tools",
    skills: "agent instructions",
    template: "templates",
    tests: "tests",
    templates: "templates",
    web: "cockpit app",
    web_cockpit: "cockpit app",
    workflow: "workflow docs"
  };
  return labels[category] || category.replaceAll("_", " ");
}

function gateCheckLabel(id: string): string {
  const labels: Record<string, string> = {
    wiki_audit: "source and privacy audit",
    methodology_coverage: "method coverage",
    operation_compile: "operations page",
    input_stage: "intake page",
    pytest: "test suite"
  };
  return labels[id] || id.replaceAll("_", " ");
}

function humanList(items: string[], empty = "none listed"): string {
  const unique = [...new Set(items.filter(Boolean))];
  if (unique.length === 0) return empty;
  if (unique.length === 1) return unique[0];
  if (unique.length === 2) return `${unique[0]} and ${unique[1]}`;
  return `${unique.slice(0, -1).join(", ")} and ${unique[unique.length - 1]}`;
}

function riskHintLabel(hint: string): string {
  const labels: Record<string, string> = {
    public_boundary: "public sharing review",
    deletion_review: "deletion review",
    generated_artifact: "generated content",
    memory_review: "content review",
    method_contract: "operating rule review",
    test_coverage: "test coverage"
  };
  return labels[hint] || hint.replaceAll("_", " ");
}

function freshnessLabel(state: string): string {
  if (state === "fresh") return "ok";
  if (state === "stale") return "needs refresh";
  return "not checked";
}

function contentKindLabel(kind: string): string {
  const labels: Record<string, string> = {
    root_index: "home map",
    context_hub: "area overview",
    operational_rule: "operating rule",
    source: "evidence source",
    dashboard: "dashboard",
    proposal: "review draft"
  };
  return labels[kind] || kind.replaceAll("_", " ") || "content";
}

function pageStatusTone(page: PageRecord): "good" | "warn" | "bad" | "info" | "muted" {
  if (page.risk_flags.length > 0) return "warn";
  if (page.freshness_state === "fresh") return "good";
  if (page.freshness_state === "stale") return "warn";
  return "muted";
}

function pageMetaLabel(page: PageRecord): string {
  return `${page.context || "No area"} · ${contentKindLabel(page.page_type)} · ${freshnessLabel(page.freshness_state)}`;
}

function evidenceLabel(page: PageRecord): string {
  if (page.source_refs.length === 0) return "No evidence links listed";
  if (page.source_refs.length === 1) return "1 evidence link";
  return `${page.source_refs.length} evidence links`;
}

function pageNeedsAttention(page: PageRecord): boolean {
  return page.risk_flags.length > 0 || page.freshness_state === "stale" || page.approved_state !== "approved";
}

function pageDecisionLabel(page: PageRecord): string {
  if (page.risk_flags.length > 0) return "Review risk";
  if (page.freshness_state === "stale") return "Refresh before trusting";
  if (page.approved_state !== "approved") return "Needs approval";
  return "Ready to trust";
}

function pageDecisionDetail(page: PageRecord): string {
  if (page.risk_flags.length > 0) return `Check ${humanList(page.risk_flags.map(riskHintLabel))} before using this content.`;
  if (page.freshness_state === "stale") return "The content may still be useful, but it should be refreshed before a decision depends on it.";
  if (page.approved_state !== "approved") return "This item has not reached the approved wiki state yet.";
  return "No freshness or risk issue is currently visible in the cockpit.";
}

function pageEvidenceDetail(page: PageRecord): string {
  if (page.source_refs.length === 0) return "No source link is listed for this item.";
  if (page.source_refs.length === 1) return "One source link is available for verification.";
  return `${page.source_refs.length} source links are available for verification.`;
}

type ContentViewMode = "attention" | "evidence" | "trusted" | "all";

const CONTENT_VIEW_MODES: { id: ContentViewMode; label: string; description: string }[] = [
  { id: "attention", label: "Needs attention", description: "Stale, risky or not approved" },
  { id: "evidence", label: "Has evidence", description: "Items with source links" },
  { id: "trusted", label: "Ready to trust", description: "Fresh and risk-free" },
  { id: "all", label: "All content", description: "Every wiki item" }
];

function pagesForContentMode(pages: PageRecord[], mode: ContentViewMode): PageRecord[] {
  if (mode === "attention") return pages.filter(pageNeedsAttention);
  if (mode === "evidence") return pages.filter((page) => page.source_refs.length > 0 || page.page_type === "source");
  if (mode === "trusted") return pages.filter((page) => page.freshness_state === "fresh" && page.risk_flags.length === 0 && page.approved_state === "approved");
  return pages;
}

function contentModeCounts(pages: PageRecord[]): Record<ContentViewMode, number> {
  return {
    attention: pagesForContentMode(pages, "attention").length,
    evidence: pagesForContentMode(pages, "evidence").length,
    trusted: pagesForContentMode(pages, "trusted").length,
    all: pages.length
  };
}

function updatedLabel(value: string): string {
  if (!value) return "Not dated";
  return value.replace("T", " ").replace("Z", "").slice(0, 16);
}

function DiffFrame({ file }: { file: DiffFile }) {
  return (
    <article className="diffFrame">
      <div className="diffFrameHeader">
        <div>
          <strong>{file.path}</strong>
          <span>{file.category} · {file.change_sources.map(changeSourceLabel).join(", ")}</span>
        </div>
        <StatusPill tone={diffTone(file)}>{changeStatusLabel(file.status || "changed")}</StatusPill>
      </div>
      <div className="diffMeta">
        <span>{file.additions} added</span>
        <span>{file.deletions} removed</span>
        {file.staged && <span>included</span>}
        {file.unstaged && <span>still local</span>}
      </div>
      <div className="riskPills">
        {file.risk_hints.map((hint) => (
          <StatusPill tone={hintTone(hint)} key={hint}>{riskHintLabel(hint)}</StatusPill>
        ))}
        {file.risk_hints.length === 0 && <StatusPill tone="muted">no explicit risk</StatusPill>}
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
        <h2>Evidence Board</h2>
        <StatusPill tone={bundle.diff.summary.privacy_review_required ? "warn" : "good"}>
          {bundle.diff.summary.file_count} item(s)
        </StatusPill>
      </div>
      <div className="diffSummary">
        <span><GitBranch size={16} /> Saved review {bundle.diff.summary.branch_file_count}</span>
        <span><ListChecks size={16} /> Still local {bundle.diff.summary.working_tree_file_count}</span>
        <span><FileText size={16} /> +{bundle.diff.summary.insertions} / -{bundle.diff.summary.deletions}</span>
        <span><CircleAlert size={16} /> Privacy {bundle.diff.summary.privacy_review_required ? "yes" : "no"}</span>
      </div>
      <div className="filmstripTrack" aria-label="Changed content board">
        {files.map((file) => <DiffFrame file={file} key={`${file.status}-${file.path}`} />)}
        {files.length === 0 && <p>No saved or local changes in this view.</p>}
      </div>
      <details className="auditDetails">
        <summary>Technical audit trail</summary>
        <dl className="kv diffCompare">
          <dt>Compared with</dt>
          <dd>{bundle.diff.compare.base_ref || bundle.diff.compare.default_branch || "not available"}</dd>
          <dt>Review base</dt>
          <dd>{bundle.diff.compare.merge_base || "not available"}</dd>
          <dt>Current version</dt>
          <dd>{bundle.diff.compare.head_commit || "not available"}</dd>
        </dl>
        <ul className="plainList commandList diffCommands">
          {bundle.diff.commands.slice(0, 4).map((command) => (
            <li key={command.join(" ")}><code>{command.join(" ")}</code></li>
          ))}
        </ul>
      </details>
    </section>
  );
}

function pageMatches(page: PageRecord, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [page.title, page.path, page.context, page.page_type, page.summary, ...page.source_refs]
    .join(" ")
    .toLowerCase()
    .includes(needle);
}

type MapIntentId = "review" | "evidence" | "stale" | "browse";

const MAP_INTENTS: MapIntentId[] = ["review", "evidence", "stale", "browse"];

function pathsInReview(bundle: SnapshotBundle): Set<string> {
  return new Set([
    ...bundle.diff.files.map((file) => file.path),
    ...bundle.git.worktree.changed_files.map((file) => file.path)
  ]);
}

function pagesForMapIntent(bundle: SnapshotBundle, intent: MapIntentId): PageRecord[] {
  const reviewPaths = pathsInReview(bundle);
  if (intent === "review") {
    const changed = bundle.pages.pages.filter((page) => reviewPaths.has(page.path));
    const risky = bundle.pages.pages.filter((page) => page.risk_flags.length > 0 || page.freshness_state === "stale");
    return [...new Map([...changed, ...risky].map((page) => [page.id, page])).values()].slice(0, 12);
  }
  if (intent === "evidence") {
    return bundle.pages.pages
      .filter((page) => page.source_refs.length > 0 || page.page_type === "source")
      .slice(0, 12);
  }
  if (intent === "stale") {
    return bundle.pages.pages.filter((page) => page.freshness_state === "stale").slice(0, 12);
  }
  return bundle.pages.pages.slice(0, 12);
}

function mapIntentCopy(intent: MapIntentId, bundle: SnapshotBundle): { label: string; detail: string; tone: "good" | "warn" | "bad" | "info" | "muted"; count: number } {
  const pages = pagesForMapIntent(bundle, intent);
  if (intent === "review") {
    return {
      label: "Approve a change",
      detail: "Start with the content touched by this review and anything nearby that could block approval.",
      tone: pages.length ? "warn" : "good",
      count: pages.length
    };
  }
  if (intent === "evidence") {
    return {
      label: "Check evidence",
      detail: "Open content that has source links or source records before trusting a claim.",
      tone: pages.length ? "info" : "muted",
      count: pages.length
    };
  }
  if (intent === "stale") {
    return {
      label: "Update old content",
      detail: "Find content that needs a new read before it supports a decision.",
      tone: pages.length ? "warn" : "good",
      count: pages.length
    };
  }
  return {
    label: "Find a page",
    detail: "Use the map as navigation: pick a node, follow its route and open the content.",
    tone: "info",
    count: pages.length
  };
}

function mapIntentDecision(intent: MapIntentId, count: number): string {
  if (intent === "review") {
    return count ? "Inspect these items before approving the request." : "No review content is highlighted.";
  }
  if (intent === "evidence") {
    return count ? "Verify the available sources, then decide whether the claim is trustworthy." : "No evidence-backed item is visible.";
  }
  if (intent === "stale") {
    return count ? "Refresh these items before using them as current knowledge." : "No stale item is visible.";
  }
  return count ? "Open a content item and follow its nearby route." : "No content is available in this view.";
}

function mapIntentAction(intent: MapIntentId): string {
  if (intent === "review") return "The highlighted items are added to the decision packet automatically.";
  if (intent === "evidence") return "Open one item, check its evidence links, then add it to the packet if it matters.";
  if (intent === "stale") return "Open one item and decide whether it needs a new source read.";
  return "Pick any node to preview it without changing the packet.";
}

function connectionPages(bundle: SnapshotBundle, selected: PageRecord | undefined, direction: "in" | "out"): PageRecord[] {
  if (!selected) return [];
  const ids = new Set(
    bundle.graph.edges
      .filter((edge) => (direction === "in" ? edge.target === selected.id : edge.source === selected.id))
      .map((edge) => (direction === "in" ? edge.source : edge.target))
  );
  return bundle.pages.pages.filter((page) => ids.has(page.id) || ids.has(page.path)).slice(0, 8);
}

function sourceProofs(bundle: SnapshotBundle, selected: PageRecord | undefined): PageRecord[] {
  if (!selected) return [];
  const refs = new Set(selected.source_refs);
  return bundle.pages.pages
    .filter((page) => refs.has(page.id) || refs.has(page.path) || refs.has(page.title))
    .slice(0, 6);
}

function selectedRoute(bundle: SnapshotBundle, selected: PageRecord | undefined): PageRecord[] {
  if (!selected) return [];
  const byId = new Map(bundle.pages.pages.map((page) => [page.id, page]));
  const byPath = new Map(bundle.pages.pages.map((page) => [page.path, page]));
  const route: PageRecord[] = [selected];
  let cursor: PageRecord | undefined = selected;
  const seen = new Set([selected.id]);
  while (cursor?.moc_parent) {
    const parentPage: PageRecord | undefined = byPath.get(cursor.moc_parent) || byId.get(cursor.moc_parent);
    if (!parentPage || seen.has(parentPage.id)) break;
    route.unshift(parentPage);
    seen.add(parentPage.id);
    cursor = parentPage;
  }
  return route;
}

function pagesFromIds(pages: PageRecord[], ids: string[]): PageRecord[] {
  const byId = new Map<string, PageRecord>();
  pages.forEach((page) => {
    byId.set(page.id, page);
    byId.set(page.path, page);
  });
  return ids.flatMap((id) => {
    const page = byId.get(id);
    return page ? [page] : [];
  });
}

function relatedImpactPages(bundle: SnapshotBundle, pages: PageRecord[]): PageRecord[] {
  const selected = new Set(pages.flatMap((page) => [page.id, page.path]));
  const neighbors = new Set<string>();
  bundle.graph.edges.forEach((edge) => {
    if (selected.has(edge.source)) neighbors.add(edge.target);
    if (selected.has(edge.target)) neighbors.add(edge.source);
  });
  return bundle.pages.pages
    .filter((page) => !selected.has(page.id) && !selected.has(page.path) && (neighbors.has(page.id) || neighbors.has(page.path)))
    .slice(0, 8);
}

function impactReviewText(bundle: SnapshotBundle, pages: PageRecord[]): string {
  const contexts = [...new Set(pages.map((page) => page.context).filter(Boolean))];
  const sourceRefs = [...new Set(pages.flatMap((page) => page.source_refs))];
  const checks = bundle.gates.gates.map((gate) => `- [ ] ${gateCheckLabel(gate.id)}`);
  return [
    "Decision Packet",
    "",
    `Workspace: ${approvalWorkspaceLabel(bundle.git)}`,
    `Approval request: ${bundle.git.proposal.draft_pr_url ? "linked" : gateStatusLabel(bundle.git.proposal.human_gate_state)}`,
    `Selected content: ${pages.length} item(s)`,
    `Areas touched: ${contexts.length ? humanList(contexts) : "none"}`,
    `Evidence links: ${sourceRefs.length}`,
    "",
    "Content to inspect:",
    ...pages.map((page) => `- ${page.title}: ${pageMetaLabel(page)}; ${evidenceLabel(page)}`),
    "",
    "Checks to run before approval:",
    ...(checks.length ? checks : ["- [ ] No review checks available in this view."]),
    "",
    "Human decision: approve, request changes, or ask for more evidence in the review request.",
    "",
    "Technical references:",
    ...pages.map((page) => `- ${page.path}`)
  ].join("\n");
}

function MapIntentPanel({
  bundle,
  activeIntent,
  onChoose,
  onSelect
}: {
  bundle: SnapshotBundle;
  activeIntent: MapIntentId;
  onChoose: (intent: MapIntentId) => void;
  onSelect: (id: string) => void;
}) {
  const activePages = pagesForMapIntent(bundle, activeIntent);
  const activeCopy = mapIntentCopy(activeIntent, bundle);
  return (
    <section className="panel mapIntentPanel">
      <div className="panelHeader">
        <h2>Use The Map To</h2>
        <StatusPill tone={activeCopy.tone}>{activeCopy.count} highlighted</StatusPill>
      </div>
      <div className="mapDecisionStrip" aria-label="Current map decision">
        <div>
          <span>Current task</span>
          <strong>{activeCopy.label}</strong>
          <p>{mapIntentDecision(activeIntent, activePages.length)}</p>
        </div>
        <div>
          <span>How to use it</span>
          <strong>{activePages.length ? `${activePages.length} item(s)` : "Nothing queued"}</strong>
          <p>{mapIntentAction(activeIntent)}</p>
        </div>
      </div>
      <div className="intentButtons" aria-label="Map work modes">
        {MAP_INTENTS.map((intent) => {
          const copy = mapIntentCopy(intent, bundle);
          return (
            <button
              aria-pressed={activeIntent === intent}
              className={activeIntent === intent ? "intentButton active" : "intentButton"}
              onClick={() => onChoose(intent)}
              key={intent}
              type="button"
            >
              <strong>{copy.label}</strong>
              <span>{copy.detail}</span>
              <StatusPill tone={copy.tone}>{copy.count}</StatusPill>
            </button>
          );
        })}
      </div>
      <div className="intentPages" aria-label="Highlighted map pages">
        {activePages.slice(0, 6).map((page) => (
          <button className="textButton" onClick={() => onSelect(page.id)} title={page.path} key={page.id}>
            {page.title}
          </button>
        ))}
        {activePages.length === 0 && <p>No content matches this map mode in the current view.</p>}
      </div>
    </section>
  );
}

function PageActionDrawer({
  bundle,
  selected,
  isBundled,
  onSelect,
  onToggleBundle,
  onRun
}: {
  bundle: SnapshotBundle;
  selected: PageRecord | undefined;
  isBundled: boolean;
  onSelect: (id: string) => void;
  onToggleBundle: (id: string) => void;
  onRun: (action: ActionCard) => void;
}) {
  const inbound = connectionPages(bundle, selected, "in");
  const outbound = connectionPages(bundle, selected, "out");
  const related = [...new Map([...inbound, ...outbound].map((page) => [page.id, page])).values()].slice(0, 8);
  const proofs = sourceProofs(bundle, selected);
  const route = selectedRoute(bundle, selected);
  const graphAction = bundle.actions.actions.find((action) => action.id === "graph-check");
  const reviewAction = bundle.actions.actions.find((action) => action.id === "review-local-changes");
  if (!selected) return null;
  return (
    <section className="panel pageActionDrawer">
      <div className="panelHeader">
        <h2>Selected Item</h2>
        <StatusPill tone={selected.freshness_state === "fresh" ? "good" : selected.freshness_state === "stale" ? "warn" : "muted"}>
          {freshnessLabel(selected.freshness_state)}
        </StatusPill>
      </div>
      <div className="drawerLead">
        <div>
          <h3>{selected.title}</h3>
          <p>{selected.summary || "No summary in this view."}</p>
        </div>
        <a className="secondaryButton" href={`/pages/${encodeURIComponent(selected.id)}`} title="Open page cockpit">
          <ExternalLink size={16} />
          <span>Open page</span>
        </a>
      </div>
      <dl className="kv">
        <dt>Decision</dt>
        <dd>{pageDecisionLabel(selected)}</dd>
        <dt>Evidence</dt>
        <dd>{evidenceLabel(selected)}</dd>
        <dt>Impact</dt>
        <dd>{related.length ? `${related.length} nearby item(s)` : "No nearby content highlighted."}</dd>
        <dt>Last update</dt>
        <dd>{updatedLabel(selected.updated_at)}</dd>
      </dl>
      <details className="auditDetails">
        <summary>Technical address</summary>
        <code>{selected.path}</code>
      </details>
      <div className="routeRail" aria-label="Route from root to selected page">
        {route.map((page) => (
          <button key={page.id} onClick={() => onSelect(page.id)} title={page.path}>
            {page.title}
          </button>
        ))}
      </div>
      <div className="drawerGrid">
        <div>
          <h3>Evidence Links</h3>
          <ul className="plainList compactList">
            {proofs.map((page) => (
              <li key={page.id}><button className="textButton" onClick={() => onSelect(page.id)}>{page.title}</button></li>
            ))}
            {proofs.length === 0 && <li>{selected.source_refs.length ? `${selected.source_refs.length} recorded evidence link(s). Open technical address for exact ids.` : "No evidence links listed."}</li>}
          </ul>
        </div>
        <div>
          <h3>Related Content</h3>
          <ul className="plainList compactList">
            {related.map((page) => (
              <li key={page.id}><button className="textButton" onClick={() => onSelect(page.id)}>{page.title}</button></li>
            ))}
            {related.length === 0 && <li>No nearby content in this view.</li>}
          </ul>
        </div>
      </div>
      <div className="buttonCluster">
        <button className={isBundled ? "secondaryButton active" : "secondaryButton"} onClick={() => onToggleBundle(selected.id)} title="Toggle impact review bundle">
          <ListChecks size={16} />
          <span>{isBundled ? "Remove from packet" : "Add to decision packet"}</span>
        </button>
        {graphAction && <button className="secondaryButton" onClick={() => onRun(graphAction)}><Search size={16} /><span>Check map</span></button>}
        {reviewAction && <button className="secondaryButton" onClick={() => onRun(reviewAction)}><GitBranch size={16} /><span>Review changes</span></button>}
      </div>
    </section>
  );
}

function ImpactBundlePanel({
  bundle,
  pages,
  onSelect,
  onRemove,
  onClear,
  onRun
}: {
  bundle: SnapshotBundle;
  pages: PageRecord[];
  onSelect: (id: string) => void;
  onRemove: (id: string) => void;
  onClear: () => void;
  onRun: (action: ActionCard) => void;
}) {
  const contexts = [...new Set(pages.map((page) => page.context).filter(Boolean))];
  const sourceRefs = [...new Set(pages.flatMap((page) => page.source_refs))];
  const staleCount = pages.filter((page) => page.freshness_state === "stale").length;
  const related = relatedImpactPages(bundle, pages);
  const reviewText = impactReviewText(bundle, pages);
  const actions = bundle.actions.actions.filter((action) => ["graph-check", "review-local-changes", "pr-summary"].includes(action.id));
  return (
    <section className="panel impactBundlePanel" aria-label="Decision Packet">
      <div className="panelHeader">
        <h2>Decision Packet</h2>
        <StatusPill tone={pages.length ? "info" : "muted"}>{pages.length} pages</StatusPill>
      </div>
      <div className="bundleMetrics" aria-label="Impact bundle metrics">
        <Stat icon={<FileText size={18} />} label="Areas" value={contexts.length} tone="info" />
        <Stat icon={<Clock3 size={18} />} label="Needs refresh" value={staleCount} tone={staleCount ? "warn" : "good"} />
        <Stat icon={<Search size={18} />} label="Evidence links" value={sourceRefs.length} tone={sourceRefs.length ? "info" : "muted"} />
        <Stat icon={<GitPullRequest size={18} />} label="Approval" value={gateStatusLabel(bundle.git.proposal.human_gate_state)} tone={bundle.git.proposal.is_proposal_branch ? "warn" : "info"} />
      </div>
      <div className="impactGrid">
        <div>
          <div className="bundleSectionHeader">
            <h3>Selected Content</h3>
            <button className="textButton" onClick={onClear} disabled={!pages.length}>Clear</button>
          </div>
          <div className="bundleRows">
            {pages.map((page) => (
              <article className="bundleRow" key={page.id}>
                <button className="textButton bundleTitle" onClick={() => onSelect(page.id)} title={page.path}>{page.title}</button>
                <span>{pageMetaLabel(page)}</span>
                <StatusPill tone={pageStatusTone(page)}>{evidenceLabel(page)}</StatusPill>
                <button className="textButton" onClick={() => onRemove(page.id)}>Remove</button>
              </article>
            ))}
            {pages.length === 0 && <p>No content selected.</p>}
          </div>
          {related.length > 0 && (
            <>
              <h3>Nearby Content</h3>
              <ul className="plainList compactList">
                {related.map((page) => (
                  <li key={page.id}><button className="textButton" onClick={() => onSelect(page.id)}>{page.title}</button></li>
                ))}
              </ul>
            </>
          )}
        </div>
        <div>
          <h3>Decision Summary</h3>
          <ul className="plainList compactList decisionSummaryList">
            <li>{pages.length ? `${pages.length} content item(s) selected for review.` : "No content selected yet."}</li>
            <li>{sourceRefs.length ? `${sourceRefs.length} evidence link(s) are available.` : "No evidence links are available in the current selection."}</li>
            <li>{staleCount ? `${staleCount} selected item(s) need refresh.` : "Selected content is not stale."}</li>
            <li>{related.length ? `${related.length} nearby item(s) may be affected.` : "No nearby content is highlighted."}</li>
          </ul>
          <details className="auditDetails">
            <summary>Copyable decision packet</summary>
            <pre className="bundlePreview">{reviewText}</pre>
          </details>
          <div className="buttonCluster">
            {actions.map((action) => (
              <button className="secondaryButton" key={action.id} onClick={() => onRun(action)} title={actionReason(action)}>
                {action.id === "pr-summary" ? <GitPullRequest size={16} /> : <ListChecks size={16} />}
                <span>{actionTitle(action)}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function KnowledgeExplorer({
  bundle,
  selectedPageId,
  bundledPageIds,
  search,
  onSearch,
  onSelect,
  onToggleBundle,
  onRun
}: {
  bundle: SnapshotBundle;
  selectedPageId: string;
  bundledPageIds: string[];
  search: string;
  onSearch: (value: string) => void;
  onSelect: (id: string) => void;
  onToggleBundle: (id: string) => void;
  onRun: (action: ActionCard) => void;
}) {
  const results = useMemo(
    () => bundle.pages.pages.filter((page) => pageMatches(page, search)).slice(0, 12),
    [bundle.pages.pages, search]
  );
  const bundledIds = useMemo(() => new Set(bundledPageIds), [bundledPageIds]);
  const selected = pageById(bundle.pages.pages, selectedPageId || results[0]?.id);
  const handleResultClick = (event: MouseEvent<HTMLButtonElement>, page: PageRecord) => {
    if (event.shiftKey) {
      onToggleBundle(page.id);
      return;
    }
    onSelect(page.id);
  };
  return (
    <div className="knowledgeGrid">
      <section className="panel searchPanel">
        <div className="panelHeader">
          <h2>Explore Content</h2>
          <StatusPill tone="info">{results.length}</StatusPill>
        </div>
        <label className="field">
          <span>Find content</span>
          <input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="title, area, type, evidence" />
        </label>
        <div className="searchResults" role="listbox" aria-label="Content search results">
          {results.map((page) => (
            <button
              className={`searchResult${selected?.id === page.id ? " active" : ""}${bundledIds.has(page.id) || bundledIds.has(page.path) ? " bundled" : ""}`}
              key={page.id}
              onClick={(event) => handleResultClick(event, page)}
              title={page.path}
            >
              <span>{page.title}</span>
              <small>{pageMetaLabel(page)} · {evidenceLabel(page)}</small>
            </button>
          ))}
          {results.length === 0 && <p>No content matched the current search.</p>}
        </div>
      </section>
      <PageActionDrawer
        bundle={bundle}
        selected={selected}
        isBundled={Boolean(selected && (bundledIds.has(selected.id) || bundledIds.has(selected.path)))}
        onSelect={onSelect}
        onToggleBundle={onToggleBundle}
        onRun={onRun}
      />
    </div>
  );
}

function OpsView({ bundle, onRun }: { bundle: SnapshotBundle; onRun: (action: ActionCard) => void }) {
  const stale = bundle.freshness.summary.stale ?? 0;
  const fresh = bundle.freshness.summary.fresh ?? 0;
  const changed = bundle.git.worktree.changed_files.length;
  const [search, setSearch] = useState("");
  const [selectedPageId, setSelectedPageId] = useState(bundle.pages.pages[0]?.id || "");
  const [reviewPageIds, setReviewPageIds] = useState<string[]>([]);
  const [mapIntent, setMapIntent] = useState<MapIntentId>("review");
  const reviewPages = useMemo(() => pagesFromIds(bundle.pages.pages, reviewPageIds), [bundle.pages.pages, reviewPageIds]);
  const intentPages = useMemo(() => pagesForMapIntent(bundle, mapIntent), [bundle, mapIntent]);
  const activeMapIntent = useMemo(() => mapIntentCopy(mapIntent, bundle), [bundle, mapIntent]);
  const toggleReviewPage = (id: string) => {
    setReviewPageIds((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  };
  const clearReviewPages = () => setReviewPageIds([]);
  const chooseMapIntent = (intent: MapIntentId) => {
    const pages = pagesForMapIntent(bundle, intent);
    setMapIntent(intent);
    setSearch("");
    if (pages[0]) setSelectedPageId(pages[0].id);
    if (intent !== "browse") setReviewPageIds(pages.slice(0, 8).map((page) => page.id));
  };
  const highlightedPageIds = useMemo(
    () => {
      const searchHits = bundle.pages.pages.filter((page) => pageMatches(page, search)).slice(0, 16).flatMap((page) => [page.id, page.path]);
      const bundleHits = reviewPages.flatMap((page) => [page.id, page.path]);
      const intentHits = intentPages.flatMap((page) => [page.id, page.path]);
      return [...new Set([...searchHits, ...bundleHits, ...intentHits])];
    },
    [bundle.pages.pages, intentPages, reviewPages, search]
  );
  return (
    <main className="workspace">
      <section className="heroBand">
        <div className="heroCopy">
          <StatusPill tone={bundle.git.proposal.is_proposal_branch ? "warn" : "good"}>{gitGateLabel(bundle.git)}</StatusPill>
          <h1>What needs attention?</h1>
          <p>{bundle.operations.title} · {bundle.manifest.repo.repo_id} · updated {updatedLabel(bundle.manifest.generated_at)}</p>
        </div>
        <SystemScene
          nodes={bundle.graph.nodes}
          git={bundle.git}
          selectedPageId={selectedPageId}
          highlightedPageIds={highlightedPageIds}
          intent={{ label: activeMapIntent.label, detail: activeMapIntent.detail, count: activeMapIntent.count }}
          onNodeSelect={setSelectedPageId}
        />
      </section>
      <section className="statGrid" aria-label="Operational summary">
        <Stat icon={<BadgeCheck size={18} />} label="Up to date" value={fresh} tone="good" />
        <Stat icon={<Clock3 size={18} />} label="Needs refresh" value={stale} tone={stale ? "warn" : "good"} />
        <Stat icon={<GitBranch size={18} />} label="Workspace" value={workspaceDisplayLabel(bundle.git)} tone={bundle.git.proposal.is_proposal_branch ? "warn" : "info"} />
        <Stat icon={<ListChecks size={18} />} label="Review items" value={changed} tone={changed ? "warn" : "good"} />
      </section>
      <MapIntentPanel bundle={bundle} activeIntent={mapIntent} onChoose={chooseMapIntent} onSelect={setSelectedPageId} />
      <KnowledgeExplorer
        bundle={bundle}
        selectedPageId={selectedPageId}
        bundledPageIds={reviewPageIds}
        search={search}
        onSearch={setSearch}
        onSelect={setSelectedPageId}
        onToggleBundle={toggleReviewPage}
        onRun={onRun}
      />
      <ImpactBundlePanel
        bundle={bundle}
        pages={reviewPages}
        onSelect={setSelectedPageId}
        onRemove={toggleReviewPage}
        onClear={clearReviewPages}
        onRun={onRun}
      />
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
            {bundle.operations.sections.length === 0 && <li>No operational notes in this view.</li>}
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

function prHandoffTitle(bundle: SnapshotBundle): string {
  const theme = bundle.git.proposal.theme || bundle.manifest.repo.repo_id;
  return `Review ${theme}`;
}

function prHandoffBody(bundle: SnapshotBundle): string {
  const files = bundle.diff.files.slice(0, 20);
  const changedLines = files.length
    ? files.map((file) => `- ${file.path} (${changeStatusLabel(file.status || "changed")}, ${file.additions} added / ${file.deletions} removed, ${file.category})`)
    : ["- No changed content in the current view."];
  const gateLines = bundle.gates.gates.length
    ? bundle.gates.gates.map((gate) => `- [ ] ${gate.argv.join(" ")}`)
    : ["- [ ] No automated checks listed in the current view."];
  const riskHints = [...new Set(files.flatMap((file) => file.risk_hints))];
  return [
    "## Summary",
    `- Workspace: ${workspaceDisplayLabel(bundle.git)}`,
    `- Compared with: ${bundle.diff.compare.base_ref || bundle.git.default_branch}`,
    `- Content: ${bundle.diff.summary.file_count} total, ${bundle.diff.summary.branch_file_count} saved for review, ${bundle.diff.summary.working_tree_file_count} still local`,
    `- Privacy review: ${bundle.diff.summary.privacy_review_required ? "required" : "not flagged"}`,
    `- Risk notes: ${riskHints.length ? riskHints.map(riskHintLabel).join(", ") : "none"}`,
    "",
    "## Content Changed",
    ...changedLines,
    "",
    "## Automated Checks",
    ...gateLines,
    "",
    "## Approval Checklist",
    "- [ ] Conceptual review completed by a human",
    "- [ ] Privacy/publication boundary checked",
    "- [ ] Exact content changes inspected",
    "- [ ] Final merge/approval handled outside the cockpit"
  ].join("\n");
}

function gateStepTone(status: string): "good" | "warn" | "bad" | "info" | "muted" {
  if (["ready", "published", "linked", "clean", "clear"].includes(status)) return "good";
  if (["blocked", "outside_flow"].includes(status)) return "bad";
  if (["needs_publish", "dirty", "not_run", "not_opened", "needs_review"].includes(status)) return "warn";
  if (["empty"].includes(status)) return "muted";
  return "info";
}

function approvalRiskHints(bundle: SnapshotBundle): string[] {
  return [...new Set(bundle.diff.files.flatMap((file) => file.risk_hints))];
}

function gateStatusTone(status: string): "good" | "warn" | "bad" | "info" | "muted" {
  const value = status.toLowerCase();
  if (["pass", "passed", "success", "ok"].includes(value)) return "good";
  if (["fail", "failed", "error", "blocked"].includes(value)) return "bad";
  if (["not_run", "pending", "unknown"].includes(value)) return "warn";
  return "info";
}

function approvalDecision(bundle: SnapshotBundle): { label: string; detail: string; tone: "good" | "warn" | "bad" | "info" | "muted" } {
  const git = bundle.git;
  if (!git.available) return { label: "Cannot decide yet", detail: "Workspace state is unavailable in this view.", tone: "bad" };
  if (!git.proposal.is_proposal_branch && git.current_branch !== git.default_branch) {
    return { label: "Outside the approval flow", detail: "Move the work into a review workspace before asking for approval.", tone: "bad" };
  }
  if (git.current_branch === git.default_branch) {
    return { label: "Approved content view", detail: "You are looking at approved content. Refresh it only after an external approval is merged.", tone: git.worktree.clean ? "good" : "warn" };
  }
  if (bundle.diff.summary.privacy_review_required) {
    return { label: "Needs privacy review", detail: "Inspect the changed content and risk notes before opening the approval request.", tone: "warn" };
  }
  if (!git.proposal.draft_pr_url) {
    return { label: "Prepare the approval request", detail: "The change exists locally or remotely, but no approval request is linked in this view.", tone: "warn" };
  }
  if (git.proposal.human_gate_state === "draft") {
    return { label: "Ready for human review", detail: "Open the draft request, inspect the packet, then mark it ready outside the cockpit.", tone: "info" };
  }
  if (git.proposal.human_gate_state === "ready_for_review") {
    return { label: "Waiting on human approval", detail: "The review request is the human gate; merge remains external to the base cockpit.", tone: "info" };
  }
  if (git.proposal.human_gate_state === "merged") {
    return { label: "Approved externally", detail: "Switch to the approved branch and fast-forward sync the local checkout.", tone: "good" };
  }
  return { label: "Review the packet", detail: "Use the evidence, checks and approval request below to decide the next step.", tone: "info" };
}

function approvalWorkspaceLabel(git: SnapshotBundle["git"]): string {
  if (git.proposal.is_proposal_branch) return git.proposal.theme ? `Review workspace: ${git.proposal.theme}` : "Review workspace";
  if (git.current_branch === git.default_branch) return "Approved content workspace";
  return git.current_branch ? "Current workspace outside the normal approval flow" : "Workspace not detected";
}

function approvalSharedCopyLabel(git: SnapshotBundle["git"]): string {
  if (!git.upstream.name && !git.upstream.remote) return "No shared copy is configured.";
  if (git.upstream.ahead > 0) return `${git.upstream.ahead} local update(s) still need sending.`;
  if (git.upstream.behind > 0) return `${git.upstream.behind} approved update(s) need pulling.`;
  return "Shared copy is up to date.";
}

function ApprovalInbox({
  bundle,
  onRun
}: {
  bundle: SnapshotBundle;
  onRun: (action: ActionCard) => void;
}) {
  const checks = reviewChecklist(bundle);
  const decision = approvalDecision(bundle);
  const risks = approvalRiskHints(bundle);
  const prAction = bundle.actions.actions.find((action) => action.id === "pr-summary");
  const gateAction = bundle.actions.actions.find((action) => action.id === "run-honesty-gates");
  const reviewAction = bundle.actions.actions.find((action) => action.id === "review-local-changes");
  const changedFiles = bundle.diff.files.slice(0, 6);
  const primaryChangedFiles = changedFiles.slice(0, 3);
  const changedAreas = [...new Set(bundle.diff.files.map((file) => changeAreaLabel(file.category)).filter(Boolean))].slice(0, 8);
  const riskyFiles = bundle.diff.files.filter((file) => file.risk_hints.length > 0).slice(0, 6);
  const requestUrl = bundle.git.proposal.draft_pr_url;
  const checkTone = gateStatusTone(bundle.gates.status);
  const checkReady = checkTone === "good";
  const checkLabels = bundle.gates.gates.map((gate) => gateCheckLabel(gate.id));
  const changedFileLine = primaryChangedFiles.length
    ? `${primaryChangedFiles.map((file) => `${file.path} (${changeStatusLabel(file.status || "changed")})`).join(", ")}${
        bundle.diff.files.length > primaryChangedFiles.length ? ` and ${bundle.diff.files.length - primaryChangedFiles.length} more` : ""
      }`
    : "No changed files listed.";

  return (
    <section className="approvalInbox" aria-label="Approval inbox">
      <div className="approvalInboxHeader">
        <div>
          <StatusPill tone={decision.tone}>{decision.label}</StatusPill>
          <h1>Approval Inbox</h1>
          <p>{decision.detail}</p>
        </div>
        <div className="inboxCounters" aria-label="Approval summary">
          <span><strong>{bundle.diff.summary.file_count}</strong> changed</span>
          <span><strong>{risks.length}</strong> risk notes</span>
          <span><strong>{bundle.gates.gates.length}</strong> checks</span>
          <span><strong>{requestUrl ? "1" : "0"}</strong> request</span>
        </div>
      </div>

      <div className="approvalQueue">
        <article className="approvalItem">
          <div className="approvalItemHeader">
            <span className="stageIndex">1</span>
            <div>
              <h2>Changed content</h2>
              <p>Decide whether the scope of this review is clear enough to approve.</p>
            </div>
            <StatusPill tone={bundle.diff.summary.file_count ? "warn" : "good"}>
              {bundle.diff.summary.file_count ? "needs review" : "clear"}
            </StatusPill>
          </div>
          <dl className="approvalFacts">
            <dt>Decision</dt>
            <dd>{bundle.diff.summary.file_count ? "Review whether these changes belong in one approval request." : "No changed content needs approval in this view."}</dd>
            <dt>Primary items</dt>
            <dd>{changedFileLine}</dd>
            <dt>What to check</dt>
            <dd>{changedAreas.length ? humanList(changedAreas) : "No changed content listed."}</dd>
          </dl>
          <details className="approvalItemDetails">
            <summary>Show changed items</summary>
            <ul className="plainList compactList">
              {changedFiles.map((file) => (
                <li key={`${file.status}-${file.path}`}>
                  {file.path} · {changeStatusLabel(file.status || "changed")} · {file.additions} added / {file.deletions} removed
                </li>
              ))}
              {bundle.diff.files.length > changedFiles.length && <li>{bundle.diff.files.length - changedFiles.length} more item(s) in exact evidence.</li>}
            </ul>
          </details>
          <div className="approvalItemActions">
            {prAction && <ActionButton action={prAction} onRun={onRun} />}
            {reviewAction && <ActionButton action={reviewAction} onRun={onRun} />}
          </div>
        </article>

        <article className="approvalItem">
          <div className="approvalItemHeader">
            <span className="stageIndex">2</span>
            <div>
              <h2>Risk and privacy</h2>
              <p>Decide whether anything here blocks approval or public publication later.</p>
            </div>
            <StatusPill tone={bundle.diff.summary.privacy_review_required || risks.length ? "warn" : "good"}>
              {bundle.diff.summary.privacy_review_required || risks.length ? "needs review" : "clear"}
            </StatusPill>
          </div>
          <dl className="approvalFacts">
            <dt>Decision</dt>
            <dd>{bundle.diff.summary.privacy_review_required || risks.length ? "Inspect and resolve these notes before asking for approval." : "No privacy or risk blocker is visible."}</dd>
            <dt>Risk notes</dt>
            <dd>{risks.length ? risks.map(riskHintLabel).join(", ") : "No explicit risk notes."}</dd>
            <dt>Privacy</dt>
            <dd>{bundle.diff.summary.privacy_review_required ? "Review required before approval." : "No privacy flag in the changed content."}</dd>
          </dl>
          <details className="approvalItemDetails">
            <summary>Show files with risk notes</summary>
            <ul className="plainList compactList">
              {riskyFiles.map((file) => (
                <li key={file.path}>{file.path} · {file.risk_hints.map(riskHintLabel).join(", ")}</li>
              ))}
              {riskyFiles.length === 0 && <li>No changed files carry explicit risk notes.</li>}
            </ul>
          </details>
        </article>

        <article className="approvalItem">
          <div className="approvalItemHeader">
            <span className="stageIndex">3</span>
            <div>
              <h2>Checks</h2>
              <p>Decide whether automated validation is strong enough for a human review.</p>
            </div>
            <StatusPill tone={checkTone}>{gateStatusLabel(bundle.gates.status)}</StatusPill>
          </div>
          <dl className="approvalFacts">
            <dt>Decision</dt>
            <dd>{checkReady ? "Automated validation is ready for human review." : "Run or inspect checks before approval."}</dd>
            <dt>Available checks</dt>
            <dd>{bundle.gates.gates.length} check(s): {humanList(checkLabels)}.</dd>
            <dt>Checklist</dt>
            <dd>{checks.filter((check) => check.ok).length}/{checks.length} approval checklist item(s) ready.</dd>
          </dl>
          <details className="approvalItemDetails">
            <summary>Show approval checklist</summary>
            <ul className="plainList compactList">
              {checks.map((check) => (
                <li key={check.label}>{check.ok ? "Ready" : "Needs work"} · {check.label}</li>
              ))}
            </ul>
          </details>
          <div className="approvalItemActions">
            {gateAction && <ActionButton action={gateAction} onRun={onRun} />}
          </div>
        </article>

        <article className="approvalItem">
          <div className="approvalItemHeader">
            <span className="stageIndex">4</span>
            <div>
              <h2>Approval request</h2>
              <p>Decide whether the request is ready for the final human decision.</p>
            </div>
            <StatusPill tone={requestUrl ? "info" : "warn"}>
              {requestUrl ? "linked" : "not opened"}
            </StatusPill>
          </div>
          <dl className="approvalFacts">
            <dt>Decision</dt>
            <dd>{requestUrl ? "Use the linked request as the human gate." : "Open or link a request before final approval."}</dd>
            <dt>Workspace</dt>
            <dd>{approvalWorkspaceLabel(bundle.git)}</dd>
            <dt>Shared copy</dt>
            <dd>{approvalSharedCopyLabel(bundle.git)}</dd>
          </dl>
          <div className="approvalItemActions">
            {requestUrl && (
              <a className="secondaryButton" href={requestUrl} title="Open review request">
                <ExternalLink size={16} />
                <span>Open request</span>
              </a>
            )}
          </div>
        </article>
      </div>
    </section>
  );
}

function prGateSteps(bundle: SnapshotBundle): { label: string; status: string; detail: string }[] {
  const git = bundle.git;
  const published = Boolean(git.upstream.name) && git.upstream.ahead === 0;
  return [
    {
      label: "Review workspace",
      status: git.proposal.is_proposal_branch ? "ready" : git.current_branch === git.default_branch ? "approved" : "outside_flow",
      detail: workspaceDisplayLabel(git)
    },
    {
      label: "Send for review",
      status: published ? "published" : git.proposal.is_proposal_branch ? "needs_publish" : "blocked",
      detail: published ? sharedCopyLabel(git) : "not sent"
    },
    {
      label: "Local edits",
      status: git.worktree.clean ? "clean" : "dirty",
      detail: `${git.worktree.changed_files.length} changed item(s)`
    },
    {
      label: "Checks",
      status: bundle.gates.status,
      detail: `${bundle.gates.gates.length} automated check(s)`
    },
    {
      label: "Review request",
      status: git.proposal.draft_pr_url ? "linked" : git.proposal.human_gate_state || "not_opened",
      detail: git.proposal.draft_pr_url || "not linked in this view"
    },
    {
      label: "Human decision",
      status: git.proposal.human_gate_state,
      detail: "Final approval happens outside the cockpit"
    }
  ];
}

function PrHandoffPanel({
  bundle,
  onWorkflow
}: {
  bundle: SnapshotBundle;
  onWorkflow: (operation: string, payload?: Record<string, unknown>, dryRun?: boolean) => void;
}) {
  const generatedTitle = useMemo(() => prHandoffTitle(bundle), [bundle]);
  const generatedBody = useMemo(() => prHandoffBody(bundle), [bundle]);
  const steps = useMemo(() => prGateSteps(bundle), [bundle]);
  const [title, setTitle] = useState(generatedTitle);
  const [body, setBody] = useState(generatedBody);
  const [execute, setExecute] = useState(false);
  const dryRun = !execute;
  const resetGenerated = () => {
    setTitle(generatedTitle);
    setBody(generatedBody);
  };

  return (
    <section className="panel prHandoffPanel">
      <div className="panelHeader">
        <h2>Prepare Approval Request</h2>
        <label className="toggleControl">
          <input type="checkbox" checked={execute} onChange={(event) => setExecute(event.target.checked)} />
          <span>Allow online send</span>
        </label>
      </div>
      <div className="gateTrack" aria-label="Human approval state">
        {steps.map((step) => (
          <article className={`gateStep gateStep-${gateStepTone(step.status)}`} key={step.label}>
            <strong>{step.label}</strong>
            <StatusPill tone={gateStepTone(step.status)}>{gateStatusLabel(step.status)}</StatusPill>
            <span>{step.detail}</span>
          </article>
        ))}
      </div>
      <div className="handoffGrid">
        <label className="field">
          <span>Review request title</span>
          <input value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>
        <button className="secondaryButton" onClick={resetGenerated} title="Regenerate these review notes from the current view">
          <RefreshCw size={16} />
          <span>Regenerate</span>
        </button>
        <label className="field wide">
          <span>Decision notes for the review request</span>
          <textarea className="handoffBody" value={body} onChange={(event) => setBody(event.target.value)} rows={13} />
        </label>
        {bundle.git.proposal.draft_pr_url && (
          <a className="secondaryButton wide" href={bundle.git.proposal.draft_pr_url} title="Open review request">
            <ExternalLink size={16} />
            <span>Open request</span>
          </a>
        )}
        <div className="buttonCluster wide">
          <button className="secondaryButton" onClick={() => onWorkflow("publish_proposal", {}, dryRun)} title="Send the current review workspace">
            <RefreshCw size={16} />
            <span>Send changes</span>
          </button>
          <button className="secondaryButton" onClick={() => onWorkflow("open_draft_pr", { title, body }, dryRun)} title="Create a draft review request">
            <GitPullRequest size={16} />
            <span>Open review draft</span>
          </button>
          <button className="secondaryButton" onClick={() => onWorkflow("update_draft_pr", { title, body }, dryRun)} title="Update the current review request body">
            <FileText size={16} />
            <span>Update Review Request</span>
          </button>
        </div>
      </div>
    </section>
  );
}

function syncTone(bundle: SnapshotBundle): "good" | "warn" | "bad" | "info" | "muted" {
  const git = bundle.git;
  if (!git.available) return "bad";
  if (git.current_branch === git.default_branch) return git.worktree.clean ? "good" : "warn";
  if (git.proposal.human_gate_state === "merged") return "info";
  return "muted";
}

function syncStatus(bundle: SnapshotBundle): string {
  const git = bundle.git;
  if (!git.available) return "git unavailable";
  if (git.current_branch === git.default_branch) return git.worktree.clean ? "ready" : "local changes";
  if (git.proposal.human_gate_state === "merged") return "approved externally";
  return "external review";
}

function SyncMainPanel({
  bundle,
  onWorkflow
}: {
  bundle: SnapshotBundle;
  onWorkflow: (operation: string, payload?: Record<string, unknown>, dryRun?: boolean) => void;
}) {
  const [execute, setExecute] = useState(false);
  const git = bundle.git;
  const onDefaultBranch = git.current_branch === git.default_branch;
  const dryRun = !execute;

  return (
    <section className="panel syncPanel">
      <div className="panelHeader">
        <h2>Refresh Approved Content</h2>
        <StatusPill tone={syncTone(bundle)}>{syncStatus(bundle)}</StatusPill>
      </div>
      <div className="syncGrid">
        <dl className="kv">
          <dt>Approved version</dt>
          <dd>{git.default_branch}</dd>
          <dt>Current workspace</dt>
          <dd>{workspaceDisplayLabel(git)}</dd>
          <dt>Online copy</dt>
          <dd>{sharedCopyLabel(git)}</dd>
          <dt>Available updates</dt>
          <dd>{git.upstream.behind}</dd>
          <dt>Local edits</dt>
          <dd>{git.worktree.clean ? "none" : "needs review"}</dd>
        </dl>
        <details className="auditDetails syncCommand">
          <summary>Terminal details</summary>
          <code>git fetch --prune {git.upstream.remote || "origin"}</code>
          <code>git pull --ff-only {git.upstream.remote || "origin"} {git.default_branch}</code>
        </details>
        <label className="toggleControl">
          <input type="checkbox" checked={execute} onChange={(event) => setExecute(event.target.checked)} disabled={!onDefaultBranch} />
          <span>Allow local refresh</span>
        </label>
        <button
          className="secondaryButton wide"
          onClick={() => onWorkflow("sync_main", {}, dryRun)}
          disabled={!onDefaultBranch}
          title={onDefaultBranch ? "Fast-forward the approved local branch" : "Sync is available only from the approved branch"}
        >
          <RefreshCw size={16} />
          <span>Refresh approved</span>
        </button>
      </div>
    </section>
  );
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
  const [message, setMessage] = useState("refine human approval cockpit");
  const [prTitle, setPrTitle] = useState("Refine human approval cockpit");
  const [prBody, setPrBody] = useState("Cockpit update with task-based navigation, evidence checks and approval flow.");
  const [execute, setExecute] = useState(false);
  const dryRun = !execute;

  return (
    <section className="panel workflowPanel">
      <div className="panelHeader">
        <h2>Prepare Local Change</h2>
        <label className="toggleControl">
          <input type="checkbox" checked={execute} onChange={(event) => setExecute(event.target.checked)} />
          <span>Enable local writes</span>
        </label>
      </div>
      <div className="workflowGrid">
        <label className="field">
          <span>Change theme</span>
          <input value={theme} onChange={(event) => setTheme(event.target.value)} />
        </label>
        <div className="buttonCluster">
          <button className="secondaryButton" onClick={() => onWorkflow("list_proposals", {}, false)} title="Show saved review workspaces">
            <ListChecks size={16} />
            <span>List</span>
          </button>
          <button className="secondaryButton" onClick={() => onWorkflow("start_proposal", { theme }, dryRun)} title="Start a review workspace">
            <GitBranch size={16} />
            <span>Start review</span>
          </button>
        </div>
        <label className="field wide">
          <span>Content to include</span>
          <textarea value={paths} onChange={(event) => setPaths(event.target.value)} rows={4} />
        </label>
        <button className="secondaryButton wide" onClick={() => onWorkflow("stage_paths", { paths: splitPathInput(paths) }, dryRun)} title="Include selected changed content">
          <ListChecks size={16} />
          <span>Include selected content</span>
        </button>
        <label className="field">
          <span>Version note</span>
          <input value={message} onChange={(event) => setMessage(event.target.value)} />
        </label>
        <button className="secondaryButton" onClick={() => onWorkflow("commit_proposal", { message }, dryRun)} title="Save a named local version">
          <CheckCircle2 size={16} />
          <span>Save version</span>
        </button>
        <label className="field">
          <span>Review title</span>
          <input value={prTitle} onChange={(event) => setPrTitle(event.target.value)} />
        </label>
        <label className="field">
          <span>Review notes</span>
          <textarea value={prBody} onChange={(event) => setPrBody(event.target.value)} rows={4} />
        </label>
        <div className="buttonCluster wide">
          <button className="secondaryButton" onClick={() => onWorkflow("publish_proposal", {}, dryRun)} title="Send the current review workspace">
            <RefreshCw size={16} />
            <span>Send changes</span>
          </button>
          <button className="secondaryButton" onClick={() => onWorkflow("open_draft_pr", { title: prTitle, body: prBody }, dryRun)} title="Open a review request">
            <GitPullRequest size={16} />
            <span>Open review request</span>
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
  return (
    <main className="workspace">
      <ApprovalInbox bundle={bundle} onRun={onRun} />
      <details className="reviewUtilityDetails">
        <summary>Request editor and exact evidence</summary>
        <PrHandoffPanel bundle={bundle} onWorkflow={onWorkflow} />
        <DiffFilmstrip bundle={bundle} />
        <SyncMainPanel bundle={bundle} onWorkflow={onWorkflow} />
        <GitWorkflowPanel bundle={bundle} onWorkflow={onWorkflow} />
        <section className="panel">
          <div className="panelHeader">
            <h2>Exact Content Changes</h2>
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
            {bundle.git.worktree.changed_files.length === 0 && <p>No local changes in this view.</p>}
          </div>
        </section>
        <section className="panel">
          <div className="panelHeader">
            <h2>Automated Checks</h2>
            <StatusPill tone={gateStatusTone(bundle.gates.status)}>{gateStatusLabel(bundle.gates.status)}</StatusPill>
          </div>
          <ul className="plainList commandList">
            {bundle.gates.gates.map((gate) => (
              <li key={gate.id}>
                <code>{gate.argv.join(" ")}</code>
              </li>
            ))}
          </ul>
        </section>
      </details>
    </main>
  );
}

function healthDecision(
  bundle: SnapshotBundle,
  qualityFlags: number
): { label: string; detail: string; tone: "good" | "warn" | "bad" | "info" | "muted" } {
  const stale = bundle.freshness.summary.stale ?? 0;
  const unknown = bundle.freshness.summary.unknown ?? 0;
  const gateTone = gateStatusTone(bundle.gates.status);
  if (gateTone === "bad") {
    return { label: "Do not rely yet", detail: "A required check is failing. Fix that before trusting or approving this wiki state.", tone: "bad" };
  }
  if (gateTone === "warn") {
    return { label: "Check before relying", detail: "The content can be browsed, but validation has not proved this state yet.", tone: "warn" };
  }
  if (qualityFlags || stale || unknown) {
    return { label: "Usable with review", detail: "The wiki is usable, but some content needs attention before high-confidence decisions.", tone: "warn" };
  }
  return { label: "Ready to trust", detail: "Checks are passing and the current content health signals are clear.", tone: "good" };
}

function HealthView({ bundle, onRun }: { bundle: SnapshotBundle; onRun: (action: ActionCard) => void }) {
  const qualityFlags = qualityFlagCount(bundle);
  const decision = healthDecision(bundle, qualityFlags);
  const fresh = bundle.freshness.summary.fresh ?? 0;
  const stale = bundle.freshness.summary.stale ?? 0;
  const unknown = bundle.freshness.summary.unknown ?? 0;
  const gateAction = bundle.actions.actions.find((action) => action.id === "run-honesty-gates");
  const stalePages = bundle.pages.pages.filter((page) => page.freshness_state === "stale").slice(0, 8);
  const riskPages = bundle.pages.pages.filter((page) => page.risk_flags.length > 0).slice(0, 8);
  const attentionPages = [...new Map([...riskPages, ...stalePages].map((page) => [page.id, page])).values()].slice(0, 10);
  return (
    <main className="workspace">
      <section className="panel healthHero">
        <div className="panelHeader">
          <h1>Wiki Health</h1>
          <StatusPill tone={decision.tone}>{decision.label}</StatusPill>
        </div>
        <p className="panelLead">{decision.detail}</p>
        <div className="healthDecisionGrid" aria-label="Wiki health decision summary">
          <article className="healthDecisionCard">
            <ShieldCheck size={18} />
            <span>Validation</span>
            <strong>{gateStatusLabel(bundle.gates.status)}</strong>
            <p>{bundle.gates.gates.length} local check(s) are available for approval confidence.</p>
            {gateAction && <ActionButton action={gateAction} onRun={onRun} />}
          </article>
          <article className="healthDecisionCard">
            <Clock3 size={18} />
            <span>Freshness</span>
            <strong>{stale ? `${stale} need refresh` : "Current"}</strong>
            <p>{fresh} ready, {unknown} not checked.</p>
          </article>
          <article className="healthDecisionCard">
            <CircleAlert size={18} />
            <span>Review warnings</span>
            <strong>{qualityFlags}</strong>
            <p>{qualityFlags ? "Inspect warnings before relying on affected content." : "No current warning is exposed in this view."}</p>
          </article>
          <article className="healthDecisionCard">
            <Search size={18} />
            <span>Evidence</span>
            <strong>{bundle.sources.sources.length}</strong>
            <p>Evidence source(s) are available to verify content claims.</p>
          </article>
        </div>
      </section>

      <section className="panel">
        <div className="panelHeader">
          <h2>Needs Attention</h2>
          <StatusPill tone={attentionPages.length ? "warn" : "good"}>{attentionPages.length ? `${attentionPages.length} item(s)` : "clear"}</StatusPill>
        </div>
        <div className="healthAttentionList">
          {attentionPages.map((page) => (
            <a className="healthAttentionItem" href={`/pages/${encodeURIComponent(page.id)}`} key={page.id}>
              <div>
                <strong>{page.title}</strong>
                <span>{pageMetaLabel(page)} · {evidenceLabel(page)}</span>
              </div>
              <StatusPill tone={pageStatusTone(page)}>
                {page.risk_flags.length ? "review risk" : freshnessLabel(page.freshness_state)}
              </StatusPill>
            </a>
          ))}
          {attentionPages.length === 0 && <p>No content item needs attention in this view.</p>}
        </div>
      </section>

      <details className="reviewUtilityDetails">
        <summary>Area rollup and exact checks</summary>
        <section className="panel">
          <div className="panelHeader">
            <h2>Area Readiness</h2>
            <StatusPill tone="info">{Object.keys(bundle.freshness.by_context).length} areas</StatusPill>
          </div>
          <div className="contextGrid">
            {Object.entries(bundle.freshness.by_context).map(([context, stats]) => (
              <article className="contextTile" key={context}>
                <h2>{context}</h2>
                <span>ready {stats.fresh ?? 0}</span>
                <span>needs refresh {stats.stale ?? 0}</span>
                <span>not checked {stats.unknown ?? 0}</span>
              </article>
            ))}
          </div>
        </section>
        <section className="panel">
          <div className="panelHeader">
            <h2>Exact Checks</h2>
            <StatusPill tone={gateStatusTone(bundle.gates.status)}>{gateStatusLabel(bundle.gates.status)}</StatusPill>
          </div>
          <ul className="plainList commandList">
            {bundle.gates.gates.map((gate) => (
              <li key={gate.id}>
                <strong>{gateCheckLabel(gate.id)}</strong>
                <details className="auditDetails">
                  <summary>Terminal command</summary>
                  <code>{gate.argv.join(" ")}</code>
                </details>
              </li>
            ))}
          </ul>
        </section>
      </details>
    </main>
  );
}

function sourceResultTone(result: SourceTriageResult | null): "good" | "warn" | "bad" | "muted" {
  if (!result) return "muted";
  if (result.secret_block || result.error) return "bad";
  if ((result.risk_flags || []).length > 0) return "warn";
  return "good";
}

function sourceReadyLabel(result: SourceTriageResult): string {
  if (result.secret_block) return "Blocked by secret";
  if (result.error) return "Needs attention";
  if (result.ok) return "Ready to review";
  return "Needs review";
}

function sourceReadyDetail(result: SourceTriageResult): string {
  if (result.error) return result.error;
  if (result.secret_block) return "Remove access secrets before this source can enter the wiki flow.";
  if ((result.risk_flags || []).length > 0) return "Safe to continue only after the flagged items are reviewed.";
  return "No blocking issue was found in the local triage.";
}

function sourceTypeLabel(value?: string): string {
  const labels: Record<string, string> = {
    file: "Local file",
    url: "Web link",
    markdown: "Markdown note",
    pdf: "PDF document",
    text: "Text document",
    unknown: "Unknown source"
  };
  return labels[value || "unknown"] || (value || "unknown").replaceAll("_", " ");
}

function sourceFoundLabel(value?: boolean | null): string {
  if (value === true) return "Found";
  if (value === false) return "Not found";
  return "Not checked";
}

function sourceRiskLabel(value: string): string {
  const labels: Record<string, string> = {
    secret: "Access secret",
    secret_block: "Access secret",
    pii: "Personal data",
    public_boundary: "Public boundary",
    missing_context: "Missing area",
    unresolved_target: "Unclear destination"
  };
  return labels[value] || value.replaceAll("_", " ");
}

function sourceRiskSummary(result: SourceTriageResult): string {
  if (result.secret_block) return "Blocked";
  if ((result.risk_flags || []).length > 0) return `${result.risk_flags?.length || 0} flag(s)`;
  return "No flags";
}

function sourceFindingLabel(finding: SourceFinding): string {
  return `${sourceRiskLabel(finding.category)} · ${finding.kind.replaceAll("_", " ")}`;
}

function stageTone(stage: IngestionStage): "good" | "warn" | "bad" | "info" | "muted" {
  if (stage.status === "complete") return "good";
  if (stage.status === "ready") return "info";
  if (stage.status === "warning" || stage.status === "waiting") return "warn";
  if (stage.status === "blocked") return "bad";
  return "muted";
}

function stageStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    complete: "done",
    ready: "ready",
    waiting: "waiting",
    blocked: "blocked",
    warning: "needs review"
  };
  return labels[status] || status.replaceAll("_", " ");
}

function runnableStage(stage: IngestionStage): boolean {
  return Boolean(stage.command) && stage.status !== "blocked";
}

function stageButtonLabel(stage: IngestionStage, executeWrites: boolean, busyStep: string): string {
  if (busyStep === stage.id) return "Running";
  if (stage.writes) return executeWrites ? "Apply" : "Preview";
  return "Review";
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
        <h3>Add Checklist</h3>
        <StatusPill tone={plan.ok ? "good" : "bad"}>{plan.ok ? "ready to start" : "blocked"}</StatusPill>
      </div>
      <p className="panelLead">Preview each step locally first. Turn on review writes only when this source should be added to the review workspace.</p>
      <div className="pipelineRail" aria-label="Add knowledge flow">
        {plan.stages.map((stage, index) => (
          <article className={`pipelineStage stage-${stage.status}`} key={stage.id}>
            <div className="stageIndex">{index + 1}</div>
            <div>
              <div className="stageTitle">
                <strong>{stage.label}</strong>
                <StatusPill tone={stageTone(stage)}>{stageStatusLabel(stage.status)}</StatusPill>
              </div>
              <p>{stage.detail}</p>
              {stage.command && (
                <details className="auditDetails stageCommand">
                  <summary>Technical command</summary>
                  <code>{stage.command.join(" ")}</code>
                </details>
              )}
            </div>
            {runnableStage(stage) && (
              <button className={stage.writes ? "secondaryButton risky" : "secondaryButton"} onClick={() => onRun(stage)} title={stage.detail}>
                <Play size={16} />
                <span>{stageButtonLabel(stage, executeWrites, busyStep)}</span>
              </button>
            )}
          </article>
        ))}
      </div>
      {plan.next_blocked_stage && (
        <p className="pipelineNote">
          Next required step: <strong>{plan.next_blocked_stage.label}</strong> · {plan.next_blocked_stage.detail}
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
  const resultRiskFlags = result?.risk_flags || [];
  const resultFindings = result?.findings || [];
  const targetPages = result?.targets?.target_pages || [];
  const targetEntities = result?.targets?.target_entities || [];

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
          <h1>Add Knowledge</h1>
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
              <small>{pageMetaLabel(item)} · {evidenceLabel(item)}</small>
            </button>
          ))}
          {bundle.sources.sources.length === 0 && <p>No evidence sources in this view.</p>}
        </div>
      </section>
      <section className="panel">
        <div className="panelHeader">
          <h2>Review New Source</h2>
          <StatusPill tone={sourceResultTone(result)}>{result ? (result.ok ? "ready" : "blocked") : "idle"}</StatusPill>
        </div>
        <div className="workflowGrid">
          <label className="field wide">
            <span>File or URL to add</span>
            <input value={source} onChange={(event) => setSource(event.target.value)} />
          </label>
          <label className="field">
            <span>Area</span>
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
            <span>{busy ? "Checking" : "Check source"}</span>
          </button>
          <label className="toggleControl wideToggle">
            <input type="checkbox" checked={executeWrites} onChange={(event) => setExecuteWrites(event.target.checked)} />
            <span>Allow review writes</span>
          </label>
        </div>
        {result && (
          <div className="triageResult">
            <div className="sourceDecisionGrid" aria-label="Source decision summary">
              <article className="sourceDecisionCard">
                <span>Decision</span>
                <strong>{sourceReadyLabel(result)}</strong>
                <p>{sourceReadyDetail(result)}</p>
              </article>
              <article className="sourceDecisionCard">
                <span>Risk</span>
                <strong>{sourceRiskSummary(result)}</strong>
                <p>{resultRiskFlags.length ? "Review the flagged items before approving the source." : "No access-secret or risk flag was found in triage."}</p>
              </article>
              <article className="sourceDecisionCard">
                <span>Destination</span>
                <strong>{result.context || context}</strong>
                <p>{targetPages.length ? `${targetPages.length} suggested content item(s)` : "No exact target suggested yet."}</p>
              </article>
              <article className="sourceDecisionCard">
                <span>Evidence</span>
                <strong>{sourceFoundLabel(result.exists)}</strong>
                <p>{sourceTypeLabel(result.source_type)}</p>
              </article>
            </div>
            <details className="auditDetails sourceTechnicalDetails">
              <summary>Technical source details</summary>
              <dl className="kv">
                <dt>Source key</dt>
                <dd>{result.source_id || "not available"}</dd>
                <dt>Source</dt>
                <dd>{result.source || source}</dd>
                <dt>Content type</dt>
                <dd>{result.source_type || "unknown"}</dd>
                <dt>Found</dt>
                <dd>{String(result.exists)}</dd>
                <dt>Area</dt>
                <dd>{result.context || context}</dd>
              </dl>
            </details>
            <div className="tagCloud" aria-label="Source risk flags">
              {resultRiskFlags.map((flag) => (
                <StatusPill tone={flag === "secret_block" ? "bad" : "warn"} key={flag}>
                  {sourceRiskLabel(flag)}
                </StatusPill>
              ))}
              {resultRiskFlags.length === 0 && <StatusPill tone="good">No flags</StatusPill>}
            </div>
            {result.targets && (
              <div className="targetGrid">
                <article className="sourceTargetCard">
                  <h3>Suggested Content</h3>
                  <p>{targetPages.length ? `${targetPages.length} existing page(s) may need to receive or reference this source.` : "No existing page was matched automatically."}</p>
                  <details className="auditDetails">
                    <summary>Exact target pages</summary>
                    <ul className="plainList compactList">
                      {targetPages.map((page) => (
                        <li key={page}>{page}</li>
                      ))}
                      {targetPages.length === 0 && <li>none</li>}
                    </ul>
                  </details>
                </article>
                <article className="sourceTargetCard">
                  <h3>Known Entities</h3>
                  <p>{targetEntities.length ? `${targetEntities.length} existing entity link(s) were suggested.` : "No known entity was matched automatically."}</p>
                  <details className="auditDetails">
                    <summary>Exact entity references</summary>
                    <ul className="plainList compactList">
                      {targetEntities.map((entity) => (
                        <li key={entity}>{entity}</li>
                      ))}
                      {targetEntities.length === 0 && <li>none</li>}
                    </ul>
                  </details>
                </article>
              </div>
            )}
            {(result.next_steps || []).length > 0 && (
              <>
                <h3>Recommended Next Steps</h3>
                <ul className="plainList compactList">
                  {(result.next_steps || []).map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ul>
              </>
            )}
            {resultFindings.length > 0 && (
              <>
                <h3>Review Findings</h3>
                <div className="sourceFindingList">
                  {resultFindings.map((finding) => (
                    <article className="sourceFinding" key={`${finding.kind}-${finding.line}-${finding.excerpt}`}>
                      <div>
                        <strong>{sourceFindingLabel(finding)}</strong>
                        <p>{finding.excerpt}</p>
                        <details className="auditDetails">
                          <summary>Detection details</summary>
                          <dl className="kv">
                            <dt>Line</dt>
                            <dd>{finding.line}</dd>
                            <dt>Detector</dt>
                            <dd>{finding.detector}</dd>
                          </dl>
                        </details>
                      </div>
                      <StatusPill tone={finding.category === "secret" ? "bad" : "warn"}>{finding.severity}</StatusPill>
                    </article>
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

function PageList({
  pages,
  selected,
  search,
  mode,
  modeCounts,
  onModeChange,
  onSearch
}: {
  pages: PageRecord[];
  selected: PageRecord | undefined;
  search: string;
  mode: ContentViewMode;
  modeCounts: Record<ContentViewMode, number>;
  onModeChange: (mode: ContentViewMode) => void;
  onSearch: (value: string) => void;
}) {
  return (
    <aside className="pageList" aria-label="Content browser">
      <div className="pageListHeader">
        <div>
          <h2>Browse Content</h2>
          <span>{pages.length} visible item(s)</span>
        </div>
        <p className="pageListLead">Choose a verification queue, then open an item for the decision summary.</p>
        <div className="contentModeBar" role="group" aria-label="Content verification filters">
          {CONTENT_VIEW_MODES.map((item) => (
            <button
              aria-pressed={mode === item.id}
              className={mode === item.id ? "contentModeButton active" : "contentModeButton"}
              key={item.id}
              onClick={() => onModeChange(item.id)}
              title={item.description}
              type="button"
            >
              <span>{item.label}</span>
              <small>{modeCounts[item.id]}</small>
            </button>
          ))}
        </div>
        <label className="field">
          <span>Find</span>
          <input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="title, area, type, evidence" />
        </label>
      </div>
      {pages.slice(0, 120).map((page) => (
        <a className={selected?.id === page.id ? "pageLink active" : "pageLink"} href={`/pages/${encodeURIComponent(page.id)}`} key={page.id}>
          <span>{page.title}</span>
          <small>{pageMetaLabel(page)} · {evidenceLabel(page)}</small>
        </a>
      ))}
      {pages.length === 0 && <p>No content matched the current search.</p>}
    </aside>
  );
}

function PagesView({ bundle, pageId }: { bundle: SnapshotBundle; pageId?: string }) {
  const [search, setSearch] = useState("");
  const [mode, setMode] = useState<ContentViewMode>("attention");
  const modeCounts = useMemo(() => contentModeCounts(bundle.pages.pages), [bundle.pages.pages]);
  const modePages = useMemo(() => pagesForContentMode(bundle.pages.pages, mode), [bundle.pages.pages, mode]);
  const results = useMemo(
    () => modePages.filter((page) => pageMatches(page, search)),
    [modePages, search]
  );
  const selected = pageId ? pageById(bundle.pages.pages, pageId) : pageById(results.length ? results : modePages, pageId);
  return (
    <main className="workspace pagesWorkspace">
      <PageList
        mode={mode}
        modeCounts={modeCounts}
        onModeChange={setMode}
        onSearch={setSearch}
        pages={results}
        search={search}
        selected={selected}
      />
      <section className="panel pageDetail">
        {selected && (
          <>
            <div className="panelHeader">
              <h1>{selected.title}</h1>
              <StatusPill tone={selected.freshness_state === "fresh" ? "good" : selected.freshness_state === "stale" ? "warn" : "muted"}>
                {freshnessLabel(selected.freshness_state)}
              </StatusPill>
            </div>
            <div className="pageVerificationIntro">
              <h2>Verification Summary</h2>
              <p>{selected.summary || "No short summary is available in this view."}</p>
            </div>
            <div className="contentDecisionGrid" aria-label="Content verification summary">
              <article className="contentDecisionCard">
                <span>Decision</span>
                <strong>{pageDecisionLabel(selected)}</strong>
                <p>{pageDecisionDetail(selected)}</p>
              </article>
              <article className="contentDecisionCard">
                <span>Evidence</span>
                <strong>{evidenceLabel(selected)}</strong>
                <p>{pageEvidenceDetail(selected)}</p>
              </article>
              <article className="contentDecisionCard">
                <span>Area</span>
                <strong>{selected.context || "No area"}</strong>
                <p>{contentKindLabel(selected.page_type)}</p>
              </article>
              <article className="contentDecisionCard">
                <span>Last update</span>
                <strong>{updatedLabel(selected.updated_at)}</strong>
                <p>{freshnessLabel(selected.freshness_state)}</p>
              </article>
            </div>
            <details className="auditDetails">
              <summary>Open technical references</summary>
              <dl className="kv">
                <dt>File address</dt>
                <dd>{selected.path}</dd>
                <dt>Approval state</dt>
                <dd>{selected.approved_state || "not listed"}</dd>
                <dt>Risk flags</dt>
                <dd>{selected.risk_flags.length ? humanList(selected.risk_flags.map(riskHintLabel)) : "none listed"}</dd>
                <dt>Evidence ids</dt>
                <dd>{selected.source_refs.length ? selected.source_refs.join(", ") : "none listed"}</dd>
              </dl>
              <a className="externalLink" href={`/${selected.path}`} title="Open Markdown file">
                <ExternalLink size={16} />
                <span>Open Markdown file</span>
              </a>
            </details>
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
    if (route.view === "health") return <HealthView bundle={bundle} onRun={runAction} />;
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
                {loadState.runtime.repoLabel || loadState.bundle.manifest.repo.repo_id} · {modeLabel(loadState.runtime.mode || loadState.bundle.manifest.mode)}
              </span>
            )}
          </div>
          {loadState.status === "ready" && (
            <StatusPill tone={loadState.bundle.git.proposal.is_proposal_branch ? "warn" : "good"}>
              {gitGateLabel(loadState.bundle.git)}
            </StatusPill>
          )}
        </header>
        {content}
        <CommandOutput result={commandResult} />
      </div>
    </div>
  );
}
