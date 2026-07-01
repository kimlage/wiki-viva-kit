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
  ListChecks,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  TerminalSquare
} from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { SystemScene } from "./components/SystemScene";
import { gitGateLabel, pageById, qualityFlagCount, reviewChecklist, topActions } from "./data/model";
import { loadSnapshotBundle, runCockpitAction } from "./data/snapshot";
import type { ActionCard, ActionRunResult, PageRecord, SnapshotBundle } from "./types";
import "./styles.css";

type LoadState =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "ready"; bundle: SnapshotBundle; source: string };

function routeView(): { view: "ops" | "review" | "health" | "pages"; pageId?: string } {
  const path = window.location.pathname;
  if (path.startsWith("/review")) return { view: "review" };
  if (path.startsWith("/health")) return { view: "health" };
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
    { href: "/health", label: "Health", icon: <ShieldCheck size={17} /> },
    { href: "/pages", label: "Pages", icon: <FileText size={17} /> }
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

function CommandOutput({ result }: { result: ActionRunResult | null }) {
  if (!result) return null;
  return (
    <section className="panel outputPanel">
      <div className="panelHeader">
        <h2>Command Log</h2>
        <StatusPill tone={result.ok ? "good" : "bad"}>{result.ok ? "passed" : "failed"}</StatusPill>
      </div>
      {result.results.map((entry, index) => (
        <details open={index === 0} key={`${entry.argv.join(" ")}-${index}`}>
          <summary>
            <TerminalSquare size={16} />
            <span>{entry.argv.join(" ")}</span>
          </summary>
          <pre>{[entry.stdout, entry.stderr].filter(Boolean).join("\n") || "No output."}</pre>
        </details>
      ))}
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

function ReviewView({ bundle, onRun }: { bundle: SnapshotBundle; onRun: (action: ActionCard) => void }) {
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
  const [commandResult, setCommandResult] = useState<ActionRunResult | null>(null);

  useEffect(() => {
    loadSnapshotBundle()
      .then(({ bundle, source }) => setLoadState({ status: "ready", bundle, source }))
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

  const content = useMemo(() => {
    if (loadState.status === "loading") return <main className="workspace"><section className="panel"><h1>Loading cockpit</h1></section></main>;
    if (loadState.status === "error") return <main className="workspace"><section className="panel"><h1>Snapshot unavailable</h1><p>{loadState.error}</p></section></main>;
    const { bundle } = loadState;
    if (route.view === "review") return <ReviewView bundle={bundle} onRun={runAction} />;
    if (route.view === "health") return <HealthView bundle={bundle} />;
    if (route.view === "pages") return <PagesView bundle={bundle} pageId={route.pageId} />;
    return <OpsView bundle={bundle} onRun={runAction} />;
  }, [loadState, route]);

  return (
    <div className="appShell">
      <Nav active={active} />
      <div className="mainColumn">
        <header className="topBar">
          <div>
            <strong>Wiki Viva Cockpit</strong>
            {loadState.status === "ready" && <span>{loadState.bundle.manifest.repo.repo_id} · {loadState.source}</span>}
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
