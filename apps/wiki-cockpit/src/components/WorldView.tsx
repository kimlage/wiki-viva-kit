// WorldView: the 3D-first cockpit shell. The scene IS the navigation surface;
// everything else is a thin HUD fixed to the sceneShell edges — top strip
// (breadcrumbs + snapshot age + honest totals), left mission card, right
// PageReader dock, bottom command bar (search, perspective glyphs, packet
// tray, minimap hint). The old below-the-fold panel stack is gone: every ops
// action is reachable inside the viewport.

import { Activity, GitPullRequest, ListChecks, Play, Search, Trophy } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { t } from "../data/i18n";
import { contextLabel, isRawData, perspectiveLabel, worldGroupLabel } from "../data/presentation";
import { groupKeyForPage } from "../scene/perspectives";
import type { PerspectiveId } from "../scene/perspectives";
import { rankPages } from "../scene/search";
import { buildUrl, navigate, patchWorld, retreat } from "../router";
import type { WorldPatch, WorldRoute } from "../router";
import type { RuntimeConfig } from "../data/runtimeConfig";
import type { ActionCard, BriefSpec, CodexCapability, PageRecord, SnapshotBundle } from "../types";
import { CoachMarks, tourSeen } from "./CoachMarks";
import { HelpTip } from "./HelpTip";
import { MissionsPanel } from "./MissionsPanel";
import { PageReader } from "./PageReader";
import { WorkTray } from "./WorkTray";
import type { RelationGroupKey } from "./PageReader";
import { SystemScene } from "./SystemScene";
import type { ScenePatch } from "./SystemScene";

function findPage(pages: PageRecord[], key: string | undefined): PageRecord | undefined {
  if (!key) return undefined;
  return pages.find((page) => page.id === key || page.path === key);
}

const SEARCH_VISIBLE = 10;

function gateTone(status: string): "good" | "warn" | "bad" {
  const value = status.toLowerCase();
  if (["pass", "passed", "success", "ok"].includes(value)) return "good";
  if (["fail", "failed", "error", "blocked"].includes(value)) return "bad";
  return "warn";
}

const ACTION_TITLES: Record<string, string> = {
  "git-status": "Check work state",
  "review-local-changes": "Inspect changed content",
  "run-honesty-gates": "Verify approval readiness",
  "pr-summary": "Prepare approval summary",
  "graph-check": "Check related content"
};

function actionTitle(action: ActionCard): string {
  return ACTION_TITLES[action.id] || action.title;
}

function updatedLabel(value: string): string {
  if (!value) return t("misc.noDate");
  return value.replace("T", " ").replace("Z", "").slice(0, 16);
}

type MissionRow = {
  key: string;
  label: string;
  detail: string;
  help?: string;
  tone: "good" | "warn" | "bad";
  onClick: () => void;
};

export function WorldView({
  bundle,
  runtime,
  route,
  onRun,
  onNotice,
  onComposeBrief,
  onResumeBrief,
  onReturnJob,
  codexCapability
}: {
  bundle: SnapshotBundle;
  runtime: RuntimeConfig;
  route: WorldRoute;
  onRun: (action: ActionCard) => void;
  onNotice?: (text: string) => void;
  onComposeBrief?: (spec: BriefSpec) => void;
  onResumeBrief?: (briefId: string) => void;
  onReturnJob?: (jobId: string, feedback: string) => void;
  codexCapability?: CodexCapability;
}) {
  const pages = bundle.pages.pages;
  // Always navigate from the CURRENT route: async callbacks (debounce timers,
  // scene events) must never replay a stale route and revert navigation.
  const routeRef = useRef(route);
  routeRef.current = route;
  const [searchDraft, setSearchDraft] = useState(route.query.q);
  const [activeHit, setActiveHit] = useState(0);
  const [trayOpen, setTrayOpen] = useState(false);
  const [missionsOpen, setMissionsOpen] = useState(false);
  const [workOpen, setWorkOpen] = useState(false);
  const [tourOpen, setTourOpen] = useState(
    () =>
      typeof window !== "undefined" &&
      new URLSearchParams(window.location.search).get("visual") !== "1" &&
      !tourSeen()
  );
  const [isolateRelation, setIsolateRelation] = useState<RelationGroupKey | null>(null);
  const [hoverLinkId, setHoverLinkId] = useState<string | null>(null);
  const [walk, setWalk] = useState<{ ids: string[]; step: number } | null>(null);
  const [trailIds, setTrailIds] = useState<string[]>([]);
  const searchRef = useRef<HTMLInputElement>(null);

  // Canonical page navigation: selecting a page ALWAYS emits the full URL
  // (context › group › page), so the positional grammar stays unambiguous and
  // off-level selections auto-drill instead of silently no-oping.
  const canonicalPatch = (patch: WorldPatch): WorldPatch => {
    const current = routeRef.current;
    // A perspective switch while a page is locked re-derives the page's group
    // for the NEW perspective, so the positional URL never degenerates.
    if (patch.perspective && patch.pageId === undefined && current.pageId) {
      patch = { ...patch, pageId: current.pageId };
    }
    if (typeof patch.pageId !== "string") return patch;
    const page = findPage(pages, patch.pageId);
    if (!page) return patch;
    const perspective = patch.perspective ?? current.perspective;
    return {
      ...patch,
      pageId: page.id,
      context: page.context || "system",
      group: perspective === "trails" ? null : groupKeyForPage(perspective, page) ?? null
    };
  };
  const navigateWorld = (patch: WorldPatch, options: { replace?: boolean } = {}) =>
    navigate(patchWorld(routeRef.current, canonicalPatch(patch)), options);
  const makeHref = (patch: ScenePatch) => buildUrl(patchWorld(route, canonicalPatch(patch as WorldPatch)));

  const knownGroupKey = (segment: string): boolean => {
    if (route.perspective === "radar" || route.perspective === "districts") {
      return segment === "atencao" || pages.some((page) => (page.page_type || "content") === segment);
    }
    if (route.perspective === "atlas") {
      return (
        segment === "sem-pai" ||
        pages.some((page) => page.moc_parent && groupKeyForPage("atlas", page) === segment)
      );
    }
    return false;
  };

  // AUTO-DRILL + pin: any off-level selection (search result, wiki-link,
  // packet item, legacy alias, hand-typed URL) canonicalizes the URL to the
  // page's level — the silent no-op is banned.
  useEffect(() => {
    // A trailing segment that is actually a page id (typed/legacy URLs) is
    // re-read as the locked page, never dropped.
    if (!route.pageId && route.group && !knownGroupKey(route.group)) {
      const page = findPage(pages, route.group);
      if (page) {
        navigate(patchWorld(route, canonicalPatch({ pageId: page.id, reader: route.query.reader })), { replace: true });
        return;
      }
    }
    if (!route.pageId) return;
    const page = findPage(pages, route.pageId);
    if (!page) return;
    const context = page.context || "system";
    const group = route.perspective === "trails" ? undefined : groupKeyForPage(route.perspective, page);
    if (route.context !== context || (route.perspective !== "trails" && route.group !== group)) {
      navigate(patchWorld(route, { context, group: group ?? null }), { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pages, route]);

  // Selecting a page opens a new read: stale evidence-walk highlights and
  // relation isolation from the previous page never leak into this one.
  useEffect(() => {
    setWalk(null);
    setIsolateRelation(null);
    setHoverLinkId(null);
  }, [route.pageId, route.query.reader]);

  // A pageId that does not exist in THIS universe (demo id in the real world
  // or vice versa) is announced instead of silently ignored.
  const missingNoticeRef = useRef("");
  useEffect(() => {
    if (!route.pageId) {
      missingNoticeRef.current = "";
      return;
    }
    if (findPage(pages, route.pageId) || missingNoticeRef.current === route.pageId) return;
    missingNoticeRef.current = route.pageId;
    onNotice?.(t("world.missingInUniverse"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pages, route.pageId]);

  // Reading trail: last hops while moving between pages (jump-trail chips).
  useEffect(() => {
    if (!route.pageId) return;
    const page = findPage(pages, route.pageId);
    if (!page) return;
    setTrailIds((current) => {
      const next = current.filter((id) => id !== page.id);
      next.push(page.id);
      return next.slice(-5);
    });
  }, [pages, route.pageId]);

  // "?" reopens the guided tour from anywhere (outside typing contexts).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
      if (event.key === "?") setTourOpen(true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Search field mirrors ?q= (deep-linkable transient state).
  useEffect(() => {
    setSearchDraft(route.query.q);
  }, [route.query.q]);
  useEffect(() => {
    if (searchDraft === route.query.q) return undefined;
    const timer = window.setTimeout(() => navigateWorld({ q: searchDraft || null }, { replace: true }), 250);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchDraft]);

  const searchHits = useMemo(
    () => (route.query.q ? rankPages(pages, route.query.q) : []),
    [pages, route.query.q]
  );
  // Keyboard result navigation resets whenever the query changes.
  useEffect(() => setActiveHit(0), [route.query.q]);
  const visibleHits = searchHits.slice(0, SEARCH_VISIBLE);
  const openHit = (page?: PageRecord) => {
    if (page) navigateWorld({ pageId: page.id, reader: true });
  };
  const onSearchKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (!visibleHits.length) {
      if (event.key === "Escape") setSearchDraft("");
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveHit((index) => Math.min(index + 1, visibleHits.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveHit((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      openHit(visibleHits[activeHit] ?? visibleHits[0]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      setSearchDraft("");
    }
  };
  const packetPages = useMemo(
    () => route.query.packet.map((id) => findPage(pages, id)).filter((page): page is PageRecord => Boolean(page)),
    [pages, route.query.packet]
  );
  const highlightedIds = useMemo(() => {
    const ids = new Set<string>();
    searchHits.slice(0, 24).forEach((page) => {
      ids.add(page.id);
      ids.add(page.path);
    });
    packetPages.forEach((page) => {
      ids.add(page.id);
      ids.add(page.path);
    });
    if (hoverLinkId) ids.add(hoverLinkId);
    return [...ids];
  }, [hoverLinkId, packetPages, searchHits]);

  const togglePacket = (id: string) => {
    const page = findPage(pages, id);
    const keys = new Set([id, page?.id, page?.path].filter(Boolean) as string[]);
    const current = routeRef.current.query.packet;
    const isMember = current.some((item) => keys.has(item));
    const packet = isMember ? current.filter((item) => !keys.has(item)) : [...current, page?.id ?? id];
    navigateWorld({ packet }, { replace: true });
    onNotice?.(isMember ? t("toast.packetRemoved") : t("toast.packetAdded"));
  };

  const refreshAction =
    bundle.actions.actions.find((action) => action.id === "refresh-cockpit-check") ||
    bundle.actions.actions.find((action) => action.id === "graph-check");
  const gateAction = bundle.actions.actions.find((action) => action.id === "run-honesty-gates");
  const prAction = bundle.actions.actions.find((action) => action.id === "pr-summary");
  const reviewAction = bundle.actions.actions.find((action) => action.id === "review-local-changes");

  // Mission card: one intent state, one UI (replaces HeroGlass + MapIntentPanel).
  const stale = bundle.freshness.summary.stale ?? 0;
  const changed = bundle.git.worktree.changed_files.length;
  const missionRows: MissionRow[] = [];
  if (changed > 0) {
    missionRows.push({
      key: "review",
      label: t("mission.approve.label"),
      detail: t("mission.approve.detail", { n: changed }),
      help: t("mission.approve.help"),
      tone: "warn",
      onClick: () => navigate(route.demo ? "/demo/review" : "/review")
    });
  }
  if (gateTone(bundle.gates.status) !== "good" && gateAction) {
    missionRows.push({
      key: "checks",
      label: t("mission.checks.label"),
      detail: t("mission.checks.detail"),
      help: t("mission.checks.help"),
      tone: gateTone(bundle.gates.status),
      onClick: () => onRun(gateAction)
    });
  }
  if (stale > 0) {
    missionRows.push({
      key: "stale",
      label: t("mission.stale.label"),
      detail: t("mission.stale.detail", { n: stale }),
      help: t("mission.stale.help"),
      tone: "warn",
      onClick: () => navigateWorld({ perspective: "radar", filter: "stale" })
    });
  }
  if (missionRows.length === 0) {
    missionRows.push({
      key: "browse",
      label: t("mission.clear.label"),
      detail: t("mission.clear.detail"),
      tone: "good",
      onClick: () => navigateWorld({ perspective: "atlas", context: null, group: null })
    });
  }

  const selectedPage = findPage(pages, route.pageId);
  const readerOpen = Boolean(route.pageId && route.query.reader && selectedPage);
  const trailPages = trailIds.map((id) => findPage(pages, id)).filter((page): page is PageRecord => Boolean(page));

  // Breadcrumbs: URL-derived, every segment clickable, registry labels.
  const crumbs: { label: string; patch: WorldPatch }[] = [
    { label: t("world.galaxy"), patch: { context: null, group: null, pageId: null, reader: false } }
  ];
  if (route.context) crumbs.push({ label: contextLabel(route.context), patch: { group: null, pageId: null, reader: false } });
  if (route.group && route.perspective !== "trails") {
    const groupKind = route.perspective === "districts" ? "page_type" : route.perspective === "atlas" ? "hub" : "attention";
    crumbs.push({ label: worldGroupLabel(groupKind, route.group), patch: { pageId: null, reader: false } });
  }
  if (selectedPage) crumbs.push({ label: selectedPage.title, patch: {} });

  const sceneRoute = {
    perspective: route.perspective,
    context: route.context,
    group: route.group,
    pageId: route.pageId,
    reader: route.query.reader,
    filter: route.query.filter
  };

  return (
    <main className="worldWorkspace" aria-label={t("world.aria")}>
      <SystemScene
        nodes={bundle.graph.nodes}
        edges={bundle.graph.edges}
        git={bundle.git}
        route={sceneRoute}
        packetIds={route.query.packet}
        highlightedPageIds={highlightedIds}
        isolateRelation={isolateRelation}
        walk={walk}
        snapshotAt={bundle.manifest.generated_at}
        activityLevel={bundle.timeline.bands.last_7_days || 0}
        onNavigate={(patch) => navigateWorld(patch as WorldPatch)}
        onRetreat={() => navigate(retreat(route))}
        onFocusSearch={() => searchRef.current?.focus()}
        onTogglePacket={togglePacket}
        onRunRefresh={() => refreshAction && onRun(refreshAction)}
        makeHref={makeHref}
      >
        {/* TOP strip: breadcrumb trail + snapshot age + mode + true total. */}
        <div className="worldTopStrip" aria-label={t("world.breadcrumbsAria")}>
          <nav className="worldBreadcrumbs" aria-label={t("world.breadcrumbsAria")}>
            {crumbs.map((crumb, index) => (
              <span key={`${crumb.label}-${index}`}>
                {index > 0 && <i aria-hidden>›</i>}
                {index === crumbs.length - 1 ? (
                  <strong>{crumb.label}</strong>
                ) : (
                  <button className="crumbButton" onClick={() => navigateWorld(crumb.patch)} type="button">
                    {crumb.label}
                  </button>
                )}
              </span>
            ))}
          </nav>
          <div className="worldMeta">
            <span>{t("world.pages", { n: pages.length })}</span>
            <span>{t("world.updated", { when: updatedLabel(bundle.manifest.generated_at) })}</span>
            <span>{route.demo ? t("world.demoMode") : runtime.mode || bundle.manifest.mode}</span>
          </div>
        </div>

        {/* LEFT mission card: current intent with do-now rows. */}
        <div className="worldMissionCard" role="region" aria-label={t("world.missionAria")}>
          <header>
            <strong>{perspectiveLabel(route.perspective).label}</strong>
            <span>{perspectiveLabel(route.perspective).hint}</span>
          </header>
          <div className="missionRows">
            {missionRows.slice(0, 3).map((row, index) => (
              <div className={`missionRow tone-${row.tone}`} key={row.key}>
                <button className="missionRowMain" onClick={row.onClick} type="button">
                  <span className="stageIndex">{index + 1}</span>
                  <span className="missionCopy">
                    <strong>{row.label}</strong>
                    <small>{row.detail}</small>
                  </span>
                </button>
                {row.help && <HelpTip title={row.label} body={row.help} />}
              </div>
            ))}
          </div>
          {route.query.q && (
            <div className="missionSearchResults" aria-label={t("world.results", { n: searchHits.length })}>
              <span className="missionSearchCount">
                {searchHits.length > SEARCH_VISIBLE
                  ? t("world.resultsCapped", { n: searchHits.length, shown: SEARCH_VISIBLE })
                  : t("world.results", { n: searchHits.length })}
              </span>
              {visibleHits.map((page, index) => (
                <button
                  className={index === activeHit ? "textButton searchHitActive" : "textButton"}
                  key={page.id}
                  onMouseEnter={() => setActiveHit(index)}
                  onClick={() => openHit(page)}
                  title={page.path}
                  type="button"
                >
                  {page.title}
                  <small>
                    {" "}
                    · {contextLabel(page.context || "system")}
                    {isRawData(page.page_type) ? <em className="rawTag"> {t("world.raw")}</em> : null}
                    {page.summary_truncated ? ` · ${t("world.partialSummary")}` : ""}
                  </small>
                </button>
              ))}
              {searchHits.length === 0 && <span className="missionSearchCount">{t("world.noResults")}</span>}
            </div>
          )}
        </div>

        {/* RIGHT: the in-world reader dock. */}
        {readerOpen && selectedPage && (
          <PageReader
            bundle={bundle}
            pageId={selectedPage.id}
            demo={route.demo}
            snapshotSource={runtime.snapshotBase}
            devMode={(runtime.mode || bundle.manifest.mode) === "local_operator" && !route.demo}
            trail={trailPages}
            packetIds={route.query.packet}
            onNavigatePage={(id) => navigateWorld({ pageId: id, reader: true })}
            onClose={() => navigateWorld({ reader: false })}
            onTogglePacket={togglePacket}
            onRunAction={onRun}
            onComposeBrief={onComposeBrief}
            onHoverLink={setHoverLinkId}
            onIsolateRelation={setIsolateRelation}
            onEvidenceStep={(ids, step) => setWalk({ ids, step })}
          />
        )}

        {/* BOTTOM command bar: search, perspective glyphs, packet tray. */}
        <div className="worldCommandBar" role="toolbar" aria-label={t("world.commandBarAria")}>
          <label className="commandSearch">
            <Search size={14} aria-hidden />
            <input
              ref={searchRef}
              value={searchDraft}
              onChange={(event) => setSearchDraft(event.target.value)}
              onKeyDown={onSearchKeyDown}
              placeholder={t("world.searchPlaceholder")}
              aria-label={t("world.searchAria")}
            />
          </label>
          <div className="perspectiveGlyphs" role="group" aria-label={t("world.perspectives")}>
            {(["radar", "atlas", "districts", "trails"] as PerspectiveId[]).map((perspective, index) => {
              const info = perspectiveLabel(perspective);
              return (
                <button
                  key={perspective}
                  className={route.perspective === perspective ? "glyphButton active" : "glyphButton"}
                  onClick={() => navigateWorld({ perspective })}
                  title={`${info.label} (${index + 1}) — ${info.hint}`}
                  aria-pressed={route.perspective === perspective}
                  type="button"
                >
                  <span aria-hidden>{info.glyph}</span>
                  <small>{info.label}</small>
                </button>
              );
            })}
          </div>
          <button
            className={trayOpen ? "trayButton active" : "trayButton"}
            onClick={() => {
              setTrayOpen((value) => !value);
              setMissionsOpen(false);
              setWorkOpen(false);
            }}
            type="button"
            aria-expanded={trayOpen}
          >
            <ListChecks size={14} />
            <span>{t("world.packet", { n: route.query.packet.length })}</span>
          </button>
          <HelpTip term="packet" />
          <button
            className={missionsOpen ? "trayButton missionsButton active" : "trayButton missionsButton"}
            onClick={() => {
              setMissionsOpen((value) => !value);
              setTrayOpen(false);
              setWorkOpen(false);
            }}
            type="button"
            aria-expanded={missionsOpen}
          >
            <Trophy size={14} />
            <span>{t("world.missions")}</span>
          </button>
          {onComposeBrief && (
            <button
              className={workOpen ? "trayButton workButton active" : "trayButton workButton"}
              onClick={() => {
                setWorkOpen((value) => !value);
                setTrayOpen(false);
                setMissionsOpen(false);
              }}
              type="button"
              aria-expanded={workOpen}
            >
              <Activity size={14} />
              <span>{t("work.title")}</span>
            </button>
          )}
          <button className="trayButton tourButton" onClick={() => setTourOpen(true)} type="button">
            <span aria-hidden>?</span>
            <span className="visuallyHidden">{t("tour.reopen")}</span>
          </button>
          <span className="commandHint" aria-hidden>
            {t("world.hintKeys")}
          </span>
        </div>

        {/* Decision-packet slide-up tray (replaces ImpactBundlePanel). */}
        {trayOpen && (
          <div className="packetTray" role="region" aria-label={t("world.packet", { n: packetPages.length })}>
            <header>
              <strong>{t("world.packet", { n: packetPages.length })}</strong>
              <HelpTip term="packet" />
              <button className="textButton" onClick={() => navigateWorld({ packet: [] }, { replace: true })} disabled={packetPages.length === 0} type="button">
                {t("misc.clear")}
              </button>
              <button className="readerClose" onClick={() => setTrayOpen(false)} title="Fechar" type="button">
                ×
              </button>
            </header>
            <div className="packetRows">
              {packetPages.map((page) => (
                <div className="packetRow" key={page.id}>
                  <button className="textButton" onClick={() => navigateWorld({ pageId: page.id, reader: true })} title={page.path} type="button">
                    {page.title}
                  </button>
                  <small>
                    {contextLabel(page.context || "system")}
                    {isRawData(page.page_type) ? ` · ${t("world.raw")}` : ""}
                    {page.summary_truncated ? ` · ${t("world.partialSummary")}` : ""}
                  </small>
                  <button className="textButton" onClick={() => togglePacket(page.id)} type="button">
                    {t("misc.remove")}
                  </button>
                </div>
              ))}
              {packetPages.length === 0 && <p>{t("misc.packetEmpty")}</p>}
            </div>
            <div className="packetActions">
              {reviewAction && (
                <button className="secondaryButton" onClick={() => onRun(reviewAction)} type="button">
                  <Play size={14} />
                  <span>{actionTitle(reviewAction)}</span>
                </button>
              )}
              {gateAction && (
                <button className="secondaryButton" onClick={() => onRun(gateAction)} type="button">
                  <Play size={14} />
                  <span>{actionTitle(gateAction)}</span>
                </button>
              )}
              {prAction && (
                <button className="secondaryButton" onClick={() => onRun(prAction)} type="button">
                  <GitPullRequest size={14} />
                  <span>{actionTitle(prAction)}</span>
                </button>
              )}
            </div>
          </div>
        )}
        {missionsOpen && (
          <MissionsPanel
            bundle={bundle}
            demo={route.demo}
            onOpenPage={(id) => {
              setMissionsOpen(false);
              navigateWorld({ pageId: id, reader: true });
            }}
            onComposeBrief={
              onComposeBrief
                ? (spec) => {
                    setMissionsOpen(false);
                    onComposeBrief(spec);
                  }
                : undefined
            }
            onClose={() => setMissionsOpen(false)}
          />
        )}
        {workOpen && onComposeBrief && (
          <WorkTray
            capability={codexCapability ?? { enabled: true, installed: false, runnable: false, authed: false, auth_mode: null, version: null, usable: false, reason: "" }}
            demo={route.demo}
            onResumeBrief={(id) => {
              setWorkOpen(false);
              onResumeBrief?.(id);
            }}
            onReturn={
              onReturnJob
                ? (jobId, feedback) => {
                    setWorkOpen(false);
                    onReturnJob(jobId, feedback);
                  }
                : undefined
            }
            onNotice={(text) => onNotice?.(text)}
            onClose={() => setWorkOpen(false)}
          />
        )}
      </SystemScene>
      <CoachMarks open={tourOpen} onClose={() => setTourOpen(false)} />
    </main>
  );
}
