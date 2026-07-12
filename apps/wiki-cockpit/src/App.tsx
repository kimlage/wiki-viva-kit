import {
  Activity,
  CheckCircle2,
  CircleAlert,
  Database,
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
  Sprout,
  TerminalSquare
} from "lucide-react";
import type { ReactNode } from "react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BlocksDock } from "./components/BlocksDock";
import { AppearanceControl } from "./components/AppearanceControl";
// CreateDock and the genesis guide render inside WorldView now — the create
// flow is spatial-first, the tutorial voice is an in-world beacon.
import { BriefStudio } from "./components/BriefStudio";
import { DemoGate } from "./components/DemoGate";
import { CodexDock } from "./components/CodexDock";
import { GateDock } from "./components/GateDock";
import { GatesDock } from "./components/GatesDock";
import { IntakeDock } from "./components/IntakeDock";
import { WorkDock } from "./components/WorkDock";
import { SourceDock } from "./components/SourceDock";
import { useSurfacePresence } from "./components/world/useSurfacePresence";
import { ExpandablePre } from "./components/ExpandablePre";
import { GENESIS_FINAL_STAGE, genesisAttachMatches, genesisCreateMatches, genesisUrl } from "./data/genesis";
import { configureLanguage, t } from "./data/i18n";
import { qualityFlagCount, reviewChecklist } from "./data/model";
import { contextLabel, pageTypeLabel, registerContextPalette } from "./data/presentation";
import type { RuntimeConfig } from "./data/runtimeConfig";
import type { Route, WorldPatch, WorldRoute } from "./router";
import { isNativeWorldViewId } from "./world/experience";
import type { ApplicationPorts } from "./application/ports";
import { groupKeyForPage } from "./scene/perspectives";
import type { OperatorCommandCard, BriefRecord, BriefSpec, CodexCapability, CommandResultEntry, CommandRunResult, DiffFile, IngestionPlan, IngestionStage, PageRecord, SnapshotBundle, SourceFinding, SourceTriageResult } from "./types";
import { CODEX_UNAVAILABLE } from "./types";
import "./shell.css";

const RuntimeWorldView = lazy(() => import("./components/RuntimeWorldView").then((module) => ({ default: module.RuntimeWorldView })));

type LoadState =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "ready"; bundle: SnapshotBundle; source: string; runtime: RuntimeConfig };

// Returning to a tab is a useful, low-noise freshness signal for a local
// cockpit. Keep the guard long enough to collapse the paired `focus` +
// `visibilitychange` events browsers commonly emit for the same return.
const REAL_SNAPSHOT_REVALIDATION_INTERVAL_MS = 5_000;

function snapshotRevisionKey(bundle: SnapshotBundle): string {
  const manifest = bundle.manifest;
  if (manifest.snapshot_id || manifest.bundle_hash) {
    return `snapshot:${manifest.snapshot_id || ""}|bundle:${manifest.bundle_hash || ""}`;
  }
  return `source:${manifest.source_sha || manifest.source_commit || manifest.generated_at}`;
}

function snapshotVerifiedAtLabel(timestamp: number | null): string {
  if (timestamp === null) return t("snapshot.revalidationNeverVerified");
  return new Date(timestamp).toISOString().replace(".000Z", "Z");
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
    controlled_operator: "controlled operator",
    // Real mode whose operator/snapshot could not be reached: the bundled
    // SAMPLE loaded instead — the header must say so, loudly.
    sample_fallback: "SAMPLE DATA — operator unreachable"
  };
  return labels[mode] || mode.replaceAll("_", " ");
}

function WorldRouteLoading({ readerOpen }: { readerOpen: boolean }) {
  return (
    <main className={readerOpen ? "worldRouteLoading withReader" : "worldRouteLoading"} role="status">
      <div className="worldRouteLoadingFrame">
        <div className="worldRouteLoadingTop" aria-hidden="true">
          <strong>Galaxy</strong>
          <span>Quadrants</span><span>Radar</span><span>Sources</span><span>Work</span><span>Overlay</span>
        </div>
        <div className="worldRouteLoadingStage" aria-hidden="true">
          <aside>
            <strong>Next steps</strong>
            <span>Preparing operational signals…</span>
          </aside>
          <section>
            <Sparkles size={18} />
            <strong>Building one continuous world</strong>
            <span>Keeping page identity and position while the scene arrives.</span>
          </section>
        </div>
        {readerOpen && (
          <aside className="worldRouteReaderLoading" aria-hidden="true">
            <div><span>page</span><span>context</span><span>evidence</span></div>
            <h2>Loading page context</h2>
            <p>The world stays visible while relationships and evidence arrive.</p>
            <section>
              <small>ACTION AT A GLANCE</small>
              <strong>Preparing the next decision…</strong>
            </section>
          </aside>
        )}
        <span className="visuallyHidden">Loading world runtime…</span>
      </div>
    </main>
  );
}

function isBlockedSampleFallback(route: Route, state: LoadState): boolean {
  if (route.demo || state.status !== "ready") return false;
  return state.runtime.mode === "sample_fallback" || state.source.includes("/sample-snapshot");
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

function Nav({
  active,
  demo,
  dockHref
}: {
  active: string;
  demo: boolean;
  dockHref: (dock: "approve" | "intake" | "gates" | "source" | "create") => string;
}) {
  // /demo prefixes ALL generated URLs — the demo universe never cross-links
  // into the real snapshot. Anchors are intercepted by the SPA router. The
  // Approve/Add/Health items open the world dock in place (dockHref carries the
  // demo prefix through patchWorld), so no legacy-redirect flash.
  const prefix = demo ? "/demo" : "";
  const items = [
    { href: `${prefix}/w?view=radar`, id: "world", label: t("nav.home"), icon: <Activity size={17} /> },
    { href: dockHref("approve"), id: "review", label: t("nav.approve"), icon: <GitPullRequest size={17} /> },
    { href: dockHref("intake"), id: "sources", label: t("nav.add"), icon: <Inbox size={17} /> },
    { href: dockHref("create"), id: "create", label: t("nav.create"), icon: <Sprout size={17} /> },
    { href: dockHref("source"), id: "fontes", label: t("nav.sources"), icon: <Database size={17} /> },
    { href: dockHref("gates"), id: "health", label: t("nav.health"), icon: <ShieldCheck size={17} /> },
    { href: `${prefix}/w?view=atlas&runtime=compat`, id: "content", label: t("nav.content"), icon: <FileText size={17} /> },
    demo
      ? { href: "/w?view=radar", id: "demo", label: t("nav.exitDemo"), icon: <Sparkles size={17} /> }
      : { href: "/demo/w?view=radar", id: "demo", label: t("nav.demo"), icon: <Sparkles size={17} /> }
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

function operatorCommandTitle(action: OperatorCommandCard): string {
  const labels: Record<string, string> = {
    "git-status": "Check work state",
    "review-local-changes": "Inspect changed content",
    "run-honesty-gates": "Verify approval readiness",
    "pr-summary": "Prepare approval summary",
    "graph-check": "Check related content"
  };
  return labels[action.id] || action.title;
}

function operatorCommandReason(action: OperatorCommandCard): string {
  const labels: Record<string, string> = {
    "review-local-changes": "Shows changed content before saving a version or preparing approval.",
    "run-honesty-gates": "Confirms whether local checks support the next human decision.",
    "pr-summary": "Prepares a human-readable summary from changed content, affected areas and privacy notes.",
    "graph-check": "Checks whether related content and impact links still make sense."
  };
  return labels[action.id] || action.human_reason;
}

function OperatorCommandButton({ action, onRun }: { action: OperatorCommandCard; onRun: (action: OperatorCommandCard) => void }) {
  const risky = action.risk_level !== "read";
  const title = operatorCommandTitle(action);
  return (
    <button className={risky ? "actionButton risky" : "actionButton"} onClick={() => onRun(action)} title={operatorCommandReason(action)}>
      {risky ? <RefreshCw size={16} /> : <Play size={16} />}
      <span>{title}</span>
    </button>
  );
}

function commandResultTitle(result: CommandRunResult): string {
  if ("summary" in result && result.summary) return result.summary;
  if ("operation" in result) return result.operation.replaceAll("_", " ");
  if ("action_id" in result) {
    const key = `operatorCommandTitle.${result.action_id}`;
    const label = t(key);
    return label === key ? result.action_id.replaceAll("_", " ") : label;
  }
  return t("action.finished");
}

function commandResultMode(result: CommandRunResult): string {
  return result.dry_run ? t("action.previewOnly") : t("action.applied");
}

function commandEntryLabel(entry: CommandResultEntry, index: number): string {
  return t("action.stepLabel", {
    index: index + 1,
    state: entry.ok ? t("action.completed") : t("action.needsAttention")
  });
}

function CommandOutput({ result }: { result: CommandRunResult | null }) {
  if (!result) return null;
  const passedCount = result.results.filter((entry) => entry.ok).length;
  const failedCount = result.results.length - passedCount;
  return (
    <section className="panel outputPanel" id="actionResult">
      <div className="panelHeader">
        <h2>{t("action.title")}</h2>
        <StatusPill tone={result.ok ? "good" : "bad"}>{result.ok ? t("action.completed") : t("action.needsAttention")}</StatusPill>
      </div>
      <div className="outputSummary">
        <strong>{commandResultTitle(result)}</strong>
        <p>{result.ok ? t("action.okBody") : t("action.failBody")}</p>
      </div>
      <div className="outputFacts" aria-label={t("action.facts")}>
        <span>
          <strong>{commandResultMode(result)}</strong>
          {t("action.mode")}
        </span>
        <span>
          <strong>{passedCount}/{result.results.length}</strong>
          {t("action.stepsCompleted")}
        </span>
        <span>
          <strong>{failedCount}</strong>
          {t("action.needsAttentionFact")}
        </span>
      </div>
      {result.error && <p className="outputError">{result.error}</p>}
      <div className="outputStepList">
        {result.results.map((entry, index) => (
          <details className="auditDetails outputStep" key={`${entry.argv.join(" ")}-${index}`}>
            <summary>
              <TerminalSquare size={16} />
              <span>{commandEntryLabel(entry, index)}</span>
              <StatusPill tone={entry.ok ? "good" : "bad"}>{entry.ok ? t("action.ok") : t("action.failed")}</StatusPill>
            </summary>
            <div className="commandMeta">
              <span>{entry.dry_run ? t("action.previewOnly") : t("action.applied")}</span>
              <code>{entry.argv.join(" ")}</code>
            </div>
            <ExpandablePre
              text={[entry.stdout, entry.stderr].filter(Boolean).join("\n")}
              title={commandEntryLabel(entry, index)}
              emptyLabel={t("action.noOutput")}
            />
          </details>
        ))}
      </div>
      {result.results.length === 0 && !result.error && <p className="outputEmpty">{t("action.noTerminalOutput")}</p>}
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

function pathTitle(path: string): string {
  const fileName = path.split("/").pop() || path;
  return fileName
    .replace(/\.[^.]+$/, "")
    .replace(/^\d{4}-\d{2}-\d{2}-?/, "")
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (value) => value.toUpperCase());
}

function humanFileLabel(file: DiffFile): string {
  if (file.path.includes("apps/wiki-cockpit/src/App.tsx")) return "Cockpit flow";
  if (file.path.includes("apps/wiki-cockpit/src/styles.css")) return "Cockpit layout";
  if (file.path.includes("apps/wiki-cockpit/src/App.visual.test.tsx")) return "Visual route checks";
  if (file.path.includes("apps/wiki-cockpit/src/")) return `Cockpit ${pathTitle(file.path)}`;
  if (file.path.includes("/proposals/")) return `Proposal: ${pathTitle(file.path)}`;
  if (file.path.startsWith("memories/")) return `Wiki content: ${pathTitle(file.path)}`;
  if (file.path.startsWith("docs/")) return `Reference: ${pathTitle(file.path)}`;
  if (file.path.startsWith("scripts/")) return `Local operation: ${pathTitle(file.path)}`;
  if (file.path.startsWith("tests/")) return `Validation: ${pathTitle(file.path)}`;
  return pathTitle(file.path);
}

function humanFileSummary(file: DiffFile): string {
  return `${humanFileLabel(file)} · ${changeAreaLabel(file.category)} · ${changeStatusLabel(file.status || "changed")}`;
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
  return pageTypeLabel(kind);
}

function pageStatusTone(page: PageRecord): "good" | "warn" | "bad" | "info" | "muted" {
  if (page.risk_flags.length > 0) return "warn";
  if (page.freshness_state === "fresh") return "good";
  if (page.freshness_state === "stale") return "warn";
  return "muted";
}

function pageMetaLabel(page: PageRecord): string {
  return `${page.context ? contextLabel(page.context) : "No area"} · ${contentKindLabel(page.page_type)} · ${freshnessLabel(page.freshness_state)}`;
}

function evidenceLabel(page: PageRecord): string {
  if (page.source_refs.length === 0) return "No evidence links listed";
  if (page.source_refs.length === 1) return "1 evidence link";
  return `${page.source_refs.length} evidence links`;
}

function DiffFrame({ file }: { file: DiffFile }) {
  return (
    <article className="diffFrame">
      <div className="diffFrameHeader">
        <div>
          <strong>{humanFileLabel(file)}</strong>
          <span>{changeAreaLabel(file.category)} · {file.change_sources.map(changeSourceLabel).join(", ")}</span>
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
      <details className="inlineDetails">
        <summary>File details</summary>
        <code>{file.path}</code>
      </details>
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
        <summary>Comparison details</summary>
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
    "- [ ] Content changes inspected",
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

function changedScopeLabel(bundle: SnapshotBundle): string {
  const files = bundle.diff.files;
  if (files.length === 0) return "No changed content is listed.";
  const areas = [...new Set(files.map((file) => changeAreaLabel(file.category)).filter(Boolean))];
  return `${files.length} item(s) across ${humanList(areas, "unknown areas")}.`;
}

function approvalMissingItems(bundle: SnapshotBundle, risks: string[], checkReady: boolean, requestUrl: string | null): string[] {
  const missing: string[] = [];
  if (!bundle.git.proposal.is_proposal_branch && bundle.git.current_branch !== bundle.git.default_branch) missing.push("review workspace");
  if (bundle.diff.summary.file_count > 0) missing.push("scope review");
  if (bundle.diff.summary.privacy_review_required || risks.length > 0) missing.push("risk review");
  if (!checkReady) missing.push("validation evidence");
  if (bundle.git.upstream.ahead > 0) missing.push("send local changes");
  if (!requestUrl && bundle.git.current_branch !== bundle.git.default_branch) missing.push("linked approval request");
  return missing;
}

function approvalCommandLabel(actionId: string): string {
  const labels: Record<string, string> = {
    "pr-summary": "Prepare packet",
    "review-local-changes": "Inspect changes",
    "run-honesty-gates": "Run checks"
  };
  return labels[actionId] || actionId.replaceAll("_", " ");
}

function ApprovalInbox({
  bundle,
  onRun
}: {
  bundle: SnapshotBundle;
  onRun: (action: OperatorCommandCard) => void;
}) {
  const checks = reviewChecklist(bundle);
  const decision = approvalDecision(bundle);
  const risks = approvalRiskHints(bundle);
  const prCommand = bundle.actions.actions.find((action) => action.id === "pr-summary");
  const gateCommand = bundle.actions.actions.find((action) => action.id === "run-honesty-gates");
  const reviewCommand = bundle.actions.actions.find((action) => action.id === "review-local-changes");
  const changedFiles = bundle.diff.files.slice(0, 6);
  const primaryChangedFiles = changedFiles.slice(0, 3);
  const changedAreas = [...new Set(bundle.diff.files.map((file) => changeAreaLabel(file.category)).filter(Boolean))].slice(0, 8);
  const riskyFiles = bundle.diff.files.filter((file) => file.risk_hints.length > 0).slice(0, 6);
  const requestUrl = bundle.git.proposal.draft_pr_url;
  const checkTone = gateStatusTone(bundle.gates.status);
  const checkReady = checkTone === "good";
  const checkLabels = bundle.gates.gates.map((gate) => gateCheckLabel(gate.id));
  const missingItems = approvalMissingItems(bundle, risks, checkReady, requestUrl);
  const changedFileLine = primaryChangedFiles.length
    ? `${primaryChangedFiles.map((file) => humanFileSummary(file)).join(", ")}${
        bundle.diff.files.length > primaryChangedFiles.length ? ` and ${bundle.diff.files.length - primaryChangedFiles.length} more` : ""
      }`
    : "No changed content listed.";

  return (
    <section className="approvalInbox" aria-label="Approval inbox">
      <div className="approvalInboxHeader">
        <div>
          <StatusPill tone={decision.tone}>{decision.label}</StatusPill>
          <h1>Approval Inbox</h1>
          <p>{decision.detail} Each inbox item below contains the decision, available evidence and the next action.</p>
        </div>
        <div className="inboxCounters inboxDecisionCards" aria-label="Approval summary">
          <span><strong>{bundle.diff.summary.file_count ? "Review" : "Clear"}</strong> Scope</span>
          <span><strong>{risks.length || bundle.diff.summary.privacy_review_required ? "Check" : "Clear"}</strong> Risk</span>
          <span><strong>{checkReady ? "Ready" : "Needed"}</strong> Validation</span>
          <span><strong>{requestUrl ? "Linked" : "Missing"}</strong> Human gate</span>
        </div>
      </div>

      <section className="approvalBrief" aria-label="Approval decision brief">
        <article>
          <span>What is being approved?</span>
          <strong>{changedScopeLabel(bundle)}</strong>
          <p>{changedAreas.length ? `Touched areas: ${humanList(changedAreas)}.` : "No changed area is listed."}</p>
        </article>
        <article>
          <span>What blocks approval?</span>
          <strong>{missingItems.length ? `${missingItems.length} open requirement(s)` : "No blocker visible"}</strong>
          <p>{missingItems.length ? `${humanList(missingItems)}. Resolve or consciously accept them before the final human decision.` : "The visible evidence is enough for the next human decision."}</p>
        </article>
        <article>
          <span>Where is the final yes/no?</span>
          <strong>{requestUrl ? "Review request" : "Not linked yet"}</strong>
          <p>{approvalWorkspaceLabel(bundle.git)}. {approvalSharedCopyLabel(bundle.git)}</p>
        </article>
      </section>

      <div className="approvalQueue">
        <article className="approvalItem">
          <div className="approvalItemHeader">
            <span className="stageIndex">1</span>
            <div>
              <h2>Scope to approve</h2>
              <p>Confirm whether these changes belong in one approval request.</p>
            </div>
            <StatusPill tone={bundle.diff.summary.file_count ? "warn" : "good"}>
              {bundle.diff.summary.file_count ? "needs review" : "clear"}
            </StatusPill>
          </div>
          <dl className="approvalFacts">
            <dt>Decision</dt>
            <dd>{bundle.diff.summary.file_count ? "Review whether these changes belong in one approval request." : "No changed content needs approval in this view."}</dd>
            <dt>Evidence</dt>
            <dd>{changedFileLine}</dd>
            <dt>Next</dt>
            <dd>{bundle.diff.summary.file_count ? "Prepare the review packet, then inspect exact changes only when scope is unclear." : "Move to validation or the human gate."}</dd>
          </dl>
          <details className="approvalItemDetails">
            <summary>See exact changed files</summary>
            <ul className="plainList compactList">
              {changedFiles.map((file) => (
                <li key={`${file.status}-${file.path}`}>
                  {humanFileSummary(file)} · {file.additions} added / {file.deletions} removed
                  <br />
                  <code>{file.path}</code>
                </li>
              ))}
              {bundle.diff.files.length > changedFiles.length && <li>{bundle.diff.files.length - changedFiles.length} more item(s) in exact evidence.</li>}
            </ul>
          </details>
          <div className="approvalItemActions">
            {prCommand && (
              <button className="actionButton" onClick={() => onRun(prCommand)} title={operatorCommandReason(prCommand)}>
                <Play size={16} />
                <span>{approvalCommandLabel(prCommand.id)}</span>
              </button>
            )}
            {reviewCommand && (
              <button className="secondaryButton" onClick={() => onRun(reviewCommand)} title={operatorCommandReason(reviewCommand)}>
                <Search size={16} />
                <span>{approvalCommandLabel(reviewCommand.id)}</span>
              </button>
            )}
          </div>
        </article>

        <article className="approvalItem">
          <div className="approvalItemHeader">
            <span className="stageIndex">2</span>
            <div>
              <h2>Approval blockers</h2>
              <p>Check whether risk or privacy notes stop this from moving forward.</p>
            </div>
            <StatusPill tone={bundle.diff.summary.privacy_review_required || risks.length ? "warn" : "good"}>
              {bundle.diff.summary.privacy_review_required || risks.length ? "needs review" : "clear"}
            </StatusPill>
          </div>
          <dl className="approvalFacts">
            <dt>Decision</dt>
            <dd>{bundle.diff.summary.privacy_review_required || risks.length ? "Resolve the listed blockers or call them out in the review request." : "No privacy or risk blocker is visible."}</dd>
            <dt>Evidence</dt>
            <dd>{risks.length ? risks.map(riskHintLabel).join(", ") : "No explicit risk notes."}</dd>
            <dt>Next</dt>
            <dd>{bundle.diff.summary.privacy_review_required ? "Review required before approval." : "No privacy flag in the changed content."}</dd>
          </dl>
          <details className="approvalItemDetails">
            <summary>See files with risk notes</summary>
            <ul className="plainList compactList">
              {riskyFiles.map((file) => (
                <li key={file.path}>
                  {humanFileLabel(file)} · {file.risk_hints.map(riskHintLabel).join(", ")}
                  <br />
                  <code>{file.path}</code>
                </li>
              ))}
              {riskyFiles.length === 0 && <li>No changed files carry explicit risk notes.</li>}
            </ul>
          </details>
        </article>

        <article className="approvalItem">
          <div className="approvalItemHeader">
            <span className="stageIndex">3</span>
            <div>
              <h2>Validation evidence</h2>
              <p>Confirm that automated signals support the human decision.</p>
            </div>
            <StatusPill tone={checkTone}>{gateStatusLabel(bundle.gates.status)}</StatusPill>
          </div>
          <dl className="approvalFacts">
            <dt>Decision</dt>
            <dd>{checkReady ? "Automated validation is ready for human review." : "Run or inspect checks before approval."}</dd>
            <dt>Evidence</dt>
            <dd>{bundle.gates.gates.length} check(s): {humanList(checkLabels)}.</dd>
            <dt>Next</dt>
            <dd>{checks.filter((check) => check.ok).length}/{checks.length} approval checklist item(s) ready.</dd>
          </dl>
          <details className="approvalItemDetails">
            <summary>See validation checklist</summary>
            <ul className="plainList compactList">
              {checks.map((check) => (
                <li key={check.label}>{check.ok ? "Ready" : "Needs work"} · {check.label}</li>
              ))}
            </ul>
          </details>
          <div className="approvalItemActions">
            {gateCommand && (
              <button className="actionButton" onClick={() => onRun(gateCommand)} title={operatorCommandReason(gateCommand)}>
                <Play size={16} />
                <span>{approvalCommandLabel(gateCommand.id)}</span>
              </button>
            )}
          </div>
        </article>

        <article className="approvalItem">
          <div className="approvalItemHeader">
            <span className="stageIndex">4</span>
            <div>
              <h2>Human gate</h2>
              <p>Confirm where the final approval, change request or rejection will happen.</p>
            </div>
            <StatusPill tone={requestUrl ? "info" : "warn"}>
              {requestUrl ? "linked" : "not opened"}
            </StatusPill>
          </div>
          <dl className="approvalFacts">
            <dt>Decision</dt>
            <dd>{requestUrl ? "Use the linked request as the human gate." : "Open or link a request before final approval."}</dd>
            <dt>Evidence</dt>
            <dd>{approvalWorkspaceLabel(bundle.git)}</dd>
            <dt>Next</dt>
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
          <summary>Refresh details</summary>
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

// The legacy 2D pages (/review, /sources, /health) are GONE: an effect in
// App() redirects each to its world dock (approve/intake/gates), so old
// bookmarks keep working with zero rendering cost. Their components lived
// here until the 2026-07 cleanup.

export function App({ ports }: { ports: ApplicationPorts }) {
  const { navigation, operator } = ports;
  const [url, setUrl] = useState(() => navigation.getSnapshot());
  useEffect(
    () => navigation.subscribe(() => setUrl(navigation.getSnapshot())),
    [navigation]
  );
  const route = useMemo<Route>(() => navigation.parseUrl(url), [navigation, url]);
  // UI code emits navigation intentions through the injected application port.
  // URL grammar remains pure and independently testable on the same boundary.
  const navigate = (target: Route | string, options: { replace?: boolean } = {}) =>
    navigation.dispatch({ type: "navigate", target, replace: options.replace });
  const buildUrl = navigation.href;
  const patchWorld = navigation.patch;
  const worldFromRoute = navigation.toWorld;
  const hrefForWorldPatch = (worldRoute: WorldRoute, patch: WorldPatch) => {
    const nativeV8 = (!worldRoute.perspectiveExplicit || isNativeWorldViewId(worldRoute.query.view)) &&
      worldRoute.query.runtime !== "compat" && worldRoute.query.runtime !== "legacy";
    if (!nativeV8) return buildUrl(patchWorld(worldRoute, patch));

    // App-owned docks render beside RuntimeWorldView, so their callbacks do
    // not pass through WorldView's canonical writer. Mirror the same query
    // ownership here: page/group state lives in the v8 query and the emitted
    // path remains exactly `/w`, while patchWorld still enforces the surface
    // singleton and clears dock-only qualifiers.
    const patched = patchWorld(worldRoute, {
      ...patch,
      ...(patch.pageId !== undefined ? { page: patch.pageId } : {}),
      ...(patch.worldGroup === undefined && patch.group !== undefined ? { worldGroup: patch.group } : {})
    });
    const compatibilityHref = buildUrl(patched);
    const queryIndex = compatibilityHref.indexOf("?");
    return `${patched.demo ? "/demo" : ""}/w${queryIndex >= 0 ? compatibilityHref.slice(queryIndex) : ""}`;
  };
  const {
    buildIngestionPlan,
    composeBrief,
    composeSourceBrief,
    discardBrief,
    getBrief,
    loadCodexCapability,
    loadSnapshotBundle,
    returnCodexJob,
    runOperatorCommand,
    runGitWorkflow,
    runIngestionStep,
    saveBriefText,
    spawnCodexJob
  } = operator;
  const [realState, setRealState] = useState<LoadState>({ status: "loading" });
  const [demoState, setDemoState] = useState<LoadState>({ status: "loading" });
  const [commandResult, setCommandResult] = useState<CommandRunResult | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ text: string; tone: "good" | "warn" | "info"; showResult: boolean } | null>(null);
  const [activeBrief, setActiveBrief] = useState<BriefRecord | null>(null);
  const [briefBusy, setBriefBusy] = useState(false);
  const [codexCapability, setCodexCapability] = useState<CodexCapability>(CODEX_UNAVAILABLE);
  const [codexBusy, setCodexBusy] = useState(false);
  const [realRevalidationFailure, setRealRevalidationFailure] = useState<{ lastSuccessAt: number | null } | null>(null);
  const realLoadControllerRef = useRef<AbortController | null>(null);
  const realBundleLoadedRef = useRef(false);
  const lastRealLoadStartedAtRef = useRef(0);
  const lastRealSuccessAtRef = useRef<number | null>(null);
  const previousDemoRef = useRef(route.demo);
  const realRevalidationNoticeRef = useRef<string | null>(null);
  const codexProbeControllerRef = useRef<AbortController | null>(null);
  const markRealSnapshotSuccess = useCallback(() => {
    const failedNotice = realRevalidationNoticeRef.current;
    lastRealSuccessAtRef.current = Date.now();
    setRealRevalidationFailure(null);
    setNotice((current) => current?.text === failedNotice ? null : current);
    realRevalidationNoticeRef.current = null;
  }, []);
  const markRealRevalidationFailure = useCallback(() => {
    const failure = { lastSuccessAt: lastRealSuccessAtRef.current };
    const text = t("snapshot.revalidationFailed", { when: snapshotVerifiedAtLabel(failure.lastSuccessAt) });
    setRealRevalidationFailure(failure);
    realRevalidationNoticeRef.current = text;
    setNotice({ text, tone: "warn", showResult: false });
  }, []);

  // One mounted snapshot universe survives all navigation. A session that
  // starts in /demo must never probe the real operator; crossing into /demo
  // aborts an in-flight real snapshot before the synthetic universe starts.
  // The live universe is revalidated conservatively below without remounting.
  useEffect(() => {
    const returningFromDemo = previousDemoRef.current && !route.demo;
    previousDemoRef.current = route.demo;
    if (route.demo) {
      realLoadControllerRef.current?.abort();
      realLoadControllerRef.current = null;
      return undefined;
    }
    if (realBundleLoadedRef.current && !returningFromDemo) return undefined;

    // When a previously loaded real world returns from demo, keep that world
    // mounted while one unthrottled/coalesced read checks what changed during
    // the synthetic visit. A first-ever real load still owns the loading UI.
    const silent = realBundleLoadedRef.current;
    const controller = new AbortController();
    realLoadControllerRef.current?.abort();
    realLoadControllerRef.current = controller;
    lastRealLoadStartedAtRef.current = Date.now();
    if (!silent) setRealState({ status: "loading" });
    loadSnapshotBundle({ demo: false, signal: controller.signal })
      .then(({ bundle, source, runtime }) => {
        if (controller.signal.aborted) return;
        realBundleLoadedRef.current = true;
        markRealSnapshotSuccess();
        if (realLoadControllerRef.current === controller) realLoadControllerRef.current = null;
        setRealState((current) => {
          if (silent && current.status === "ready" && snapshotRevisionKey(current.bundle) === snapshotRevisionKey(bundle)) {
            return current;
          }
          return { status: "ready", bundle, source, runtime };
        });
      })
      .catch((error: Error) => {
        if (controller.signal.aborted) return;
        if (realLoadControllerRef.current === controller) realLoadControllerRef.current = null;
        if (silent) markRealRevalidationFailure();
        else setRealState({ status: "error", error: error.message });
      });
    return () => {
      if (realLoadControllerRef.current !== controller) return;
      controller.abort();
      realLoadControllerRef.current = null;
    };
  }, [loadSnapshotBundle, markRealRevalidationFailure, markRealSnapshotSuccess, route.demo]);
  // Refetch the real bundle after a mutating action (e.g. running gates writes
  // receipts) so the world reacts. Keeps the same runtime/source.
  const refetchReal = () => {
    if (route.demo) return;
    const controller = new AbortController();
    realLoadControllerRef.current?.abort();
    realLoadControllerRef.current = controller;
    lastRealLoadStartedAtRef.current = Date.now();
    loadSnapshotBundle({ demo: false, signal: controller.signal })
      .then(({ bundle, source, runtime }) => {
        if (controller.signal.aborted) return;
        realBundleLoadedRef.current = true;
        markRealSnapshotSuccess();
        if (realLoadControllerRef.current === controller) realLoadControllerRef.current = null;
        setRealState({ status: "ready", bundle, source, runtime });
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        if (realLoadControllerRef.current === controller) realLoadControllerRef.current = null;
        markRealRevalidationFailure();
      });
  };

  // A live wiki can change while its cockpit tab is in the background. On a
  // return to the tab, silently load one coherent real bundle and swap it only
  // when its immutable revision changed. URL-owned page/dock state and the
  // mounted world stay intact, so dialogs and keyboard focus are preserved.
  // Demo routes never install these listeners and can never cross this read
  // boundary. The shared controller + interval guard prevent overlap and the
  // usual focus/visibility event pair from becoming a request storm.
  useEffect(() => {
    if (route.demo) return undefined;

    const revalidate = () => {
      // The URL store can advance one render before this effect is removed.
      // Re-read its current snapshot so a same-turn live -> demo navigation
      // cannot even invoke the real loader (which also fails closed itself).
      if (navigation.parseUrl(navigation.getSnapshot()).demo) return;
      if (document.visibilityState === "hidden") return;
      if (!realBundleLoadedRef.current || realLoadControllerRef.current) return;
      const now = Date.now();
      if (now - lastRealLoadStartedAtRef.current < REAL_SNAPSHOT_REVALIDATION_INTERVAL_MS) return;

      const controller = new AbortController();
      realLoadControllerRef.current = controller;
      lastRealLoadStartedAtRef.current = now;
      loadSnapshotBundle({ demo: false, signal: controller.signal })
        .then(({ bundle, source, runtime }) => {
          if (controller.signal.aborted) return;
          markRealSnapshotSuccess();
          if (realLoadControllerRef.current === controller) realLoadControllerRef.current = null;
          setRealState((current) => {
            if (current.status === "ready" && snapshotRevisionKey(current.bundle) === snapshotRevisionKey(bundle)) {
              return current;
            }
            return { status: "ready", bundle, source, runtime };
          });
        })
        .catch(() => {
          if (controller.signal.aborted) return;
          if (realLoadControllerRef.current === controller) realLoadControllerRef.current = null;
          markRealRevalidationFailure();
        });
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") revalidate();
    };
    window.addEventListener("focus", revalidate);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("focus", revalidate);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [loadSnapshotBundle, markRealRevalidationFailure, markRealSnapshotSuccess, navigation, route.demo]);
  // Demo universe, stage-aware: the genesis tutorial loads stages/<k>/ (a real
  // pre-built snapshot per stage); the full demo loads the base sample. A stage
  // ref guards against stale fetches when the player advances quickly.
  // Clamped: stages/<k>/ exists only for 0..FINAL — a stale ?stage=99 link
  // must load the finale, never brick the demo with a 404.
  const desiredStage =
    route.kind === "world" && route.demo && route.query.genesis
      ? Math.min(route.query.stage, GENESIS_FINAL_STAGE)
      : null;
  const desiredDemoScenario =
    route.kind === "world" && route.demo && !route.query.genesis
      ? route.query.demoScenario || "normal_operations"
      : null;
  const desiredDemoTarget = desiredStage !== null
    ? `stage:${desiredStage}`
    : `scenario:${desiredDemoScenario || "normal_operations"}`;
  const stageRef = useRef<{ target: string | undefined; loaded: string | undefined }>({
    target: undefined,
    loaded: undefined
  });
  // Entities BORN between two demo bundles (a genesis stage advance): the scene
  // greets them with a birth burst — creation should feel like an event.
  const lastDemoPageIdsRef = useRef<Set<string> | null>(null);
  const [bornPageIds, setBornPageIds] = useState<string[]>([]);
  useEffect(() => {
    if (!route.demo) return;
    if (demoState.status === "ready" && stageRef.current.loaded === desiredDemoTarget) return;
    if (stageRef.current.target === desiredDemoTarget && demoState.status === "loading") return;
    // A failed load for THIS stage stays failed (the error panel shows) — the
    // effect must not flip error→loading→error forever. Navigating to another
    // stage (new target) retries naturally.
    if (stageRef.current.target === desiredDemoTarget && demoState.status === "error") return;
    stageRef.current.target = desiredDemoTarget;
    setDemoState({ status: "loading" });
    loadSnapshotBundle({ demo: true, stage: desiredStage, demoScenario: desiredDemoScenario })
      .then(({ bundle, source, runtime }) => {
        if (stageRef.current.target !== desiredDemoTarget) return; // a newer universe/stage won
        stageRef.current.loaded = desiredDemoTarget;
        const ids = bundle.pages.pages.map((page) => page.id);
        const previous = lastDemoPageIdsRef.current;
        // Births are a GENESIS beat (a stage advance): entering the full world
        // or leaving the tutorial is a scene change, not forty deliveries.
        setBornPageIds(
          desiredStage !== null && previous ? ids.filter((id) => !previous.has(id)) : []
        );
        lastDemoPageIdsRef.current = new Set(ids);
        setDemoState({ status: "ready", bundle, source, runtime });
      })
      .catch((error: Error) => {
        if (stageRef.current.target !== desiredDemoTarget) return;
        setDemoState({ status: "error", error: error.message });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [demoState.status, route.demo, desiredDemoScenario, desiredDemoTarget, desiredStage]);

  // The SPA router owns every internal anchor click.
  useEffect(() => navigation.attachLinkInterceptor(), [navigation]);

  // A route change is observable one render before the loading effect above
  // commits. Do not expose the previous stage's bundle under the next stage's
  // guide during that frame: a fast keyboard user could start a form that is
  // then remounted and lose their input when the requested snapshot arrives.
  const visibleDemoState: LoadState =
    demoState.status === "ready" && stageRef.current.loaded !== desiredDemoTarget
      ? { status: "loading" }
      : demoState;
  const loadState = route.demo ? visibleDemoState : realState;
  const blockedSampleFallback = isBlockedSampleFallback(route, loadState);

  // Live Codex capability: only meaningful with the local operator, so it is
  // probed once the real bundle is ready and never in the demo. It fails closed.
  useEffect(() => {
    codexProbeControllerRef.current?.abort();
    codexProbeControllerRef.current = null;
    if (loadState.status !== "ready" || route.demo) return undefined;
    const controller = new AbortController();
    codexProbeControllerRef.current = controller;
    loadCodexCapability(loadState.runtime, { signal: controller.signal })
      .then((capability) => {
        if (!controller.signal.aborted) setCodexCapability(capability);
      })
      .catch(() => {
        if (!controller.signal.aborted) setCodexCapability(CODEX_UNAVAILABLE);
      });
    return () => {
      controller.abort();
      if (codexProbeControllerRef.current === controller) codexProbeControllerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadState.status, route.demo]);

  // Re-probe on demand (the Codex diagnostics dock's Re-verify button): the
  // moment the owner reinstalls / logs in / restarts the operator, the ladder
  // flips without a page reload.
  const reverifyCodex = () => {
    if (loadState.status !== "ready" || route.demo || codexBusy) return;
    codexProbeControllerRef.current?.abort();
    const controller = new AbortController();
    codexProbeControllerRef.current = controller;
    setCodexBusy(true);
    loadCodexCapability(loadState.runtime, { signal: controller.signal })
      .then((capability) => {
        if (!controller.signal.aborted) setCodexCapability(capability);
      })
      .catch(() => {
        if (!controller.signal.aborted) setCodexCapability(CODEX_UNAVAILABLE);
      })
      .finally(() => {
        if (codexProbeControllerRef.current === controller) codexProbeControllerRef.current = null;
        setCodexBusy(false);
      });
  };
  const openCodexDock = () => {
    if (route.kind === "world") navigate(hrefForWorldPatch(route, { dock: "codex" }));
  };

  // The base system is English; the whole UI flips when the wiki's configured
  // language starts with "pt" (runtime config wins over the manifest).
  configureLanguage(
    loadState.status === "ready" ? loadState.runtime.language || loadState.bundle.manifest.repo.language : "en",
    loadState.status === "ready" ? loadState.runtime.strings : undefined
  );

  // Context accents remain deterministic secondary keylines for labels and
  // guides; node body color is resolved exclusively from the active overlay.
  // Inline during render — like configureLanguage above — so the very first
  // scene paint already uses the registered slots (idempotent, module state).
  if (loadState.status === "ready") {
    registerContextPalette(loadState.bundle.graph.nodes.map((node) => node.context || "system"));
  }

  // The legacy 2D pages dissolve into world docks. /review → the Gate, /health →
  // the Gates dock (health is the weather); bookmarks never break. (/sources
  // follows in Phase 4.)
  useEffect(() => {
    if (route.kind === "review") {
      navigate(buildUrl(patchWorld(worldFromRoute(route), { dock: "approve" })), { replace: true });
    } else if (route.kind === "health") {
      navigate(buildUrl(patchWorld(worldFromRoute(route), { dock: "gates" })), { replace: true });
    } else if (route.kind === "sources") {
      navigate(buildUrl(patchWorld(worldFromRoute(route), { dock: "intake" })), { replace: true });
    }
  }, [route.kind]);

  // Legacy alias: /pages/:id lands on the same page in the query-owned world
  // (`/w?view=atlas&page=...&reader=1&runtime=compat`). /pages lists become
  // the Atlas compatibility projection without re-emitting its old path.
  useEffect(() => {
    if (route.kind !== "pageAlias" || loadState.status !== "ready") return;
    const world = worldFromRoute(route);
    if (!route.pageId) {
      navigate(buildUrl({
        ...world,
        perspective: "atlas",
        perspectiveExplicit: true,
        query: { ...world.query, view: "atlas", runtime: "compat" }
      }), { replace: true });
      return;
    }
    const page = loadState.bundle.pages.pages.find((item) => item.id === route.pageId || item.path === route.pageId);
    if (!page) {
      navigate(buildUrl({
        ...world,
        perspective: "atlas",
        perspectiveExplicit: true,
        query: { ...world.query, view: "atlas", runtime: "compat" }
      }), { replace: true });
      return;
    }
    navigate(
      buildUrl({
        ...world,
        perspective: "atlas",
        context: page.context || "system",
        group: groupKeyForPage("atlas", page),
        pageId: page.id,
        perspectiveExplicit: true,
        query: {
          ...world.query,
          view: "atlas",
          worldGroup: groupKeyForPage("atlas", page) || "",
          page: page.id,
          reader: true,
          runtime: "compat"
        }
      }),
      { replace: true }
    );
  }, [loadState, route]);

  // Transient notices auto-dismiss; the busy toast stays until the run ends.
  useEffect(() => {
    if (!notice) return undefined;
    const timer = window.setTimeout(() => setNotice(null), 8000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const announceResult = (title: string, ok: boolean) => {
    setNotice({ text: ok ? t("toast.completed", { title }) : t("toast.needsAttention", { title }), tone: ok ? "good" : "warn", showResult: true });
  };
  const scrollToResult = () => {
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    document.getElementById("actionResult")?.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
  };

  // When a world dock is open, the left rail highlights the item that opened it
  // (approve→review, gates→health, intake→sources) instead of always "world".
  const dockNavId: Record<string, string> = { approve: "review", gates: "health", intake: "sources", source: "fontes", create: "create" };
  const active =
    route.kind === "world" || route.kind === "pageAlias"
      ? route.kind === "world" && route.query.dock && dockNavId[route.query.dock]
        ? dockNavId[route.query.dock]
        : route.kind === "world" && route.perspective === "atlas"
          ? "content"
          : "world"
      : route.kind;

  // Nav points straight at the dock on the CURRENT world (no redirect hop),
  // preserving the operator's perspective/context.
  const navWorld = worldFromRoute(route);
  const dockHref = (dock: "approve" | "intake" | "gates" | "source" | "create") =>
    hrefForWorldPatch(navWorld, { dock });

  const executeOperatorCommand = async (action: OperatorCommandCard) => {
    if (busyAction) return;
    if (route.demo) {
      setNotice({ text: t("demo.actionsOff"), tone: "info", showResult: false });
      return;
    }
    const title = operatorCommandTitle(action);
    setBusyAction(title);
    setNotice(null);
    try {
      const result = await runOperatorCommand(action.id, action.default_dry_run);
      setCommandResult(result);
      announceResult(title, result.ok);
    } catch (error) {
      setCommandResult({
        ok: false,
        action_id: action.id,
        dry_run: action.default_dry_run,
        error: error instanceof Error ? error.message : "action failed",
        results: []
      });
      announceResult(title, false);
    } finally {
      setBusyAction(null);
    }
  };
  const runWorkflow = async (operation: string, payload: Record<string, unknown> = {}, dryRun = true) => {
    if (busyAction) return;
    if (route.demo) {
      setNotice({ text: t("demo.gitOff"), tone: "info", showResult: false });
      return;
    }
    const title = operation.replaceAll("_", " ");
    setBusyAction(title);
    setNotice(null);
    try {
      const result = await runGitWorkflow(operation, payload, dryRun);
      setCommandResult(result);
      announceResult(title, result.ok);
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
      announceResult(title, false);
    } finally {
      setBusyAction(null);
    }
  };
  const notify = (text: string) => setNotice({ text, tone: "info", showResult: false });

  // Compose a work brief from a grounding spec and open the studio. Briefs need
  // the local operator (they read repo files) — the demo degrades honestly.
  const runBrief = async (spec: BriefSpec) => {
    if (briefBusy) return;
    // Genesis: the player acts through the REAL surfaces (CreateDock seeds,
    // docks compose briefs). The expected action advances the stage — the
    // staged snapshot IS the simulated result of the brief being approved.
    // Anything else gets an honest "in a real wiki this becomes a brief → PR".
    if (route.kind === "world" && route.demo && route.query.genesis) {
      if (genesisCreateMatches(route.query.stage, spec)) {
        setNotice({ text: t("genesis.actionDone"), tone: "good", showResult: false });
        navigate(genesisUrl(route.query.stage + 1, { visual: route.query.visual }));
      } else {
        setNotice({ text: t("genesis.simulatedBrief"), tone: "info", showResult: false });
      }
      return;
    }
    if (route.demo) {
      setNotice({ text: t("brief.demoOff"), tone: "info", showResult: false });
      return;
    }
    setBriefBusy(true);
    try {
      const record = await composeBrief(spec);
      setActiveBrief(record);
    } catch (error) {
      setNotice({
        text: t("brief.compose.failed", { error: error instanceof Error ? error.message : "failed" }),
        tone: "warn",
        showResult: false
      });
    } finally {
      setBriefBusy(false);
    }
  };
  const saveBrief = async (briefId: string, text: string) => {
    setBriefBusy(true);
    try {
      const record = await saveBriefText(briefId, text);
      setActiveBrief(record);
      setNotice({ text: t("brief.exit.saved"), tone: "good", showResult: false });
    } catch (error) {
      setNotice({
        text: t("brief.exit.saveFailed", { error: error instanceof Error ? error.message : "failed" }),
        tone: "warn",
        showResult: false
      });
    } finally {
      setBriefBusy(false);
    }
  };
  const removeBrief = async (briefId: string) => {
    setBriefBusy(true);
    try {
      await discardBrief(briefId);
      setNotice({ text: t("brief.exit.discarded"), tone: "info", showResult: false });
    } catch {
      // A failed discard is non-fatal; just close the studio.
    } finally {
      setBriefBusy(false);
      setActiveBrief(null);
    }
  };
  // Return a delivered job with feedback → compose a follow-up brief that
  // continues the SAME branch, and open it in the studio for review/execute.
  const returnJob = async (jobId: string, feedback: string) => {
    try {
      const brief = await returnCodexJob(jobId, feedback);
      if (brief.ok === false) {
        setNotice({ text: t("codex.job.failed", { error: brief.error || "return failed" }), tone: "warn", showResult: false });
        return;
      }
      setActiveBrief(brief);
    } catch (error) {
      setNotice({
        text: t("codex.job.failed", { error: error instanceof Error ? error.message : "failed" }),
        tone: "warn",
        showResult: false
      });
    }
  };
  // Reopen a saved draft brief from the Work tray into the studio.
  const resumeBrief = async (briefId: string) => {
    try {
      const record = await getBrief(briefId);
      if (record) setActiveBrief(record);
    } catch (error) {
      setNotice({
        text: t("brief.compose.failed", { error: error instanceof Error ? error.message : "failed" }),
        tone: "warn",
        showResult: false
      });
    }
  };
  // Execute exit: what you see is what runs — persist the current text first,
  // then submit the job by its verified sha. The endpoint fails closed when
  // Codex is unusable, so this only ever renders when capability.usable.
  const executeBrief = async (brief: BriefRecord, text: string) => {
    setBriefBusy(true);
    try {
      const saved = brief.status === "draft" ? await saveBriefText(brief.brief_id, text) : brief;
      if (!saved.brief_sha) {
        setNotice({ text: t("brief.exit.saveFailed", { error: saved.error || "no sha" }), tone: "warn", showResult: false });
        return;
      }
      const job = await spawnCodexJob(saved.brief_id, saved.brief_sha, { dryRun: false });
      if (job.ok === false) {
        setNotice({
          text: t("codex.job.failed", { error: job.error || job.reason || "rejected" }),
          tone: "warn",
          showResult: false
        });
        return;
      }
      setNotice({ text: t("codex.job.started", { status: job.status }), tone: "good", showResult: false });
      setActiveBrief(null);
      // Land the operator on the monitoring surface: delegated work should be
      // WATCHED, not fired and forgotten.
      const currentWorld = worldFromRoute(route);
      navigate(hrefForWorldPatch(currentWorld, { dock: "work" }));
    } catch (error) {
      setNotice({
        text: t("codex.job.failed", { error: error instanceof Error ? error.message : "failed" }),
        tone: "warn",
        showResult: false
      });
    } finally {
      setBriefBusy(false);
    }
  };

  const worldRoute = route.kind === "world" ? route : null;
  const isWorld = Boolean(worldRoute);
  const requestedDock = worldRoute && ["codex", "approve", "gates", "intake", "work", "source", "blocks"].includes(worldRoute.query.dock || "")
    ? worldRoute.query.dock
    : null;
  const dockPresence = useSurfacePresence(Boolean(requestedDock));
  const [lastDock, setLastDock] = useState<string | null>(requestedDock);
  if (requestedDock && requestedDock !== lastDock) setLastDock(requestedDock);
  const renderedDock = requestedDock ?? lastDock;
  const closeRequestedDock = () => {
    if (!worldRoute) return;
    const target = hrefForWorldPatch(worldRoute, { dock: null });
    // WebKit may keep the old navigation-store snapshot for the rest of the
    // touch turn when a fixed dock unmounts from its own close button. Crossing
    // one task boundary makes the URL and rendered surface resolve together.
    window.setTimeout(() => {
      navigate(target);
      // Also drive one local render. WebKit occasionally updates history but
      // defers the subscribed render for a fixed element's touch turn;
      // the local phase update makes the closing surface inert immediately
      // and lets React re-read the now-current URL snapshot.
      dockPresence.beginExit();
    }, 0);
  };

  // The demo TITLE SCREEN: /demo asks how you want to enter — found a world
  // from zero (genesis tutorial) or explore the full one. No bundle needed.
  if (route.kind === "demoGate") {
    return (
      <div className="demoGateShell">
        <div className="demoGateAppearance">
          <AppearanceControl />
        </div>
        <DemoGate />
      </div>
    );
  }

  const content = (() => {
    if (loadState.status === "loading") {
      if (worldRoute) {
        return <WorldRouteLoading readerOpen={Boolean(worldRoute.pageId && worldRoute.query.reader)} />;
      }
      return <main className="workspace"><section className="panel"><h1>Loading cockpit</h1></section></main>;
    }
    if (loadState.status === "error" || blockedSampleFallback) {
      const error =
        loadState.status === "error"
          ? loadState.error
          : "Sample fallback is blocked outside /demo. Start the backend on 127.0.0.1:8765 and Vite with WIKI_COCKPIT_PROXY_API=1 so /api/snapshot/pages.json returns the real repo JSON.";
      return (
        <main className="workspace">
          <section className="panel sampleFallbackBlocker" role="alert">
            <h1>Real snapshot required</h1>
            <p>{error}</p>
            <p>
              Demo/sample data is available only under <code>/demo</code>; the private cockpit must prove its own
              snapshot before visual validation.
            </p>
          </section>
        </main>
      );
    }
    const { bundle, runtime } = loadState;
    // Legacy routes render the one-frame "opening" placeholder while the
    // redirect effect above moves them to their world dock.
    if (route.kind === "review" || route.kind === "sources" || route.kind === "health" || route.kind === "pageAlias") {
      return <main className="workspace"><section className="panel"><h1>{t("misc.opening")}</h1></section></main>;
    }
    if (worldRoute) {
      return (
        <>
          <Suspense fallback={<WorldRouteLoading readerOpen={Boolean(worldRoute.pageId && worldRoute.query.reader)} />}>
          <RuntimeWorldView
            key={worldRoute.demo ? (worldRoute.query.genesis ? "genesis" : "demo") : "real"}
            bundle={bundle}
            runtime={runtime}
            route={worldRoute}
            bornPageIds={worldRoute.demo ? bornPageIds : []}
            onRun={executeOperatorCommand}
            onNotice={notify}
            onComposeBrief={runBrief}
            navigation={navigation}
            loadPageContent={operator.loadPageContent}
            loadTemporalGraph={operator.loadTemporalGraph}
            onSnapshotMismatch={worldRoute.demo ? undefined : refetchReal}
          />
          </Suspense>
        </>
      );
    }
    return null;
  })();

  const codexDockOpen = dockPresence.mounted && renderedDock === "codex";
  const gateDockOpen = dockPresence.mounted && renderedDock === "approve";
  const gatesDockOpen = dockPresence.mounted && renderedDock === "gates";
  const intakeDockOpen = dockPresence.mounted && renderedDock === "intake";
  const workDockOpen = dockPresence.mounted && renderedDock === "work";
  const sourceDockOpen = dockPresence.mounted && renderedDock === "source";
  const blocksDockOpen = dockPresence.mounted && renderedDock === "blocks";

  return (
    <div className={isWorld ? "appShell worldShellMode" : "appShell"}>
      {/* The menu is dead in the world: every destination
          lives in the bottom command bar now. The rail survives ONLY for the 2D
          fallback / degraded mode, which has no in-world command bar. */}
      {!isWorld && <Nav active={active} demo={route.demo} dockHref={dockHref} />}
      <div className="mainColumn">
        <header className="topBar">
          <div>
            <strong>Wiki Viva Cockpit</strong>
            {loadState.status === "ready" && (
              <span>
                {loadState.runtime.repoLabel || loadState.bundle.manifest.repo.repo_id} · {modeLabel(route.demo ? "static_demo" : loadState.runtime.mode || loadState.bundle.manifest.mode)}
              </span>
            )}
          </div>
          {/* Show the top-bar pill ONLY when there are real LOCAL changes to
              approve (uncommitted working-tree edits) — the same signal as the
              Approve mission. Being on a long-lived proposal branch (the private
              cockpit worktree always is) is NOT "pending approval"; an always-on
              git label was noise. Nothing to approve → no pill. */}
          <div className="topBarActions">
            {realRevalidationFailure && !route.demo && (
              <StatusPill tone="warn">
                <span title={t("snapshot.revalidationFailed", {
                  when: snapshotVerifiedAtLabel(realRevalidationFailure.lastSuccessAt)
                })}>
                  {t("snapshot.revalidationFailedShort", {
                    when: snapshotVerifiedAtLabel(realRevalidationFailure.lastSuccessAt)
                  })}
                </span>
              </StatusPill>
            )}
            {loadState.status === "ready" &&
              !route.demo &&
              loadState.bundle.git.worktree.changed_files.length > 0 && (
                <a href={dockHref("approve")} className="topBarPillLink">
                  <StatusPill tone="warn">
                    <span title={t("git.pendingApprovalTitle")}>
                      {t("git.pendingApprovalN", { n: loadState.bundle.git.worktree.changed_files.length })}
                    </span>
                  </StatusPill>
                </a>
              )}
            <AppearanceControl />
          </div>
        </header>
        {route.demo && (
          <div className="demoBanner" role="note">
            <Sparkles size={15} />
            <span>{t(worldRoute?.query.genesis ? "demo.bannerGenesis" : "demo.banner")}</span>
          </div>
        )}
        {content}
        {activeBrief && !route.demo && (
          <BriefStudio
            brief={activeBrief}
            capability={codexCapability}
            busy={briefBusy}
            git={loadState.status === "ready" ? loadState.bundle.git : undefined}
            onSaveText={saveBrief}
            onDiscard={removeBrief}
            onExecute={codexCapability.usable ? executeBrief : undefined}
            onDiagnose={openCodexDock}
            onNotice={notify}
            onClose={() => setActiveBrief(null)}
          />
        )}
        {dockPresence.mounted && (
        <div
          className={dockPresence.phase === "closing" ? "appDockPresence closing" : "appDockPresence"}
          aria-hidden={dockPresence.phase === "closing" ? true : undefined}
          ref={(target) => {
            if (target) target.inert = dockPresence.phase === "closing";
          }}
          data-surface-phase={dockPresence.phase}
          onAnimationEnd={(event) => {
            if (dockPresence.phase === "closing" && event.currentTarget === event.target) dockPresence.completeExit();
          }}
        >
        {codexDockOpen && worldRoute && (
          <CodexDock
            capability={codexCapability}
            busy={codexBusy}
            onReverify={reverifyCodex}
            onClose={closeRequestedDock}
          />
        )}
        {gateDockOpen && worldRoute && loadState.status === "ready" && (
          <GateDock
            bundle={loadState.bundle}
            busy={Boolean(busyAction)}
            demo={route.demo}
            loadFileDiff={operator.loadFileDiff}
            runGate={operator.runGate}
            onWorkflow={runWorkflow}
            onComposeBrief={runBrief}
            onNotice={notify}
            onRefetch={refetchReal}
            onClose={closeRequestedDock}
          />
        )}
        {gatesDockOpen && worldRoute && loadState.status === "ready" && (
          <GatesDock
            bundle={loadState.bundle}
            demo={route.demo}
            runGate={operator.runGate}
            onComposeBrief={runBrief}
            onNotice={notify}
            onRefetch={refetchReal}
            onClose={closeRequestedDock}
          />
        )}
        {intakeDockOpen && worldRoute && loadState.status === "ready" && (
          <IntakeDock
            bundle={loadState.bundle}
            initialSrc={worldRoute.query.src}
            demo={route.demo}
            intakeCopy={operator.intakeCopy}
            onComposeBrief={runBrief}
            onOpenCreate={() => navigate(hrefForWorldPatch(worldRoute, { dock: "create", src: null }))}
            onNotice={notify}
            onClose={closeRequestedDock}
          />
        )}
        {workDockOpen && worldRoute && (
          <WorkDock
            capability={codexCapability}
            demo={route.demo}
            operator={operator}
            onResumeBrief={resumeBrief}
            onReturn={returnJob}
            onDiagnose={openCodexDock}
            onNotice={notify}
            onClose={closeRequestedDock}
          />
        )}
        {sourceDockOpen && worldRoute && loadState.status === "ready" && (
          <SourceDock
            bundle={loadState.bundle}
            sourceId={worldRoute.query.src}
            demo={route.demo}
            onComposeBrief={runBrief}
            onRequestBrief={composeSourceBrief}
            onNotice={notify}
            onOpenPage={(pathOrId) => navigate(hrefForWorldPatch(worldRoute, { dock: null, pageId: pathOrId, reader: true }))}
            onOpenSource={(id) => navigate(hrefForWorldPatch(worldRoute, { dock: "source", src: id || null }))}
            onClose={closeRequestedDock}
          />
        )}
        {/* dock=create is answered INSIDE WorldView: the spatial seed flow in
            the canvas, or the bottom sheet as its declared 2D fallback. */}
        {blocksDockOpen && worldRoute && loadState.status === "ready" && (
          <BlocksDock
            bundle={loadState.bundle}
            focusId={worldRoute.query.center || worldRoute.query.src || worldRoute.pageId || null}
            readOnly={route.demo && !worldRoute.query.genesis}
            onSelectAnchor={(anchorId) => navigate(hrefForWorldPatch(worldRoute, { dock: "blocks", src: anchorId, center: anchorId }))}
            onOpenPage={(pageId) => navigate(hrefForWorldPatch(worldRoute, { dock: null, pageId, reader: true }))}
            onAttach={(id, anchorId) => {
              // The REAL attach action. Genesis: the expected attach advances the
              // stage (the world re-renders with the block truly in the stack).
              // Live wiki: it composes a brief — attach is a PR like everything.
              if (worldRoute.query.genesis) {
                if (genesisAttachMatches(worldRoute.query.stage, id)) {
                  notify(t("genesis.actionDone"));
                  navigate(genesisUrl(worldRoute.query.stage + 1, { visual: worldRoute.query.visual }));
                } else {
                  notify(t("genesis.simulatedBrief"));
                }
                return;
              }
              runBrief({
                mission_kind: "verify",
                theme: `attach-${id.replace(/[^a-z0-9_.-]/gi, "")}`,
                grounding: { page_ids: [anchorId], attach_context_package: true },
                intent:
                  `Attach \`${id}\` to the anchor page's frontmatter (a block goes under \`blocks:\`, ` +
                  `a package under \`packages:\`), keep every existing key intact, regenerate the ` +
                  `snapshot, and open a draft PR. Never touch main directly.`
              });
            }}
            onClose={closeRequestedDock}
          />
        )}
        </div>
        )}
        {commandResult && (
          <div className={isWorld ? "worldOutputDock" : undefined}>
            {isWorld && (
              <button className="readerClose outputDockClose" onClick={() => setCommandResult(null)} title="Fechar resultado" type="button">
                ×
              </button>
            )}
            <CommandOutput result={commandResult} />
          </div>
        )}
        {busyAction && (
          <div className="actionToast running" role="status">
            <span className="toastSpinner" aria-hidden />
            <span>{t("toast.running", { title: busyAction })}</span>
          </div>
        )}
        {!busyAction && notice && !(route.demo && notice.text === realRevalidationNoticeRef.current) && (
          <div className={`actionToast tone-${notice.tone}`} role="status">
            <span>{notice.text}</span>
            {notice.showResult && (
              <button onClick={scrollToResult} type="button">
                {t("toast.viewResult")}
              </button>
            )}
            <button className="toastClose" onClick={() => setNotice(null)} title="Dismiss" type="button">
              ×
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
