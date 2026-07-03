// WorldView: the 3D-first cockpit shell. The scene IS the navigation surface;
// everything else is a thin HUD fixed to the sceneShell edges — top strip
// (breadcrumbs + snapshot age + honest totals), left mission card, right
// PageReader dock, bottom command bar (search, perspective glyphs, packet
// tray, minimap hint). The old below-the-fold panel stack is gone: every ops
// action is reachable inside the viewport.

import {
  Activity,
  Database,
  GitPullRequest,
  Inbox,
  ListChecks,
  Play,
  Search,
  ShieldCheck,
  Sparkles,
  Sprout,
  Trophy
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { t } from "../data/i18n";
import { contextLabel, isRawData, perspectiveLabel, worldGroupLabel } from "../data/presentation";
import { groupKeyForPage } from "../scene/perspectives";
import type { PerspectiveId } from "../scene/perspectives";
import { SCENE_FACETS, homeQuadrant, sceneFacetOf } from "../scene/facets";
import type { SceneFacet } from "../scene/facets";
import { computeCondition } from "../scene/condition";
import { rankPages } from "../scene/search";
import { buildUrl, navigate, patchWorld, retreat } from "../router";
import type { WorldPatch, WorldRoute } from "../router";
import type { RuntimeConfig } from "../data/runtimeConfig";
import type { ActionCard, BriefSpec, PageRecord, SnapshotBundle } from "../types";
import { CoachMarks, tourSeen } from "./CoachMarks";
import { HelpTip } from "./HelpTip";
import { MissionsPanel } from "./MissionsPanel";
import { PageReader } from "./PageReader";
import type { RelationGroupKey } from "./PageReader";
import { SystemScene } from "./SystemScene";
import type { ScenePatch } from "./SystemScene";

// Ego-centric perspectives lock one page at the center and have no group slot
// in the positional URL: Trails (relations) and Focus (facet lenses).
function isEgoPerspective(perspective: string): boolean {
  return perspective === "trails" || perspective === "focus";
}

// Brief to fill an empty lens: ask the agent to add a real relation of that
// kind IF one exists in the corpus — never to invent one (the honesty rule).
function focusFillSpec(page: PageRecord, facet: SceneFacet, facetLabel: string): BriefSpec {
  return {
    mission_kind: "verify",
    theme: `facet-${facet}`,
    grounding: { page_ids: [page.id], attach_context_package: true },
    intent:
      `The page "${page.title}" (${page.path}) has no "${facetLabel}" lens — no neighbor of that kind.\n` +
      `Read the page and its context package. If a real ${facetLabel.toLowerCase()} relation exists ` +
      `(a decision, perception/insight, practice/action, or person/meeting as appropriate) that is not yet ` +
      `linked, add the link in the page body. If none exists, report that honestly and add nothing — never invent a relation.`
  };
}

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
  // Optional secondary action (e.g. "resolve with Codex") rendered as a button
  // beside the row's main click target.
  action?: { label: string; title?: string; onClick: () => void };
};

// Brief to refresh stale content: the stale pages become the grounding, so the
// agent re-reads their sources and proposes an update — never invents freshness.
function staleRefreshSpec(pages: PageRecord[]): BriefSpec {
  const targets = pages.slice(0, 40);
  const list = targets.map((page) => `- ${page.title} (${page.path})`).join("\n");
  const more = pages.length > targets.length ? `\n…and ${pages.length - targets.length} more.` : "";
  return {
    mission_kind: "verify",
    theme: "refresh-stale",
    grounding: { page_ids: targets.map((page) => page.id), attach_context_package: true },
    intent:
      `${pages.length} page(s) are past their freshness window and need review.\n\n` +
      `For each, re-read its source(s) and evidence, then update the page ONLY where the ` +
      `underlying source actually changed (bump updated_at, refresh the facts/links). If a ` +
      `source itself is stale, note it. Never fabricate freshness — if nothing changed, say so ` +
      `and just re-confirm.\n\nPages:\n${list}${more}`
  };
}

// The mission card is collapsible — a map you can actually SEE beats a panel
// you did not ask for. The preference is remembered per browser (UI state,
// not world state: it stays out of the URL on purpose).
const MISSION_CARD_KEY = "wiki-cockpit.missionCard";
function missionCardPref(): boolean {
  try {
    return window.localStorage.getItem(MISSION_CARD_KEY) !== "closed";
  } catch {
    return true;
  }
}
function persistMissionCard(open: boolean): void {
  try {
    window.localStorage.setItem(MISSION_CARD_KEY, open ? "open" : "closed");
  } catch {
    /* private mode — session-only */
  }
}

export function WorldView({
  bundle,
  runtime,
  route,
  onRun,
  onNotice,
  onComposeBrief
}: {
  bundle: SnapshotBundle;
  runtime: RuntimeConfig;
  route: WorldRoute;
  onRun: (action: ActionCard) => void;
  onNotice?: (text: string) => void;
  onComposeBrief?: (spec: BriefSpec) => void;
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
  const [missionCardOpen, setMissionCardOpen] = useState(missionCardPref);
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
      group: isEgoPerspective(perspective) ? null : groupKeyForPage(perspective, page) ?? null
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
    const group = isEgoPerspective(route.perspective) ? undefined : groupKeyForPage(route.perspective, page);
    if (route.context !== context || (!isEgoPerspective(route.perspective) && route.group !== group)) {
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

  // Purple gate halos: while the Gate dock is open, the content pages that the
  // human is about to approve glow in the world. The scene stops being a
  // backdrop to the dock and starts pointing at exactly what is under review.
  // Matches on node.path (diff paths are repo-relative, like node.path).
  const approvalPageIds = useMemo(() => {
    if (route.query.dock !== "approve") return [];
    return (bundle.diff.files ?? [])
      .filter((file) => file.category === "memory")
      .map((file) => file.path);
  }, [bundle.diff.files, route.query.dock]);

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
  if (gateTone(bundle.gates.status) !== "good") {
    // Honest per-gate status right in the radar; clicking opens the Checks dock
    // (per-gate Run + output + fix) instead of firing a blind multi-command
    // action that surfaced only as a cryptic 400.
    const gates = bundle.gates?.gates ?? [];
    const passing = gates.filter((g) => g.status === "pass").length;
    const failing = gates.filter((g) => g.status === "fail").map((g) => g.id);
    const anyRun = gates.some((g) => g.status !== "not_run");
    missionRows.push({
      key: "checks",
      label: t("mission.checks.label"),
      detail: anyRun
        ? t("mission.checks.detailStatus", { pass: passing, total: gates.length, failing: failing.length })
        : gates.length
          ? t("mission.checks.detailNotRun", { total: gates.length })
          : t("mission.checks.detail"),
      help: t("mission.checks.help"),
      tone: gateTone(bundle.gates.status),
      onClick: () => navigateWorld({ dock: "gates" })
    });
  }
  if (stale > 0) {
    const stalePages = pages.filter((page) => page.freshness_state === "stale");
    missionRows.push({
      key: "stale",
      label: t("mission.stale.label"),
      detail: t("mission.stale.detail", { n: stale }),
      help: t("mission.stale.help"),
      tone: "warn",
      onClick: () => navigateWorld({ perspective: "radar", filter: "stale" }),
      action:
        onComposeBrief && stalePages.length > 0
          ? {
              label: t("mission.stale.fix"),
              title: t("mission.stale.fixTitle"),
              onClick: () => onComposeBrief(staleRefreshSpec(stalePages))
            }
          : undefined
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

  // Focus legend: the four lenses with live 1-hop counts, computed from the
  // same facet bucketing the scene uses. An empty lens is shown as an honest
  // absence with an offer to fill it — never hidden.
  const focusFacets = useMemo(() => {
    if (route.perspective !== "focus" || !selectedPage) return null;
    const counts = new Map<SceneFacet, number>(SCENE_FACETS.map((facet) => [facet, 0]));
    const byKey = new Map<string, (typeof bundle.graph.nodes)[number]>();
    bundle.graph.nodes.forEach((node) => {
      byKey.set(node.id, node);
      byKey.set(node.path, node);
    });
    const centerId = selectedPage.id;
    const seen = new Set<string>([centerId]);
    bundle.graph.edges.forEach((edge) => {
      const src = byKey.get(edge.source);
      const tgt = byKey.get(edge.target);
      if (!src || !tgt) return;
      const neighbor = src.id === centerId ? tgt : tgt.id === centerId ? src : null;
      if (!neighbor || seen.has(neighbor.id)) return;
      seen.add(neighbor.id);
      const facet = sceneFacetOf(neighbor.page_type, edge.type);
      if (facet) counts.set(facet, (counts.get(facet) ?? 0) + 1);
    });
    return SCENE_FACETS.map((facet) => ({ facet, count: counts.get(facet) ?? 0 }));
  }, [route.perspective, selectedPage, bundle.graph]);

  // Quadrant compass: live per-quadrant home counts (+ the honest core) for the
  // Quadrants perspective — the 2×2 grid you fly by. Computed from the same
  // homeQuadrant the layout uses, so it never overstates.
  const quadrantCounts = useMemo(() => {
    if (route.perspective !== "quadrants") return null;
    const counts = new Map<SceneFacet, number>(SCENE_FACETS.map((facet) => [facet, 0]));
    let core = 0;
    bundle.graph.nodes.forEach((node) => {
      const home = homeQuadrant(node.page_type);
      if (home) counts.set(home, (counts.get(home) ?? 0) + 1);
      else core += 1;
    });
    return { quadrants: SCENE_FACETS.map((facet) => ({ facet, count: counts.get(facet) ?? 0 })), core };
  }, [route.perspective, bundle.graph]);

  // The world's condition — the honest ambient readout (weather is set from it in
  // the scene). Every segment is a real count that flies to the act point.
  const condition = useMemo(() => computeCondition(bundle), [bundle]);

  // Breadcrumbs: URL-derived, every segment clickable, registry labels.
  const crumbs: { label: string; patch: WorldPatch }[] = [
    { label: t("world.galaxy"), patch: { context: null, group: null, pageId: null, reader: false } }
  ];
  if (route.context) crumbs.push({ label: contextLabel(route.context), patch: { group: null, pageId: null, reader: false } });
  if (route.group && !isEgoPerspective(route.perspective)) {
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
    filter: route.query.filter,
    quadrant: route.query.quadrant
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
        approvalPageIds={approvalPageIds}
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
          {/* Condition strip: the honest ambient readout — every segment a real
              count that flies to its act point. Numbers-beside-art: the scene
              weather is only allowed because these exact counts are printed. */}
          <div className={`conditionStrip weather-${condition.weather}`} role="group" aria-label={t("condition.aria")}>
            <span className="conditionWeather" title={t(`condition.weather.${condition.weather}`)}>
              {t(`condition.weather.${condition.weather}`)}
            </span>
            {condition.staleCount > 0 && (
              <button className="conditionSeg warn" onClick={() => navigateWorld({ perspective: "radar", filter: "stale" })} type="button">
                {t("condition.stale", { n: condition.staleCount })}
              </button>
            )}
            {condition.gatesFailing.length > 0 && (
              <button className="conditionSeg bad" onClick={() => navigateWorld({ dock: "gates" })} type="button">
                {t("condition.gates", { n: condition.gatesFailing.length })}
              </button>
            )}
            {condition.pendingApproval > 0 && (
              <button className="conditionSeg warn" onClick={() => navigateWorld({ dock: "approve" })} type="button">
                {t("condition.approve", { n: condition.pendingApproval })}
              </button>
            )}
            {condition.pendingSourceIntake > 0 && (
              <button className="conditionSeg" onClick={() => navigateWorld({ dock: "source" })} type="button">
                {t("condition.sources", { n: condition.pendingSourceIntake })}
              </button>
            )}
          </div>
          <div className="worldMeta">
            <span>{t("world.pages", { n: pages.length })}</span>
            <span>{t("world.updated", { when: updatedLabel(bundle.manifest.generated_at) })}</span>
            <span>{route.demo ? t("world.demoMode") : runtime.mode || bundle.manifest.mode}</span>
          </div>
        </div>

        {/* FOCUS legend: the four lenses with live counts. An empty lens is an
            honest absence — labelled "no X lens registered" with an offer to
            fill it (agent adds a real relation only if one exists). */}
        {focusFacets && selectedPage && (
          <div className="focusLegend" role="region" aria-label={t("focus.legend")}>
            <span className="focusLegendTitle">{t("focus.legend")}</span>
            {focusFacets.map(({ facet, count }) => {
              const label = t(`facet.${facet}`);
              return (
                <div key={facet} className={count === 0 ? "focusLens empty" : "focusLens"}>
                  <strong>{label}</strong>
                  {count === 0 ? (
                    onComposeBrief ? (
                      <button
                        className="textButton focusFillButton"
                        onClick={() => onComposeBrief(focusFillSpec(selectedPage, facet, label))}
                        title={t("focus.emptyFacetFill", { facet: label })}
                        type="button"
                      >
                        {t("focus.emptyFacet", { facet: label })}
                      </button>
                    ) : (
                      <small className="focusLensEmpty">{t("focus.emptyFacet", { facet: label })}</small>
                    )
                  ) : (
                    <small>{count}</small>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* QUADRANT compass: the 2×2 AQAL grid you fly by. Each cell flies the
            camera to that quadrant region (?quadrant=<facet>); the active one is
            highlighted. Counts are honest home-quadrant totals + the core. */}
        {quadrantCounts && (
          <div className="quadrantCompass" role="group" aria-label={t("world.quadrantCompassAria")}>
            <div className="quadrantGrid">
              {quadrantCounts.quadrants.map(({ facet, count }) => (
                <button
                  key={facet}
                  className={route.query.quadrant === facet ? "quadrantCell active" : "quadrantCell"}
                  onClick={() =>
                    navigateWorld({ quadrant: route.query.quadrant === facet ? null : facet })
                  }
                  title={t(`facet.${facet}`)}
                  type="button"
                >
                  <strong>{t(`facet.${facet}`)}</strong>
                  <small>{count}</small>
                </button>
              ))}
            </div>
            {quadrantCounts.core > 0 && (
              <span className="quadrantCore">{t("quadrant.core")} · {quadrantCounts.core}</span>
            )}
            <button
              className="quadrantSeed"
              onClick={() => navigateWorld({ dock: "create", quadrant: route.query.quadrant || null })}
              title={t("create.title")}
              type="button"
            >
              ＋ {t("create.seedHere")}
            </button>
          </div>
        )}

        {/* LEFT mission surface. Collapsed by choice it is a single honest
            chip (worst tone + pending count) — the world stays visible;
            expanded it is the do-now card. Search results always render:
            the keyboard search flow must never depend on the card state. */}
        {(() => {
          const actionable = missionRows.filter((row) => row.key !== "browse");
          const worstTone = actionable.some((row) => row.tone === "bad")
            ? "bad"
            : actionable.some((row) => row.tone === "warn")
              ? "warn"
              : "good";
          const toggleCard = () => {
            setMissionCardOpen((open) => {
              persistMissionCard(!open);
              return !open;
            });
          };
          const searchBlock = route.query.q ? (
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
          ) : null;
          if (!missionCardOpen) {
            return (
              <div className="worldMissionSlim" role="region" aria-label={t("world.missionAria")}>
                <button
                  className={`worldMissionChip tone-${worstTone}`}
                  onClick={toggleCard}
                  aria-expanded={false}
                  title={perspectiveLabel(route.perspective).hint}
                  type="button"
                >
                  <i aria-hidden />
                  <strong>{perspectiveLabel(route.perspective).label}</strong>
                  <span>
                    {actionable.length > 0 ? t("world.missionCount", { n: actionable.length }) : t("world.missionClear")}
                  </span>
                </button>
                {searchBlock && <div className="worldMissionCard searchOnly">{searchBlock}</div>}
              </div>
            );
          }
          return (
            <div className="worldMissionCard" role="region" aria-label={t("world.missionAria")}>
              <header>
                <strong>{perspectiveLabel(route.perspective).label}</strong>
                <span>{perspectiveLabel(route.perspective).hint}</span>
                <button className="readerClose missionCollapse" onClick={toggleCard} title={t("world.missionCollapse")} type="button">
                  –
                </button>
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
                    {row.action && (
                      <button className="missionRowAction" onClick={row.action.onClick} title={row.action.title} type="button">
                        <Sparkles size={13} />
                        <span>{row.action.label}</span>
                      </button>
                    )}
                    {row.help && <HelpTip title={row.label} body={row.help} />}
                  </div>
                ))}
              </div>
              {searchBlock}
            </div>
          );
        })()}

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
          {/* Destinations — the old left rail, dissolved into the world. Each
              opens its dock in place (deep-linkable ?dock=…). Content = the
              Atlas perspective; Home = Radar (both live in the glyphs). */}
          <div className="commandDocks" role="group" aria-label={t("world.destinationsAria")}>
            {([
              { dock: "approve", label: t("nav.approve"), icon: <GitPullRequest size={15} /> },
              { dock: "intake", label: t("nav.add"), icon: <Inbox size={15} /> },
              { dock: "create", label: t("nav.create"), icon: <Sprout size={15} /> },
              { dock: "source", label: t("nav.sources"), icon: <Database size={15} /> },
              { dock: "gates", label: t("nav.health"), icon: <ShieldCheck size={15} /> }
            ] as const).map((item) => (
              <button
                key={item.dock}
                className={route.query.dock === item.dock ? "dockButton active" : "dockButton"}
                onClick={() => {
                  setTrayOpen(false);
                  setMissionsOpen(false);
                  navigateWorld({ dock: route.query.dock === item.dock ? null : item.dock });
                }}
                title={item.label}
                aria-pressed={route.query.dock === item.dock}
                type="button"
              >
                {item.icon}
                <small>{item.label}</small>
              </button>
            ))}
          </div>
          <div className="perspectiveGlyphs" role="group" aria-label={t("world.perspectives")}>
            {(["radar", "atlas", "districts", "trails", "quadrants"] as PerspectiveId[]).map((perspective, index) => {
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
            {/* Focus is page-triggered — enabled only with a page locked, so it
                never claims to show lenses over nothing. */}
            {(() => {
              const info = perspectiveLabel("focus");
              const enabled = Boolean(route.pageId);
              return (
                <button
                  key="focus"
                  className={route.perspective === "focus" ? "glyphButton active" : "glyphButton"}
                  onClick={() => enabled && navigateWorld({ perspective: "focus" })}
                  disabled={!enabled}
                  title={enabled ? `${info.label} (F) — ${info.hint}` : t("perspective.focus.needsPage")}
                  aria-pressed={route.perspective === "focus"}
                  type="button"
                >
                  <span aria-hidden>{info.glyph}</span>
                  <small>{info.label}</small>
                </button>
              );
            })()}
          </div>
          <button
            className={trayOpen ? "trayButton active" : "trayButton"}
            onClick={() => {
              setTrayOpen((value) => !value);
              setMissionsOpen(false);
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
            }}
            type="button"
            aria-expanded={missionsOpen}
          >
            <Trophy size={14} />
            <span>{t("world.missions")}</span>
          </button>
          {onComposeBrief && (
            <button
              className={route.query.dock === "work" ? "trayButton workButton active" : "trayButton workButton"}
              onClick={() => {
                // The Work surface is a DOCK (deep-linkable URL state), not a
                // local tray: monitoring delegated jobs must survive reloads
                // and be shareable. patchWorld closes any open tray for us.
                setTrayOpen(false);
                setMissionsOpen(false);
                navigateWorld({ dock: route.query.dock === "work" ? null : "work" });
              }}
              type="button"
              aria-expanded={route.query.dock === "work"}
            >
              <Activity size={14} />
              <span>{t("work.title")}</span>
            </button>
          )}
          <a
            className={route.demo ? "trayButton demoButton active" : "trayButton demoButton"}
            href={route.demo ? "/" : "/demo"}
            title={route.demo ? t("nav.exitDemo") : t("nav.demo")}
          >
            <Sparkles size={14} />
            <span>{route.demo ? t("nav.exitDemo") : t("nav.demo")}</span>
          </a>
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
      </SystemScene>
      <CoachMarks open={tourOpen} onClose={() => setTourOpen(false)} />
    </main>
  );
}
