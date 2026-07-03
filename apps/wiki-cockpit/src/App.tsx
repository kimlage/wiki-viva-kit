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
import { useEffect, useMemo, useState } from "react";
import { WorldView } from "./components/WorldView";
import { BriefStudio } from "./components/BriefStudio";
import { CodexDock } from "./components/CodexDock";
import { CreateDock } from "./components/CreateDock";
import { GateDock } from "./components/GateDock";
import { GatesDock } from "./components/GatesDock";
import { IntakeDock } from "./components/IntakeDock";
import { WorkDock } from "./components/WorkDock";
import { SourceDock } from "./components/SourceDock";
import { ExpandablePre } from "./components/ExpandablePre";
import { configureLanguage, t } from "./data/i18n";
import { qualityFlagCount, reviewChecklist } from "./data/model";
import { contextLabel, pageTypeLabel, registerContextPalette } from "./data/presentation";
import {
  buildIngestionPlan,
  composeBrief,
  discardBrief,
  getBrief,
  loadCodexCapability,
  loadSnapshotBundle,
  returnCodexJob,
  runCockpitAction,
  runGitWorkflow,
  runIngestionStep,
  saveBriefText,
  spawnCodexJob
} from "./data/snapshot";
import type { RuntimeConfig } from "./data/runtimeConfig";
import { buildUrl, installLinkInterceptor, navigate, parseRoute, patchWorld, useRouteUrl, worldFromRoute } from "./router";
import type { Route } from "./router";
import { groupKeyForPage } from "./scene/perspectives";
import type { ActionCard, BriefRecord, BriefSpec, CodexCapability, CommandResultEntry, CommandRunResult, DiffFile, IngestionPlan, IngestionStage, PageRecord, SnapshotBundle, SourceFinding, SourceTriageResult } from "./types";
import { CODEX_UNAVAILABLE } from "./types";
import "./styles.css";

type LoadState =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "ready"; bundle: SnapshotBundle; source: string; runtime: RuntimeConfig };

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
    { href: `${prefix}/w/radar`, id: "world", label: t("nav.home"), icon: <Activity size={17} /> },
    { href: dockHref("approve"), id: "review", label: t("nav.approve"), icon: <GitPullRequest size={17} /> },
    { href: dockHref("intake"), id: "sources", label: t("nav.add"), icon: <Inbox size={17} /> },
    { href: dockHref("create"), id: "create", label: t("nav.create"), icon: <Sprout size={17} /> },
    { href: dockHref("source"), id: "fontes", label: t("nav.sources"), icon: <Database size={17} /> },
    { href: dockHref("gates"), id: "health", label: t("nav.health"), icon: <ShieldCheck size={17} /> },
    { href: `${prefix}/w/atlas`, id: "content", label: t("nav.content"), icon: <FileText size={17} /> },
    demo
      ? { href: "/w/radar", id: "demo", label: t("nav.exitDemo"), icon: <Sparkles size={17} /> }
      : { href: "/demo/w/radar", id: "demo", label: t("nav.demo"), icon: <Sparkles size={17} /> }
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
    "git-status": "Check work state",
    "review-local-changes": "Inspect changed content",
    "run-honesty-gates": "Verify approval readiness",
    "pr-summary": "Prepare approval summary",
    "graph-check": "Check related content"
  };
  return labels[action.id] || action.title;
}

function actionReason(action: ActionCard): string {
  const labels: Record<string, string> = {
    "review-local-changes": "Shows changed content before saving a version or preparing approval.",
    "run-honesty-gates": "Confirms whether local checks support the next human decision.",
    "pr-summary": "Prepares a human-readable summary from changed content, affected areas and privacy notes.",
    "graph-check": "Checks whether related content and impact links still make sense."
  };
  return labels[action.id] || action.human_reason;
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

function commandResultTitle(result: CommandRunResult): string {
  if ("summary" in result && result.summary) return result.summary;
  if ("operation" in result) return result.operation.replaceAll("_", " ");
  if ("action_id" in result) {
    const key = `actionTitle.${result.action_id}`;
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

function approvalActionLabel(actionId: string): string {
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
            {prAction && (
              <button className="actionButton" onClick={() => onRun(prAction)} title={actionReason(prAction)}>
                <Play size={16} />
                <span>{approvalActionLabel(prAction.id)}</span>
              </button>
            )}
            {reviewAction && (
              <button className="secondaryButton" onClick={() => onRun(reviewAction)} title={actionReason(reviewAction)}>
                <Search size={16} />
                <span>{approvalActionLabel(reviewAction.id)}</span>
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
            {gateAction && (
              <button className="actionButton" onClick={() => onRun(gateAction)} title={actionReason(gateAction)}>
                <Play size={16} />
                <span>{approvalActionLabel(gateAction.id)}</span>
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
        <summary>Advanced: request editor and exact evidence</summary>
        <PrHandoffPanel bundle={bundle} onWorkflow={onWorkflow} />
        <DiffFilmstrip bundle={bundle} />
        <SyncMainPanel bundle={bundle} onWorkflow={onWorkflow} />
        <GitWorkflowPanel bundle={bundle} onWorkflow={onWorkflow} />
        <section className="panel">
          <div className="panelHeader">
            <h2>Changed Content Details</h2>
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

function HealthView({ bundle, demo, onRun }: { bundle: SnapshotBundle; demo: boolean; onRun: (action: ActionCard) => void }) {
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
            <a className="healthAttentionItem" href={`${demo ? "/demo" : ""}/pages/${encodeURIComponent(page.id)}`} key={page.id}>
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
            <h2>Check Details</h2>
            <StatusPill tone={gateStatusTone(bundle.gates.status)}>{gateStatusLabel(bundle.gates.status)}</StatusPill>
          </div>
          <ul className="plainList commandList">
            {bundle.gates.gates.map((gate) => (
              <li key={gate.id}>
                <strong>{gateCheckLabel(gate.id)}</strong>
                <details className="auditDetails">
                  <summary>Local check details</summary>
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
                  <summary>Local run details</summary>
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
              <summary>Source details</summary>
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
                    <summary>Suggested pages</summary>
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
                    <summary>Suggested entities</summary>
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

export function App() {
  const url = useRouteUrl();
  const route = useMemo<Route>(() => {
    const [pathname, search = ""] = url.split("?");
    return parseRoute(pathname, search ? `?${search}` : "");
  }, [url]);
  const [realState, setRealState] = useState<LoadState>({ status: "loading" });
  const [demoState, setDemoState] = useState<LoadState>({ status: "loading" });
  const [commandResult, setCommandResult] = useState<CommandRunResult | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ text: string; tone: "good" | "warn" | "info"; showResult: boolean } | null>(null);
  const [activeBrief, setActiveBrief] = useState<BriefRecord | null>(null);
  const [briefBusy, setBriefBusy] = useState(false);
  const [codexCapability, setCodexCapability] = useState<CodexCapability>(CODEX_UNAVAILABLE);
  const [codexBusy, setCodexBusy] = useState(false);

  // One snapshot bundle per universe, loaded once per session — it survives
  // all navigation. Demo is an in-memory switch, never a document reload.
  useEffect(() => {
    loadSnapshotBundle({ demo: false })
      .then(({ bundle, source, runtime }) => setRealState({ status: "ready", bundle, source, runtime }))
      .catch((error: Error) => setRealState({ status: "error", error: error.message }));
  }, []);
  // Refetch the real bundle after a mutating action (e.g. running gates writes
  // receipts) so the world reacts. Keeps the same runtime/source.
  const refetchReal = () => {
    loadSnapshotBundle({ demo: false })
      .then(({ bundle, source, runtime }) => setRealState({ status: "ready", bundle, source, runtime }))
      .catch(() => undefined);
  };
  useEffect(() => {
    if (!route.demo || demoState.status === "ready") return;
    loadSnapshotBundle({ demo: true })
      .then(({ bundle, source, runtime }) => setDemoState({ status: "ready", bundle, source, runtime }))
      .catch((error: Error) => setDemoState({ status: "error", error: error.message }));
  }, [demoState.status, route.demo]);

  // The SPA router owns every internal anchor click.
  useEffect(() => installLinkInterceptor(), []);

  const loadState = route.demo ? demoState : realState;

  // Live Codex capability: only meaningful with the local operator, so it is
  // probed once the real bundle is ready and never in the demo. It fails closed.
  useEffect(() => {
    if (loadState.status !== "ready") return;
    loadCodexCapability(loadState.runtime)
      .then(setCodexCapability)
      .catch(() => setCodexCapability(CODEX_UNAVAILABLE));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadState.status, route.demo]);

  // Re-probe on demand (the Codex diagnostics dock's Re-verify button): the
  // moment the owner reinstalls / logs in / restarts the operator, the ladder
  // flips without a page reload.
  const reverifyCodex = () => {
    if (loadState.status !== "ready" || codexBusy) return;
    setCodexBusy(true);
    loadCodexCapability(loadState.runtime)
      .then(setCodexCapability)
      .catch(() => setCodexCapability(CODEX_UNAVAILABLE))
      .finally(() => setCodexBusy(false));
  };
  const openCodexDock = () => {
    if (route.kind === "world") navigate(buildUrl(patchWorld(route, { dock: "codex" })));
  };

  // The base system is English; the whole UI flips when the wiki's configured
  // language starts with "pt" (runtime config wins over the manifest).
  configureLanguage(
    loadState.status === "ready" ? loadState.runtime.language || loadState.bundle.manifest.repo.language : "en",
    loadState.status === "ready" ? loadState.runtime.strings : undefined
  );

  // Hue = area: register every context of THIS wiki so sorted names get
  // distinct palette slots (deterministic, no hash collisions up to 12 areas).
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

  // Legacy alias: /pages/:id lands on the same page in the new world
  // (/w/atlas/:context/:group/:id?reader=1). /pages lists become the atlas.
  useEffect(() => {
    if (route.kind !== "pageAlias" || loadState.status !== "ready") return;
    const world = worldFromRoute(route);
    if (!route.pageId) {
      navigate(buildUrl({ ...world, perspective: "atlas" }), { replace: true });
      return;
    }
    const page = loadState.bundle.pages.pages.find((item) => item.id === route.pageId || item.path === route.pageId);
    if (!page) {
      navigate(buildUrl({ ...world, perspective: "atlas" }), { replace: true });
      return;
    }
    navigate(
      buildUrl({
        ...world,
        perspective: "atlas",
        context: page.context || "system",
        group: groupKeyForPage("atlas", page),
        pageId: page.id,
        query: { ...world.query, reader: true }
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
    document.getElementById("actionResult")?.scrollIntoView({ behavior: "smooth", block: "start" });
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
  const dockHref = (dock: "approve" | "intake" | "gates" | "source" | "create") => buildUrl(patchWorld(navWorld, { dock }));

  const runAction = async (action: ActionCard) => {
    if (busyAction) return;
    if (route.demo) {
      setNotice({ text: t("demo.actionsOff"), tone: "info", showResult: false });
      return;
    }
    const title = actionTitle(action);
    setBusyAction(title);
    setNotice(null);
    try {
      const result = await runCockpitAction(action.id, action.default_dry_run);
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
      navigate(buildUrl(patchWorld(worldFromRoute(route), { dock: "work" })));
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

  const content = (() => {
    if (loadState.status === "loading") {
      return <main className="workspace"><section className="panel"><h1>Loading cockpit</h1></section></main>;
    }
    if (loadState.status === "error") {
      return <main className="workspace"><section className="panel"><h1>Snapshot unavailable</h1><p>{loadState.error}</p></section></main>;
    }
    const { bundle, runtime } = loadState;
    if (route.kind === "review") return <ReviewView bundle={bundle} onRun={runAction} onWorkflow={runWorkflow} />;
    if (route.kind === "sources") return <SourcesView bundle={bundle} onCommand={setCommandResult} />;
    if (route.kind === "health") return <HealthView bundle={bundle} demo={route.demo} onRun={runAction} />;
    if (route.kind === "pageAlias") {
      return <main className="workspace"><section className="panel"><h1>{t("misc.opening")}</h1></section></main>;
    }
    if (worldRoute) {
      return (
        <WorldView
          key={worldRoute.demo ? "demo" : "real"}
          bundle={bundle}
          runtime={runtime}
          route={worldRoute}
          onRun={runAction}
          onNotice={notify}
          onComposeBrief={runBrief}
        />
      );
    }
    return null;
  })();

  const codexDockOpen = route.kind === "world" && route.query.dock === "codex";
  const gateDockOpen = route.kind === "world" && route.query.dock === "approve";
  const gatesDockOpen = route.kind === "world" && route.query.dock === "gates";
  const intakeDockOpen = route.kind === "world" && route.query.dock === "intake";
  const workDockOpen = route.kind === "world" && route.query.dock === "work";
  const sourceDockOpen = route.kind === "world" && route.query.dock === "source";
  const createDockOpen = route.kind === "world" && route.query.dock === "create";

  return (
    <div className={isWorld ? "appShell worldShellMode" : "appShell"}>
      {/* The menu is dead in the world (Kim: "matar o menu"): every destination
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
        </header>
        {route.demo && (
          <div className="demoBanner" role="note">
            <Sparkles size={15} />
            <span>{t("demo.banner")}</span>
          </div>
        )}
        {content}
        {activeBrief && (
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
        {codexDockOpen && worldRoute && (
          <CodexDock
            capability={codexCapability}
            busy={codexBusy}
            onReverify={reverifyCodex}
            onClose={() => navigate(buildUrl(patchWorld(worldRoute, { dock: null })))}
          />
        )}
        {gateDockOpen && worldRoute && loadState.status === "ready" && (
          <GateDock
            bundle={loadState.bundle}
            busy={Boolean(busyAction)}
            demo={route.demo}
            onWorkflow={runWorkflow}
            onComposeBrief={runBrief}
            onNotice={notify}
            onRefetch={refetchReal}
            onClose={() => navigate(buildUrl(patchWorld(worldRoute, { dock: null })))}
          />
        )}
        {gatesDockOpen && worldRoute && loadState.status === "ready" && (
          <GatesDock
            bundle={loadState.bundle}
            demo={route.demo}
            onComposeBrief={runBrief}
            onNotice={notify}
            onRefetch={refetchReal}
            onClose={() => navigate(buildUrl(patchWorld(worldRoute, { dock: null })))}
          />
        )}
        {intakeDockOpen && worldRoute && loadState.status === "ready" && (
          <IntakeDock
            bundle={loadState.bundle}
            initialSrc={worldRoute.query.src}
            onComposeBrief={runBrief}
            onOpenCreate={() => navigate(buildUrl(patchWorld(worldRoute, { dock: "create", src: null })))}
            onNotice={notify}
            onClose={() => navigate(buildUrl(patchWorld(worldRoute, { dock: null })))}
          />
        )}
        {workDockOpen && worldRoute && (
          <WorkDock
            capability={codexCapability}
            demo={route.demo}
            onResumeBrief={resumeBrief}
            onReturn={returnJob}
            onDiagnose={openCodexDock}
            onNotice={notify}
            onClose={() => navigate(buildUrl(patchWorld(worldRoute, { dock: null })))}
          />
        )}
        {sourceDockOpen && worldRoute && loadState.status === "ready" && (
          <SourceDock
            bundle={loadState.bundle}
            sourceId={worldRoute.query.src}
            onComposeBrief={runBrief}
            onNotice={notify}
            onOpenPage={(pathOrId) => navigate(buildUrl(patchWorld(worldRoute, { dock: null, pageId: pathOrId, reader: true })))}
            onOpenSource={(id) => navigate(buildUrl(patchWorld(worldRoute, { dock: "source", src: id || null })))}
            onClose={() => navigate(buildUrl(patchWorld(worldRoute, { dock: null })))}
          />
        )}
        {createDockOpen && worldRoute && loadState.status === "ready" && (
          <CreateDock
            bundle={loadState.bundle}
            initialType={worldRoute.query.src}
            initialQuadrant={worldRoute.query.quadrant}
            onComposeBrief={runBrief}
            onClose={() => navigate(buildUrl(patchWorld(worldRoute, { dock: null })))}
          />
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
        {!busyAction && notice && (
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
