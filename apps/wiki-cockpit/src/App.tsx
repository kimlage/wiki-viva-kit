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
        <h2>Action Log</h2>
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
        <h2>Evidence Board</h2>
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

function pageMatches(page: PageRecord, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [page.title, page.path, page.context, page.page_type, page.summary, ...page.source_refs]
    .join(" ")
    .toLowerCase()
    .includes(needle);
}

type MapIntentId = "review" | "evidence" | "stale" | "browse";

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
      label: "Decide what changed",
      detail: "Highlight pages touched by the current proposal plus risky or stale neighbors.",
      tone: pages.length ? "warn" : "good",
      count: pages.length
    };
  }
  if (intent === "evidence") {
    return {
      label: "Verify evidence",
      detail: "Show pages with source references or source records before trusting a claim.",
      tone: pages.length ? "info" : "muted",
      count: pages.length
    };
  }
  if (intent === "stale") {
    return {
      label: "Refresh old content",
      detail: "Focus the map on pages that may need a new read or update.",
      tone: pages.length ? "warn" : "good",
      count: pages.length
    };
  }
  return {
    label: "Browse the wiki",
    detail: "Use the map as navigation: pick a node, follow its route and open the page.",
    tone: "info",
    count: pages.length
  };
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
  const commands = bundle.actions.actions
    .filter((action) => ["graph-check", "review-local-changes", "pr-summary", "run-honesty-gates"].includes(action.id))
    .flatMap((action) => action.commands.map((command) => `- ${command.argv.join(" ")}`));
  return [
    "Review Packet",
    "",
    `Repo: ${bundle.manifest.repo.repo_id}`,
    `Workspace: ${bundle.git.current_branch || "unknown"}`,
    `Approval state: ${bundle.git.proposal.human_gate_state}`,
    `Selected content: ${pages.length}`,
    `Areas: ${contexts.join(", ") || "none"}`,
    `Evidence refs: ${sourceRefs.length ? sourceRefs.join(", ") : "none"}`,
    "",
    "Content to review:",
    ...pages.map((page) => `- ${page.path} [${page.context}/${page.page_type || "page"}] freshness=${page.freshness_state} refs=${page.source_refs.length}`),
    "",
    "Checks to run before approval:",
    ...(commands.length ? commands : ["- No review checks available in this snapshot."]),
    "",
    "Human decision: approve or request changes in the Pull Request."
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
  const intents: MapIntentId[] = ["review", "evidence", "stale", "browse"];
  const activePages = pagesForMapIntent(bundle, activeIntent);
  return (
    <section className="panel mapIntentPanel">
      <div className="panelHeader">
        <h2>Use The Map To</h2>
        <StatusPill tone="info">{mapIntentCopy(activeIntent, bundle).count} highlighted</StatusPill>
      </div>
      <div className="intentButtons" aria-label="Map work modes">
        {intents.map((intent) => {
          const copy = mapIntentCopy(intent, bundle);
          return (
            <button className={activeIntent === intent ? "intentButton active" : "intentButton"} onClick={() => onChoose(intent)} key={intent}>
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
        {activePages.length === 0 && <p>No pages match this map mode in the current snapshot.</p>}
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
        <h2>Content Preview</h2>
        <StatusPill tone={selected.freshness_state === "fresh" ? "good" : selected.freshness_state === "stale" ? "warn" : "muted"}>
          {selected.freshness_state}
        </StatusPill>
      </div>
      <div className="drawerLead">
        <div>
          <h3>{selected.title}</h3>
          <p>{selected.summary || "No summary text in snapshot."}</p>
        </div>
        <a className="secondaryButton" href={`/pages/${encodeURIComponent(selected.id)}`} title="Open page cockpit">
          <ExternalLink size={16} />
          <span>Open page</span>
        </a>
      </div>
      <dl className="kv">
        <dt>Page address</dt>
        <dd>{selected.path}</dd>
        <dt>Content kind</dt>
        <dd>{selected.page_type || "unknown"}</dd>
        <dt>Area</dt>
        <dd>{selected.context}</dd>
        <dt>Evidence state</dt>
        <dd>frontmatter page · {selected.visibility} · source_refs {selected.source_refs.length}</dd>
      </dl>
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
            {proofs.length === 0 && <li>{selected.source_refs.length ? selected.source_refs.join(", ") : "No source refs listed."}</li>}
          </ul>
        </div>
        <div>
          <h3>Related Content</h3>
          <ul className="plainList compactList">
            {related.map((page) => (
              <li key={page.id}><button className="textButton" onClick={() => onSelect(page.id)}>{page.title}</button></li>
            ))}
            {related.length === 0 && <li>No graph neighbors in snapshot.</li>}
          </ul>
        </div>
      </div>
      <div className="buttonCluster">
        <button className={isBundled ? "secondaryButton active" : "secondaryButton"} onClick={() => onToggleBundle(selected.id)} title="Toggle impact review bundle">
          <ListChecks size={16} />
          <span>{isBundled ? "Remove from packet" : "Add to review packet"}</span>
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
    <section className="panel impactBundlePanel" aria-label="Review Packet">
      <div className="panelHeader">
        <h2>Review Packet</h2>
        <StatusPill tone={pages.length ? "info" : "muted"}>{pages.length} pages</StatusPill>
      </div>
      <div className="bundleMetrics" aria-label="Impact bundle metrics">
        <Stat icon={<FileText size={18} />} label="Contexts" value={contexts.length} tone="info" />
        <Stat icon={<Clock3 size={18} />} label="Stale" value={staleCount} tone={staleCount ? "warn" : "good"} />
        <Stat icon={<Search size={18} />} label="Source refs" value={sourceRefs.length} tone={sourceRefs.length ? "info" : "muted"} />
        <Stat icon={<GitPullRequest size={18} />} label="Gate" value={bundle.git.proposal.human_gate_state} tone={bundle.git.proposal.is_proposal_branch ? "warn" : "info"} />
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
                <span>{page.context} / {page.page_type || "page"} / {page.freshness_state}</span>
                <code>{page.path}</code>
                <button className="textButton" onClick={() => onRemove(page.id)}>Remove</button>
              </article>
            ))}
            {pages.length === 0 && <p>No pages selected.</p>}
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
          <h3>Approval Notes</h3>
          <pre className="bundlePreview">{reviewText}</pre>
          <div className="buttonCluster">
            {actions.map((action) => (
              <button className="secondaryButton" key={action.id} onClick={() => onRun(action)} title={action.human_reason}>
                {action.id === "pr-summary" ? <GitPullRequest size={16} /> : <ListChecks size={16} />}
                <span>{action.title}</span>
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
          <input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="title, page address, area, source" />
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
              <small>{page.context} · {page.page_type || "page"} · {page.path}</small>
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
          <p>{bundle.operations.title} · {bundle.manifest.repo.repo_id} · {bundle.manifest.generated_at}</p>
        </div>
        <SystemScene nodes={bundle.graph.nodes} git={bundle.git} selectedPageId={selectedPageId} highlightedPageIds={highlightedPageIds} onNodeSelect={setSelectedPageId} />
      </section>
      <section className="statGrid" aria-label="Operational summary">
        <Stat icon={<BadgeCheck size={18} />} label="Up to date" value={fresh} tone="good" />
        <Stat icon={<Clock3 size={18} />} label="Needs refresh" value={stale} tone={stale ? "warn" : "good"} />
        <Stat icon={<GitBranch size={18} />} label="Workspace" value={bundle.git.current_branch || "none"} tone={bundle.git.proposal.is_proposal_branch ? "warn" : "info"} />
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

function prHandoffTitle(bundle: SnapshotBundle): string {
  const theme = bundle.git.proposal.theme || bundle.git.current_branch || bundle.manifest.repo.repo_id;
  return `Review ${theme}`;
}

function prHandoffBody(bundle: SnapshotBundle): string {
  const files = bundle.diff.files.slice(0, 20);
  const changedLines = files.length
    ? files.map((file) => `- ${file.path} (${file.status || "changed"}, +${file.additions}/-${file.deletions}, ${file.category})`)
    : ["- No changed files in the current snapshot."];
  const gateLines = bundle.gates.gates.length
    ? bundle.gates.gates.map((gate) => `- [ ] ${gate.argv.join(" ")}`)
    : ["- [ ] No machine gates listed in the current snapshot."];
  const riskHints = [...new Set(files.flatMap((file) => file.risk_hints))];
  return [
    "## Summary",
    `- Branch: ${bundle.git.current_branch || "unknown"}`,
    `- Base: ${bundle.diff.compare.base_ref || bundle.git.default_branch}`,
    `- Files: ${bundle.diff.summary.file_count} total, ${bundle.diff.summary.branch_file_count} branch, ${bundle.diff.summary.working_tree_file_count} local`,
    `- Privacy review: ${bundle.diff.summary.privacy_review_required ? "required" : "not flagged"}`,
    `- Risk hints: ${riskHints.length ? riskHints.join(", ") : "none"}`,
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
    "- [ ] Markdown diff inspected",
    "- [ ] No merge from the cockpit"
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
  if (!git.available) return { label: "Cannot decide yet", detail: "Git state is unavailable in this snapshot.", tone: "bad" };
  if (!git.proposal.is_proposal_branch && git.current_branch !== git.default_branch) {
    return { label: "Outside the approval flow", detail: "Move the work to a proposal branch before asking for approval.", tone: "bad" };
  }
  if (git.current_branch === git.default_branch) {
    return { label: "Approved wiki view", detail: "You are looking at the approved branch. Use sync only after an external PR merge.", tone: git.worktree.clean ? "good" : "warn" };
  }
  if (bundle.diff.summary.privacy_review_required) {
    return { label: "Needs privacy review", detail: "Inspect the changed content and risk hints before opening the Pull Request.", tone: "warn" };
  }
  if (!git.proposal.draft_pr_url) {
    return { label: "Prepare the approval request", detail: "The proposal is local/published, but no Pull Request is linked in this snapshot.", tone: "warn" };
  }
  if (git.proposal.human_gate_state === "draft") {
    return { label: "Ready for human review", detail: "Open the draft Pull Request, inspect the packet, then mark it ready outside the cockpit.", tone: "info" };
  }
  if (git.proposal.human_gate_state === "ready_for_review") {
    return { label: "Waiting on human approval", detail: "The Pull Request is the human gate; merge remains external to the base cockpit.", tone: "info" };
  }
  if (git.proposal.human_gate_state === "merged") {
    return { label: "Approved externally", detail: "Switch to the approved branch and fast-forward sync the local checkout.", tone: "good" };
  }
  return { label: "Review the packet", detail: "Use the evidence, checks and approval request below to decide the next step.", tone: "info" };
}

function ApprovalJourney({ bundle }: { bundle: SnapshotBundle }) {
  const risks = approvalRiskHints(bundle);
  const steps = [
    {
      label: "Understand the change",
      status: bundle.diff.summary.file_count ? "ready" : "empty",
      detail: `${bundle.diff.summary.file_count} changed file(s), +${bundle.diff.summary.insertions} / -${bundle.diff.summary.deletions}`
    },
    {
      label: "Check evidence",
      status: bundle.gates.status,
      detail: `${bundle.gates.gates.length} automated check(s) available`
    },
    {
      label: "Review risk",
      status: bundle.diff.summary.privacy_review_required ? "needs_review" : "clear",
      detail: risks.length ? risks.map((hint) => hint.replaceAll("_", " ")).join(", ") : "No risk hints in the current diff"
    },
    {
      label: "Prepare approval request",
      status: bundle.git.proposal.draft_pr_url ? "linked" : bundle.git.proposal.human_gate_state,
      detail: bundle.git.proposal.draft_pr_url || "No Pull Request linked yet"
    },
    {
      label: "Approve externally",
      status: bundle.git.proposal.human_gate_state,
      detail: "Final approval and merge stay in the GitHub Pull Request"
    }
  ];
  return (
    <section className="panel approvalJourney">
      <div className="panelHeader">
        <h2>Approval Path</h2>
        <StatusPill tone={approvalDecision(bundle).tone}>{approvalDecision(bundle).label}</StatusPill>
      </div>
      <div className="journeySteps" aria-label="Human approval path">
        {steps.map((step, index) => (
          <article className={`journeyStep gateStep-${gateStepTone(step.status)}`} key={step.label}>
            <span className="stageIndex">{index + 1}</span>
            <div>
              <strong>{step.label}</strong>
              <p>{step.detail}</p>
            </div>
            <StatusPill tone={gateStepTone(step.status)}>{step.status.replaceAll("_", " ")}</StatusPill>
          </article>
        ))}
      </div>
    </section>
  );
}

function DecisionPacket({ bundle }: { bundle: SnapshotBundle }) {
  const risks = approvalRiskHints(bundle);
  const sourceRefCount = bundle.pages.pages.reduce((total, page) => total + page.source_refs.length, 0);
  const prUrl = bundle.git.proposal.draft_pr_url;
  return (
    <section className="panel decisionPacket">
      <div className="panelHeader">
        <h2>Decision Packet</h2>
        <StatusPill tone={bundle.diff.summary.privacy_review_required ? "warn" : "info"}>
          {bundle.diff.summary.privacy_review_required ? "review risk" : "ready to inspect"}
        </StatusPill>
      </div>
      <div className="decisionCards">
        <article>
          <strong>What changed</strong>
          <p>{bundle.diff.summary.file_count} file(s), {bundle.diff.summary.branch_file_count} from the branch and {bundle.diff.summary.working_tree_file_count} still local.</p>
        </article>
        <article>
          <strong>Evidence available</strong>
          <p>{sourceRefCount} source reference(s) across the snapshot, plus {bundle.gates.gates.length} automated check command(s).</p>
        </article>
        <article>
          <strong>Risk to review</strong>
          <p>{risks.length ? risks.map((hint) => hint.replaceAll("_", " ")).join(", ") : "No explicit risk hints in the diff."}</p>
        </article>
        <article>
          <strong>Approval request</strong>
          <p>{prUrl ? "Pull Request is linked and can be opened for the human decision." : "No Pull Request linked yet; prepare or update the review request below."}</p>
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
      label: "Proposal branch",
      status: git.proposal.is_proposal_branch ? "ready" : git.current_branch === git.default_branch ? "approved" : "outside_flow",
      detail: git.current_branch || "no branch"
    },
    {
      label: "Publish",
      status: published ? "published" : git.proposal.is_proposal_branch ? "needs_publish" : "blocked",
      detail: git.upstream.name || git.upstream.remote || "no upstream"
    },
    {
      label: "Worktree",
      status: git.worktree.clean ? "clean" : "dirty",
      detail: `${git.worktree.changed_files.length} changed file(s)`
    },
    {
      label: "Machine gates",
      status: bundle.gates.status,
      detail: `${bundle.gates.gates.length} gate command(s)`
    },
    {
      label: "Draft PR",
      status: git.proposal.draft_pr_url ? "linked" : git.proposal.human_gate_state || "not_opened",
      detail: git.proposal.draft_pr_url || "not linked in snapshot"
    },
    {
      label: "Human review",
      status: git.proposal.human_gate_state,
      detail: "GitHub Pull Request gate"
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
          <span>Execute remote writes</span>
        </label>
      </div>
      <div className="gateTrack" aria-label="Pull Request human gate state">
        {steps.map((step) => (
          <article className={`gateStep gateStep-${gateStepTone(step.status)}`} key={step.label}>
            <strong>{step.label}</strong>
            <StatusPill tone={gateStepTone(step.status)}>{step.status}</StatusPill>
            <span>{step.detail}</span>
          </article>
        ))}
      </div>
      <div className="handoffGrid">
        <label className="field">
          <span>Review request title</span>
          <input value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>
        <button className="secondaryButton" onClick={resetGenerated} title="Regenerate the local PR handoff body from the current snapshot">
          <RefreshCw size={16} />
          <span>Regenerate</span>
        </button>
        <label className="field wide">
          <span>Decision notes for the Pull Request</span>
          <textarea className="handoffBody" value={body} onChange={(event) => setBody(event.target.value)} rows={13} />
        </label>
        {bundle.git.proposal.draft_pr_url && (
          <a className="secondaryButton wide" href={bundle.git.proposal.draft_pr_url} title="Open GitHub Pull Request">
            <ExternalLink size={16} />
            <span>Open PR</span>
          </a>
        )}
        <div className="buttonCluster wide">
          <button className="secondaryButton" onClick={() => onWorkflow("publish_proposal", {}, dryRun)} title="Push the current proposal branch">
            <RefreshCw size={16} />
            <span>Send Branch</span>
          </button>
          <button className="secondaryButton" onClick={() => onWorkflow("open_draft_pr", { title, body }, dryRun)} title="Create a draft GitHub Pull Request">
            <GitPullRequest size={16} />
            <span>Open Pull Request Draft</span>
          </button>
          <button className="secondaryButton" onClick={() => onWorkflow("update_draft_pr", { title, body }, dryRun)} title="Update the current branch Pull Request body">
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
  if (git.proposal.human_gate_state === "merged") return "merged PR";
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
        <h2>Approved Wiki Sync</h2>
        <StatusPill tone={syncTone(bundle)}>{syncStatus(bundle)}</StatusPill>
      </div>
      <div className="syncGrid">
        <dl className="kv">
          <dt>Approved branch</dt>
          <dd>{git.default_branch}</dd>
          <dt>Current branch</dt>
          <dd>{git.current_branch || "unknown"}</dd>
          <dt>Remote</dt>
          <dd>{git.upstream.remote || "origin"}</dd>
          <dt>Behind</dt>
          <dd>{git.upstream.behind}</dd>
          <dt>Worktree</dt>
          <dd>{git.worktree.clean ? "clean" : "changed"}</dd>
        </dl>
        <div className="syncCommand">
          <code>git fetch --prune {git.upstream.remote || "origin"}</code>
          <code>git pull --ff-only {git.upstream.remote || "origin"} {git.default_branch}</code>
        </div>
        <label className="toggleControl">
          <input type="checkbox" checked={execute} onChange={(event) => setExecute(event.target.checked)} disabled={!onDefaultBranch} />
          <span>Execute local pull</span>
        </label>
        <button
          className="secondaryButton wide"
          onClick={() => onWorkflow("sync_main", {}, dryRun)}
          disabled={!onDefaultBranch}
          title={onDefaultBranch ? "Fast-forward the approved local branch" : "Sync is available only from the approved branch"}
        >
          <RefreshCw size={16} />
          <span>Sync Main</span>
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
  const [message, setMessage] = useState("refine local cockpit git operations");
  const [prTitle, setPrTitle] = useState("Refine local cockpit Git operations");
  const [prBody, setPrBody] = useState("Local cockpit update with source triage and Git human-gate workflows.");
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
          <button className="secondaryButton" onClick={() => onWorkflow("list_proposals", {}, false)} title="List local proposal branches">
            <ListChecks size={16} />
            <span>List</span>
          </button>
          <button className="secondaryButton" onClick={() => onWorkflow("start_proposal", { theme }, dryRun)} title="Create proposal branch">
            <GitBranch size={16} />
            <span>Start proposal</span>
          </button>
        </div>
        <label className="field wide">
          <span>Content to include</span>
          <textarea value={paths} onChange={(event) => setPaths(event.target.value)} rows={4} />
        </label>
        <button className="secondaryButton wide" onClick={() => onWorkflow("stage_paths", { paths: splitPathInput(paths) }, dryRun)} title="Stage selected changed paths">
          <ListChecks size={16} />
          <span>Include selected content</span>
        </button>
        <label className="field">
          <span>Version note</span>
          <input value={message} onChange={(event) => setMessage(event.target.value)} />
        </label>
        <button className="secondaryButton" onClick={() => onWorkflow("commit_proposal", { message }, dryRun)} title="Commit proposal changes">
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
          <button className="secondaryButton" onClick={() => onWorkflow("publish_proposal", {}, dryRun)} title="Push proposal branch">
            <RefreshCw size={16} />
            <span>Send branch</span>
          </button>
          <button className="secondaryButton" onClick={() => onWorkflow("open_draft_pr", { title: prTitle, body: prBody }, dryRun)} title="Open draft pull request">
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
  const checks = reviewChecklist(bundle);
  const prAction = bundle.actions.actions.find((action) => action.id === "pr-summary");
  const decision = approvalDecision(bundle);
  return (
    <main className="workspace">
      <section className="panel reviewGate">
        <div className="panelHeader">
          <h1>Approval Desk</h1>
          <StatusPill tone={decision.tone}>{decision.label}</StatusPill>
        </div>
        <p className="decisionLead">{decision.detail}</p>
        <div className="gateGrid">
          <div>
            <h2>Decision Snapshot</h2>
            <dl className="kv">
              <dt>Workspace</dt>
              <dd>{bundle.git.current_branch || "detached/unknown"}</dd>
              <dt>Review request</dt>
              <dd>{bundle.git.proposal.draft_pr_url ? "linked" : bundle.git.proposal.human_gate_state}</dd>
              <dt>Remote state</dt>
              <dd>{bundle.git.upstream.name || bundle.git.upstream.remote || "not configured"} · ahead {bundle.git.upstream.ahead} / behind {bundle.git.upstream.behind}</dd>
              <dt>Local edits</dt>
              <dd>{bundle.git.worktree.clean ? "clean" : "changed"}</dd>
            </dl>
          </div>
          <div>
            <h2>Can I Approve?</h2>
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
      <ApprovalJourney bundle={bundle} />
      <DecisionPacket bundle={bundle} />
      <PrHandoffPanel bundle={bundle} onWorkflow={onWorkflow} />
      <DiffFilmstrip bundle={bundle} />
      <SyncMainPanel bundle={bundle} onWorkflow={onWorkflow} />
      <GitWorkflowPanel bundle={bundle} onWorkflow={onWorkflow} />
      <section className="panel">
        <div className="panelHeader">
          <h2>Exact Changed Content</h2>
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
          <h2>Automated Checks</h2>
          <StatusPill tone={gateStatusTone(bundle.gates.status)}>{bundle.gates.status}</StatusPill>
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
        <Stat icon={<ShieldCheck size={18} />} label="Checks" value={bundle.gates.gates.length} tone="info" />
        <Stat icon={<CircleAlert size={18} />} label="Quality flags" value={qualityFlags} tone={qualityFlags ? "warn" : "good"} />
        <Stat icon={<FileText size={18} />} label="Content" value={bundle.pages.pages.length} tone="info" />
        <Stat icon={<Search size={18} />} label="Evidence sources" value={bundle.sources.sources.length} tone="info" />
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
        <h3>Add Flow</h3>
        <StatusPill tone={plan.ok ? "good" : "bad"}>{plan.ok ? "ready" : "blocked"}</StatusPill>
      </div>
      <div className="pipelineRail" aria-label="Add knowledge flow">
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
              <small>{item.context} · {item.path}</small>
            </button>
          ))}
          {bundle.sources.sources.length === 0 && <p>No source pages in this snapshot.</p>}
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
            <span>Allow proposal writes</span>
          </label>
        </div>
        {result && (
          <div className="triageResult">
            <dl className="kv">
              <dt>Source key</dt>
              <dd>{result.source_id || "not available"}</dd>
              <dt>Content type</dt>
              <dd>{result.source_type || "unknown"}</dd>
              <dt>Found</dt>
              <dd>{String(result.exists)}</dd>
              <dt>Area</dt>
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
                  <h3>Target Content</h3>
                  <ul className="plainList compactList">
                    {result.targets.target_pages.map((page) => (
                      <li key={page}>{page}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h3>Known Entities</h3>
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
    <aside className="pageList" aria-label="Content">
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
              <dt>Page address</dt>
              <dd>{selected.path}</dd>
              <dt>Content kind</dt>
              <dd>{selected.page_type || "unknown"}</dd>
              <dt>Area</dt>
              <dd>{selected.context}</dd>
              <dt>Evidence refs</dt>
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
