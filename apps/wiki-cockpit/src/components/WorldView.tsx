// WorldView: the 3D-first cockpit shell. The scene IS the navigation surface;
// everything else is a thin HUD fixed to the sceneShell edges — top strip
// (breadcrumbs + snapshot age + honest totals), left mission card, right
// PageReader dock, bottom command bar (search, perspective glyphs, packet
// tray, minimap hint). The old below-the-fold panel stack is gone: every ops
// action is reachable inside the viewport.

import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { t } from "../data/i18n";
import { contextLabel, worldGroupLabel } from "../data/presentation";
import { groupKeyForPage } from "../scene/perspectives";
import { SCENE_FACETS, nodeQuadrant, quadrantHomesFromAssignments, sceneFacetOf } from "../scene/facets";
import type { QuadrantHomes, SceneFacet } from "../scene/facets";
import { computeCondition } from "../scene/condition";
import { rankPages } from "../scene/search";
import { buildUrl, navigate, patchWorld, retreat } from "../router";
import type { WorldPatch, WorldRoute } from "../router";
import { anchorRecord, focusAnchorId } from "../data/blocks";
import { composeInstruments, rootAnchor } from "../data/surfaces";
import type { RuntimeConfig } from "../data/runtimeConfig";
import type { ActionCard, BriefSpec, PageRecord, SnapshotBundle } from "../types";
import { CoachMarks, tourSeen } from "./CoachMarks";
import { CreateDock } from "./CreateDock";
import { deriveMissions, missionBriefSpec, MissionsPanel } from "./MissionsPanel";
import { PageReader } from "./PageReader";
import type { RelationGroupKey } from "./PageReader";
import { sceneFallbackPreferred, SystemScene } from "./SystemScene";
import type { SceneGuide, ScenePatch, SceneSeed } from "./SystemScene";
import { CommandBar } from "./world/CommandBar";
import { FoundingFallback } from "./world/FoundingFallback";
import { GuideFallback } from "./world/GuideFallback";
import { MissionCard, SEARCH_VISIBLE } from "./world/MissionCard";
import type { MissionRow } from "./world/MissionCard";
import { PacketTray } from "./world/PacketTray";
import type { FoundingSpec } from "../scene/spatial";
import { demoWorldUrl, genesisAction, genesisQuadrantMatches, genesisUrl } from "../data/genesis";
import { genesisGuide } from "../data/genesisGuide";

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

function gateTone(status: string): "good" | "warn" | "bad" {
  const value = status.toLowerCase();
  if (["pass", "passed", "success", "ok"].includes(value)) return "good";
  if (["fail", "failed", "error", "blocked"].includes(value)) return "bad";
  return "warn";
}

function updatedLabel(value: string): string {
  if (!value) return t("misc.noDate");
  return value.replace("T", " ").replace("Z", "").slice(0, 16);
}

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
// you did not ask for. The interface STARTS clean: collapsed (one honest chip)
// until the owner opens it; the choice is remembered per browser (UI state,
// not world state: it stays out of the URL on purpose).
const MISSION_CARD_KEY = "wiki-cockpit.missionCard";
function missionCardPref(): boolean {
  try {
    return window.localStorage.getItem(MISSION_CARD_KEY) === "open";
  } catch {
    return false;
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
  bornPageIds,
  onRun,
  onNotice,
  onComposeBrief
}: {
  bundle: SnapshotBundle;
  runtime: RuntimeConfig;
  route: WorldRoute;
  // Pages that did not exist in the previous bundle — the scene greets them
  // with a birth burst (genesis stage advances; later, real post-merge loads).
  bornPageIds?: string[];
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
      !route.query.genesis && // the genesis IS the tour
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

  // Command-bar handlers (the bar itself is a dumb component in world/).
  const closeTrays = () => {
    setTrayOpen(false);
    setMissionsOpen(false);
  };
  const toggleTray = () => {
    const opening = !trayOpen;
    setTrayOpen(opening);
    setMissionsOpen(false);
    // One work surface at a time: opening the tray closes dock/reader.
    if (opening && (routeRef.current.query.dock || routeRef.current.query.reader)) {
      navigateWorld({ dock: null, reader: false });
    }
  };
  const toggleMissions = () => {
    const opening = !missionsOpen;
    setMissionsOpen(opening);
    setTrayOpen(false);
    if (opening && (routeRef.current.query.dock || routeRef.current.query.reader)) {
      navigateWorld({ dock: null, reader: false });
    }
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

  const activeQuadrantAnchorId = useMemo(
    () => focusAnchorId(bundle, route.query.center || route.pageId || undefined) ?? rootAnchor(bundle)?.id ?? null,
    [bundle, route.pageId, route.query.center]
  );
  const activeQuadrantAnchor = useMemo(
    () => anchorRecord(bundle, activeQuadrantAnchorId ?? undefined),
    [bundle, activeQuadrantAnchorId]
  );

  // The AUTHORITATIVE per-page quadrant classification: the compiler's derived
  // quadrant_assignments on the ACTIVE anchor, inverted into a pageId → facet
  // map. Selecting a template/root page recenters the quadrants; the scene,
  // compass and quadrant scoping read THIS. The static page-type map is only
  // the fallback for pages outside the active anchor's compiled scope.
  const quadrantHomes = useMemo<QuadrantHomes | undefined>(() => {
    return quadrantHomesFromAssignments(activeQuadrantAnchor?.derived?.quadrant_assignments);
  }, [activeQuadrantAnchor]);

  const quadrantSceneGraph = useMemo(() => {
    const assignments = activeQuadrantAnchor?.derived?.quadrant_assignments;
    if (route.perspective !== "quadrants" || !assignments || !activeQuadrantAnchorId) {
      return bundle.graph;
    }
    const visibleIds = new Set<string>([activeQuadrantAnchorId]);
    Object.values(assignments).forEach((ids) => ids.forEach((id) => visibleIds.add(id)));
    const nodes = bundle.graph.nodes.filter((node) => visibleIds.has(node.id));
    const edges = bundle.graph.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target));
    return { nodes, edges };
  }, [activeQuadrantAnchor, activeQuadrantAnchorId, bundle.graph, route.perspective]);

  // Quadrant compass: live per-quadrant home counts (+ the honest core) for the
  // Quadrants perspective — the 2×2 grid you fly by. Computed from the same
  // classification the layout uses, so it never overstates.
  const quadrantCounts = useMemo(() => {
    if (route.perspective !== "quadrants") return null;
    const assignments = activeQuadrantAnchor?.derived?.quadrant_assignments;
    if (assignments) {
      return {
        quadrants: SCENE_FACETS.map((facet) => ({
          facet,
          count: (assignments[facet === "intencao" ? "q1" : facet === "pratica" ? "q2" : facet === "relacoes" ? "q3" : "q4"] ?? []).length
        })),
        core: assignments.q0_core?.length ?? 0
      };
    }
    const counts = new Map<SceneFacet, number>(SCENE_FACETS.map((facet) => [facet, 0]));
    let core = 0;
    bundle.graph.nodes.forEach((node) => {
      const home = nodeQuadrant(node.id, node.page_type, quadrantHomes);
      if (home) counts.set(home, (counts.get(home) ?? 0) + 1);
      else core += 1;
    });
    return { quadrants: SCENE_FACETS.map((facet) => ({ facet, count: counts.get(facet) ?? 0 })), core };
  }, [route.perspective, activeQuadrantAnchor, bundle.graph, quadrantHomes]);

  // The world's condition — the honest ambient readout (weather is set from it in
  // the scene). Every segment is a real count that flies to the act point.
  const condition = useMemo(() => computeCondition(bundle), [bundle]);

  // Scene wake-up: on some fresh mounts the r3f canvas races the shell's CSS
  // layout, measures 0×0 and then never commits its children (black world,
  // HUD alive) — a window resize is the proven unsticker. Nudge it twice after
  // mount; a real resize event is idempotent and costs one relayout.
  useEffect(() => {
    const first = window.setTimeout(() => window.dispatchEvent(new Event("resize")), 80);
    const second = window.setTimeout(() => window.dispatchEvent(new Event("resize")), 520);
    return () => {
      window.clearTimeout(first);
      window.clearTimeout(second);
    };
  }, []);

  // The instruments this world ACTUALLY has — composed from the root stack.
  // Templates add interface: no gamification package → no missions, no weather;
  // no quadrants block → no quadrant map; empty world → no instruments at all.
  const instruments = useMemo(() => composeInstruments(bundle), [bundle]);

  // Spatial-first routing: the founding rite and the seed flow live IN the
  // canvas; the 2D twins (DOM cards, the bottom sheet) are the declared
  // fallback for reduced-motion / no-WebGL / visual-test mode. LIVE state —
  // it must track the same media signal SystemScene's internal fallback does,
  // or the two branches disagree and no surface renders at all.
  const [fallbackActive, setFallbackActive] = useState(sceneFallbackPreferred);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setFallbackActive(sceneFallbackPreferred());
    media.addEventListener?.("change", update);
    window.addEventListener("popstate", update);
    return () => {
      media.removeEventListener?.("change", update);
      window.removeEventListener("popstate", update);
    };
  }, []);

  // R3 — universal exit, highest priority: Esc closes the topmost work
  // surface (tray/panel first, then any open dock) before the scene's own Esc
  // ladder (reader → plate → level up) gets to run. Capture phase +
  // stopImmediatePropagation preempts the scene's window listener — without
  // it the scene handler acts on a pre-close route and replays the old URL.
  // No typing-target guard on purpose: Esc closes the top surface, always.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // The Brief Studio is a text-editing modal with its own close affordance
      // — Esc must not mutate the layers UNDER it.
      if (document.querySelector(".briefStudio")) return;
      if (trayOpen || missionsOpen) {
        event.stopImmediatePropagation();
        event.stopPropagation();
        setTrayOpen(false);
        setMissionsOpen(false);
        return;
      }
      const current = routeRef.current;
      if (current.query.dock) {
        event.stopImmediatePropagation();
        event.stopPropagation();
        navigate(
          patchWorld(current, {
            dock: null,
            src: null,
            quadrant: current.query.dock === "create" ? null : undefined
          })
        );
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [trayOpen, missionsOpen]);

  // R8 — the trays are work surfaces too: opening a dock or the reader closes
  // them, whatever path opened it (condition strip, quest plate, guide CTA).
  useEffect(() => {
    if (route.query.dock || route.query.reader) {
      setTrayOpen(false);
      setMissionsOpen(false);
    }
  }, [route.query.dock, route.query.reader]);

  // An EMPTY world has exactly one interface: the founding rite. A dock in the
  // URL there (deep link, stale history) would open a surface over nothing.
  useEffect(() => {
    if (instruments.worldEmpty && route.query.dock) {
      navigate(patchWorld(route, { dock: null, src: null }), { replace: true });
    }
  }, [instruments.worldEmpty, route]);

  // The genesis IS the tour — mark the coach marks as seen for later sessions.
  useEffect(() => {
    if (!route.query.genesis) return;
    try {
      window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    } catch {
      /* private mode */
    }
  }, [route.query.genesis]);

  // R1 — founding: the rite's single outcome is a create brief for the root.
  // In the genesis it advances the stage (the staged snapshot IS the result);
  // in a real empty wiki the same brief becomes the setup PR.
  const foundWorld = (rootType: string, name: string) => {
    onComposeBrief?.({
      mission_kind: "create",
      theme: "found-root",
      grounding: {
        attach_context_package: true,
        create: {
          page_type: "root_entity",
          title: name,
          context: "system",
          home_facet: null,
          pinned: [{ key: "root_entity_type", label: "Root entity type", value: rootType, required: true }]
        }
      },
      intent:
        `Found this wiki's root entity: a ${rootType} named "${name}". Scaffold the root page from its ` +
        `template (memories/root/), set root_entity_type=${rootType}, wire the generated subpages, and open ` +
        `the setup draft PR. Never touch main directly.`
    });
  };
  const founding: FoundingSpec | null =
    instruments.worldEmpty && onComposeBrief ? { demo: route.demo, onFound: foundWorld } : null;

  // R4 — the create flow, spatial by default. `?dock=create` is still the one
  // URL for creating; what changes is the SURFACE that answers it.
  const contexts = useMemo(() => Object.keys(bundle.freshness?.by_context ?? {}).sort(), [bundle]);
  const seedActive = route.query.dock === "create" && !instruments.worldEmpty && Boolean(onComposeBrief);
  const seed: SceneSeed | null =
    seedActive && !fallbackActive
      ? {
          types: bundle.templates?.types ?? {},
          catalog: instruments.createCatalog,
          contexts,
          genesis: route.query.genesis,
          initialType: route.query.src || undefined,
          onSeed: (spec) => onComposeBrief?.(spec),
          onCancel: () => navigateWorld({ dock: null, src: null, quadrant: null }),
          onPreviewQuadrant: (facet) => navigateWorld({ quadrant: facet }, { replace: true })
        }
      : null;

  // R5 — the tutorial guide, anchored to each stage's subject. Present before,
  // during and after the action; Back/Skip live on the beacon itself. Demo
  // only — a stray ?genesis=1 on a real wiki must not summon the simulation.
  const goStage = (stage: number) => navigate(genesisUrl(stage, { visual: route.query.visual }));
  const skipHref = demoWorldUrl({ visual: route.query.visual });
  const guideData = route.demo && route.query.genesis ? genesisGuide(route.query.stage) : null;
  const handleQuadrantSelect = (facet: SceneFacet) => {
    const active = route.query.quadrant === facet;
    navigateWorld({
      perspective: "quadrants",
      quadrant: active ? null : facet,
      pageId: null,
      reader: false,
      dock: null,
      src: null
    });
    if (!active && route.demo && route.query.genesis && genesisQuadrantMatches(route.query.stage, facet)) {
      window.setTimeout(() => goStage(route.query.stage + 1), 850);
    }
  };
  const guide: SceneGuide | null = guideData
    ? {
        progress: guideData.progress,
        title: guideData.title,
        body: guideData.body,
        cta: guideData.ctaLabel
          ? {
              label: guideData.ctaLabel,
              onClick: () => {
                const action = genesisAction(guideData.stage);
                if (action.kind === "quadrant") {
                  handleQuadrantSelect(action.facet);
                  return;
                }
                if (guideData.dock) {
                  navigateWorld({ dock: guideData.dock.dock, src: guideData.dock.src ?? null, pageId: null, reader: false });
                } else {
                  goStage(guideData.stage + 1);
                }
              }
            }
          : null,
        during: guideData.during,
        // Only THE stage's own surface counts as "acting": an unrelated dock
        // must neither show the during-instruction nor hide the CTA.
        actionOpen: guideData.dock ? route.query.dock === guideData.dock.dock : false,
        onBack: guideData.stage > 0 ? () => goStage(guideData.stage - 1) : null,
        skipHref,
        final: guideData.final ? { exploreHref: skipHref, onRestart: () => goStage(0) } : null,
        anchorId: guideData.anchorId
      }
    : null;
  // The Missions button carries its own mission: the live count of open ones.
  const missions = useMemo(
    () => (instruments.missionsEnabled ? deriveMissions(bundle, route.demo) : []),
    [bundle, instruments.missionsEnabled, route.demo]
  );
  const openMissionCount = missions.length;
  // Quest markers: missions PLACED IN THE WORLD, game-style — a marker floats
  // over each page that asks for attention; hovering says why, clicking opens
  // it. Capped so the sky never becomes noise.
  // "Later": a marker the owner waved away stays away for this session — the
  // mission itself stays honest in the panel.
  const [dismissedQuests, setDismissedQuests] = useState<Set<string>>(new Set());
  const missionMarkers = useMemo(() => {
    // ONE marker per page (a page can carry several missions — the reader and
    // missions panel tell the full story). RELATION missions outrank plain
    // staleness on the same page: "Reconnect with Marina" is the human beat,
    // not "refresh the file". Capped against noise.
    const byPage = new Map<string, { pageId: string; kind: string; title: string; why: string; care: boolean }>();
    for (const mission of missions) {
      if (!mission.pageId || dismissedQuests.has(mission.pageId)) continue;
      const care = mission.key.startsWith("relation-") || mission.key.startsWith("date-") || mission.key.startsWith("commit-");
      const existing = byPage.get(mission.pageId);
      if (existing && (existing.care || !care)) continue;
      byPage.set(mission.pageId, { pageId: mission.pageId, kind: mission.kind, title: mission.title, why: mission.why, care });
    }
    return [...byPage.values()].slice(0, 8).map(({ care: _care, ...marker }) => marker);
  }, [missions, dismissedQuests]);

  // Witness a birth: glide the camera to the first newborn for a beat, then
  // release control (the burst plays where the eye already is).
  const [flyToPageId, setFlyToPageId] = useState("");
  useEffect(() => {
    if (!bornPageIds || bornPageIds.length === 0) return undefined;
    setFlyToPageId(bornPageIds[0]);
    const timer = window.setTimeout(() => setFlyToPageId(""), 2600);
    return () => window.clearTimeout(timer);
  }, [bornPageIds]);

  // The anchor "city tooltip": architecture + population + care debt on hover.
  const anchorInfo = useMemo(() => {
    const info: Record<string, { landmark: string; lensedPages: number; relationsDue: number; missions: number }> = {};
    const missionsByPage = new Map<string, number>();
    for (const mission of missions) {
      if (mission.pageId) missionsByPage.set(mission.pageId, (missionsByPage.get(mission.pageId) ?? 0) + 1);
    }
    for (const [id, record] of Object.entries(bundle.blockStacks?.anchors ?? {})) {
      const assignments = record.derived?.quadrant_assignments;
      const lensedPages = assignments
        ? Object.values(assignments).reduce((total, ids) => total + ids.length, 0)
        : 0;
      info[id] = {
        landmark: record.identity?.landmark ?? "",
        lensedPages,
        relationsDue: record.derived?.relations?.due.length ?? 0,
        missions: missionsByPage.get(id) ?? 0
      };
    }
    return info;
  }, [bundle, missions]);

  // The home view is a TEMPLATE decision (interface.views.default), not a
  // platform constant: a bare entry URL normalizes to the stack's default, and
  // a deep link to a perspective this world doesn't offer falls back too.
  useEffect(() => {
    // Applies to the EMPTY world too: before any lens exists there is no
    // quadrant map — the frame materializes only when the block attaches.
    if (!instruments.perspectives.includes(route.perspective) && route.perspective !== "focus") {
      navigate(buildUrl(patchWorld(route, { perspective: instruments.defaultPerspective })), { replace: true });
      return;
    }
    if (!route.perspectiveExplicit && route.perspective !== instruments.defaultPerspective) {
      navigate(buildUrl(patchWorld(route, { perspective: instruments.defaultPerspective })), { replace: true });
    }
  }, [instruments, route]);

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
        nodes={quadrantSceneGraph.nodes}
        edges={quadrantSceneGraph.edges}
        git={bundle.git}
        route={sceneRoute}
        packetIds={route.query.packet}
        highlightedPageIds={highlightedIds}
        approvalPageIds={approvalPageIds}
        isolateRelation={isolateRelation}
        walk={walk}
        snapshotAt={bundle.manifest.generated_at}
        activityLevel={bundle.timeline.bands.last_7_days || 0}
        weather={instruments.conditionEnabled ? condition.weather : "clear"}
        bornPageIds={bornPageIds}
        missionMarkers={missionMarkers}
        flyToPageId={flyToPageId}
        anchorInfo={anchorInfo}
        quadrantHomes={quadrantHomes}
        founding={fallbackActive ? null : founding}
        seed={fallbackActive ? null : seed}
        guide={fallbackActive ? null : guide}
        onMarkerResolve={
          onComposeBrief
            ? (pageId) => {
                const mission = missions.find((entry) => entry.pageId === pageId);
                const spec = mission ? missionBriefSpec(mission) : null;
                if (spec) onComposeBrief(spec);
              }
            : undefined
        }
        onMarkerDismiss={(pageId) => setDismissedQuests((prev) => new Set([...prev, pageId]))}
        onNavigate={(patch) => navigateWorld(patch as WorldPatch)}
        onRetreat={() => navigate(retreat(routeRef.current))}
        onFocusSearch={() => searchRef.current?.focus()}
        onTogglePacket={togglePacket}
        onRunRefresh={() => refreshAction && onRun(refreshAction)}
        makeHref={makeHref}
      >
        {/* TOP strip: breadcrumb trail + snapshot age + mode + true total.
            The EMPTY world shows nothing — "0 pages · demo" over the founding
            void is noise, and the founding rite is the only interface. */}
        {!instruments.worldEmpty && (
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
              weather is only allowed because these exact counts are printed.
              It EXISTS only with the gamification package attached (the world
              only asks for attention when a template asks it to). */}
          {instruments.conditionEnabled && (
          <div className={`conditionStrip weather-${condition.weather}`} role="group" aria-label={t("condition.aria")}>
            <span className="conditionWeather" title={t(`condition.weather.${condition.weather}`)}>
              {t(`condition.weather.${condition.weather}`)}
            </span>
            {condition.staleCount > 0 && (
              <button className="conditionSeg warn" onClick={() => navigateWorld({ filter: "stale" })} type="button">
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
          )}
          <div className="worldMeta">
            <span>{t("world.pages", { n: pages.length })}</span>
            <span>{t("world.updated", { when: updatedLabel(bundle.manifest.generated_at) })}</span>
            <span>{route.demo ? t("world.demoMode") : runtime.mode || bundle.manifest.mode}</span>
          </div>
        </div>
        )}

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
                  onClick={() => handleQuadrantSelect(facet)}
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

        {/* Quadrant SCOPE chip (radar/districts only): the AQAL map's selection
            carries into the spatial views and mutes everything outside it; this
            chip makes that state visible and one click to clear. */}
        {!quadrantCounts &&
          SCENE_FACETS.includes(route.query.quadrant as SceneFacet) &&
          (route.perspective === "radar" || route.perspective === "districts") && (
          <button
            className="quadrantScopeChip"
            onClick={() => navigateWorld({ quadrant: null })}
            title={t("world.quadrantScopeClear")}
            type="button"
          >
            {t("world.quadrantScope", { facet: t(`facet.${route.query.quadrant}`) })} <span aria-hidden>✕</span>
          </button>
        )}

        {/* LEFT mission surface. Collapsed by choice it is a single honest
            chip (worst tone + pending count) — the world stays visible;
            expanded it is the do-now card. Search results always render:
            the keyboard search flow must never depend on the card state. */}
        <MissionCard
          rows={missionRows}
          perspective={route.perspective}
          missionsEnabled={instruments.missionsEnabled}
          open={missionCardOpen}
          onToggle={() => {
            setMissionCardOpen((open) => {
              persistMissionCard(!open);
              return !open;
            });
          }}
          query={route.query.q}
          searchHits={searchHits}
          visibleHits={visibleHits}
          activeHit={activeHit}
          onActiveHit={setActiveHit}
          onOpenHit={openHit}
        />

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
            activeCenterId={activeQuadrantAnchorId}
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

        {/* BOTTOM command bar: search, perspective glyphs, packet tray. In an
            EMPTY world there are no instruments yet — the bar itself only
            exists once the root brings the first ones (genesis stage 0 shows
            nothing but the founding prompt). */}
        {!instruments.worldEmpty && (
          <CommandBar
            route={route}
            instruments={instruments}
            condition={condition}
            changedCount={changed}
            openMissionCount={openMissionCount}
            trayOpen={trayOpen}
            missionsOpen={missionsOpen}
            canComposeBrief={Boolean(onComposeBrief)}
            searchRef={searchRef}
            searchDraft={searchDraft}
            onSearchDraft={setSearchDraft}
            onSearchKeyDown={onSearchKeyDown}
            onNavigateWorld={navigateWorld}
            onCloseTrays={closeTrays}
            onToggleTray={toggleTray}
            onToggleMissions={toggleMissions}
            onOpenTour={() => setTourOpen(true)}
          />
        )}

        {/* Decision-packet slide-up tray (replaces ImpactBundlePanel). */}
        {trayOpen && (
          <PacketTray
            packetPages={packetPages}
            reviewAction={reviewAction}
            gateAction={gateAction}
            prAction={prAction}
            onRun={onRun}
            onOpenPage={(id) => navigateWorld({ pageId: id, reader: true })}
            onTogglePacket={togglePacket}
            onClearPacket={() => navigateWorld({ packet: [] }, { replace: true })}
            onClose={() => setTrayOpen(false)}
          />
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

      {/* The declared 2D fallback of the create flow: the bottom sheet, only
          when the canvas cannot host the spatial seeder. */}
      {seedActive && fallbackActive && (
        <CreateDock
          bundle={bundle}
          initialType={route.query.src}
          initialQuadrant={route.query.quadrant}
          genesis={route.query.genesis}
          onComposeBrief={(spec) => onComposeBrief?.(spec)}
          onHighlightQuadrant={(facet) => navigateWorld({ quadrant: facet }, { replace: true })}
          onClose={() => navigateWorld({ dock: null, src: null, quadrant: null })}
        />
      )}
      {/* 2D twins of the founding rite and the guide beacon (fallback mode). */}
      {fallbackActive && founding && (
        <FoundingFallback demo={route.demo} skipHref={route.demo ? skipHref : undefined} onFound={foundWorld} />
      )}
      {fallbackActive && guide && !founding && <GuideFallback guide={guide} />}
      <CoachMarks open={tourOpen} onClose={() => setTourOpen(false)} />
    </main>
  );
}
