// WorldView: the 3D-first cockpit shell. The scene IS the navigation surface;
// everything else is a thin HUD fixed to the sceneShell edges — top strip
// (breadcrumbs + snapshot age + honest totals), left mission card, right
// PageReader dock, bottom command bar (search, perspective glyphs, packet
// tray, minimap hint). The old below-the-fold panel stack is gone: every ops
// action is reachable inside the viewport.

import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";
import { Copy, RotateCcw, SlidersHorizontal, X } from "lucide-react";
import { t } from "../data/i18n";
import { experiencePackView } from "../data/experiencePacks";
import { contextLabel, pageTypeLabel, pageTypeStyle, perspectiveLabel, worldGroupDescription, worldGroupLabel } from "../data/presentation";
import { groupKeyForPage, isSourceEmitterType } from "../scene/perspectives";
import type { PerspectiveId as ScenePerspectiveId } from "../scene/perspectives";
import { SCENE_FACETS, nodeQuadrant, quadrantHomesFromAssignments, sceneFacetOf } from "../scene/facets";
import type { QuadrantHomes, SceneFacet } from "../scene/facets";
import { parseRealFamilyGroupId } from "../scene/worldState";
import { scopeGraphToCompiledAnchor } from "../scene/worldScope";
import { computeCondition } from "../scene/condition";
import { searchPages } from "../scene/search";
import { canonicalWorldUrl, hydrateWorldRoute } from "../world/state/routeHydration";
import type { OverlayId, RuntimeEvent } from "../world/contracts";
import type { WorldPatch, WorldRoute } from "../router";
import type { NavigationPort, OperatorPort } from "../application/ports";
import { anchorRecord, anchorSupportsQuadrants, focusAnchorId } from "../data/blocks";
import { composeInstruments, rootAnchor } from "../data/surfaces";
import { regionPayloadByKey } from "../data/visualPrimitives";
import type { RuntimeConfig } from "../data/runtimeConfig";
import type { OperatorCommandCard, BriefSpec, PageRecord, RegionGroupPayload, SnapshotBundle } from "../types";
import { CoachMarks, tourSeen } from "./CoachMarks";
import { CreateDock } from "./CreateDock";
import { deriveMissions, missionBriefSpec, MissionsPanel } from "./MissionsPanel";
import type { RelationGroupKey } from "./PageReader";
import { sceneFallbackPreferred } from "../renderers/scene/parts/materials";
import type { SceneGuide, ScenePatch, SceneSeed } from "./SystemScene";
import { CommandBar } from "./world/CommandBar";
import { FoundingFallback } from "./world/FoundingFallback";
import { GuideFallback } from "./world/GuideFallback";
import {
  MissionCard,
  SEARCH_RESULTS_ID,
  SEARCH_VISIBLE,
  searchResultOptionId
} from "./world/MissionCard";
import type { MissionRow } from "./world/MissionCard";
import { PacketTray } from "./world/PacketTray";
import { WorldNavigator } from "./world/WorldNavigator";
import { useSurfacePresence } from "./world/useSurfacePresence";
import { isNativeWorldViewId } from "../world/experience";
import {
  DEFAULT_VISUAL_CONTROL_CONFIG,
  isVisualControlCommand,
  loadVisualControlConfig,
  normalizeVisualControlConfig,
  VISUAL_CONTROL_PRESETS,
  VISUAL_CONTROL_COCKPIT_VERSION,
  VISUAL_CONTROL_STORAGE_KEY,
  visualControlDefaultSnippet,
  visualControlPayload
} from "./visualControl";
import type { VisualControlConfig, VisualLabelMode } from "./visualControl";
import type { FoundingSpec } from "../renderers/scene/spatial";
import { demoWorldUrl, genesisAction, genesisQuadrantMatches, genesisUrl } from "../data/genesis";
import { genesisGuide } from "../data/genesisGuide";
import { motionCssVariables, overlayResolveDurationMs } from "../world/visual/motionGrammar";
import {
  RUNTIME_PERFORMANCE_FALLBACK_EVENT,
  runtimePerformanceFallbackLatched
} from "../world/performance";

const SystemScene = lazy(() => import("./SystemScene").then((module) => ({ default: module.SystemScene })));
const PageReader = lazy(() => import("./PageReader").then((module) => ({ default: module.PageReader })));
const TimelineView = lazy(() => import("./TimelineView").then((module) => ({ default: module.TimelineView })));
const PackWorkbench = lazy(() => import("./PackWorkbench").then((module) => ({ default: module.PackWorkbench })));

function MeasuredWorldTopStrip({ children, ariaLabel }: { children: ReactNode; ariaLabel: string }) {
  const stripRef = useRef<HTMLDivElement>(null);

  // Compatibility context can wrap differently across platform font stacks.
  // Publish the actual strip height so the mission surface always starts
  // below its complete pointer region instead of relying on a screenshot-tuned
  // desktop offset. Keep this component-local so it also runs after the lazy
  // scene shell resolves from Suspense.
  useLayoutEffect(() => {
    const strip = stripRef.current;
    const sceneShell = strip?.closest<HTMLElement>(".sceneShell");
    if (!strip || !sceneShell) return;

    const publishHeight = () => {
      sceneShell.style.setProperty("--world-top-strip-height", `${Math.ceil(strip.getBoundingClientRect().height)}px`);
    };
    publishHeight();

    if (typeof ResizeObserver === "undefined") {
      return () => sceneShell.style.removeProperty("--world-top-strip-height");
    }
    const observer = new ResizeObserver(publishHeight);
    observer.observe(strip);
    return () => {
      observer.disconnect();
      sceneShell.style.removeProperty("--world-top-strip-height");
    };
  }, []);

  return (
    <div ref={stripRef} className="worldTopStrip" aria-label={ariaLabel}>
      {children}
    </div>
  );
}

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

function compactFamilyLabel(family: string): string {
  return pageTypeLabel(`visual_group_${family || "content"}`);
}

function familyClass(family: string): string {
  return `family-${(family || "content").replace(/[^a-z0-9_-]/gi, "").toLowerCase() || "content"}`;
}

function regionTextList(items: { page_type?: string; family?: string; kind?: string; count: number }[], label: (item: { page_type?: string; family?: string; kind?: string; count: number }) => string): string {
  return items.length > 0 ? items.map(label).join(", ") : "none";
}

function typeMixLabel(item: { page_type?: string; family?: string; count: number }): string {
  return `${item.page_type ? pageTypeLabel(item.page_type) : compactFamilyLabel(item.family || "content")} ${item.count}`;
}

function quadrantAqalText(facet: SceneFacet): { mark: string; position: string } {
  return {
    mark: t(`quadrant.aqal.${facet}.mark`),
    position: t(`quadrant.aqal.${facet}.position`)
  };
}

function quadrantHealthStyle(region: RegionGroupPayload | undefined, fallbackCount: number): CSSProperties {
  // Region payloads can describe only the compiler-classified slice of the
  // current world. Percentages must still use the full on-screen quadrant
  // count, otherwise a partial payload visually overstates its condition.
  const total = Math.max(fallbackCount, 1);
  const stale = ((region?.summary.stale ?? 0) / total) * 100;
  const proposal = ((region?.summary.proposal ?? 0) / total) * 100;
  const risk = ((region?.summary.risk ?? 0) / total) * 100;
  const raw = ((region?.summary.raw ?? 0) / total) * 100;
  const calm = Math.max(0, 100 - stale - proposal - risk - raw);
  let cursor = 0;
  const segments = [
    { color: "#5ee6a8", value: calm },
    { color: "#ffb454", value: stale },
    { color: "#c57cff", value: proposal },
    { color: "#ff7a8a", value: risk },
    { color: "#57d9a0", value: raw }
  ]
    .filter((segment) => segment.value > 0.5)
    .map((segment) => {
      const start = cursor;
      cursor += segment.value;
      return `${segment.color} ${start}% ${cursor}%`;
    });
  return { "--quadrant-health": `conic-gradient(${segments.join(", ") || "#5ee6a8 0 100%"})` } as CSSProperties;
}

function quadrantInstrumentLabel(facetLabel: string, total: number, region: RegionGroupPayload | undefined): string {
  if (!region) return `${facetLabel}: ${total}`;
  const typeMix = regionTextList(region.type_mix.slice(0, 5), typeMixLabel);
  const attention = region.attention_hints.length > 0
    ? region.attention_hints.slice(0, 4).map((hint) => t(`region.attention.${hint.kind}`, { n: hint.count })).join(", ")
    : t("region.healthy");
  const action = region.action_hints[0]
    ? t("quadrant.instrument.next", { action: t(region.action_hints[0].label_key, { n: region.action_hints[0].count }) })
    : "";
  return [
    `${facetLabel}: ${t("world.pages", { n: total })}`,
    region.summary.total !== total ? t("quadrant.instrument.classified", { n: region.summary.total }) : "",
    region.summary.hidden > 0 ? t("region.attention.hidden", { n: region.summary.hidden }) : "",
    t("quadrant.instrument.types", { items: typeMix }),
    t("quadrant.instrument.signals", { items: attention }),
    action
  ].filter(Boolean).join("\n");
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
    if (window.matchMedia?.("(max-width: 900px)").matches) return false;
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

function VisualControlPanel({
  config,
  onConfig,
  onClose,
  onReset
}: {
  config: VisualControlConfig;
  onConfig: (config: VisualControlConfig) => void;
  onClose: () => void;
  onReset: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [copiedSnippet, setCopiedSnippet] = useState(false);
  const [draftPayload, setDraftPayload] = useState("");
  const [payloadDirty, setPayloadDirty] = useState(false);
  const [payloadError, setPayloadError] = useState("");
  const payload = useMemo(
    () => JSON.stringify(visualControlPayload(config, VISUAL_CONTROL_COCKPIT_VERSION), null, 2),
    [config]
  );
  const defaultSnippet = useMemo(() => visualControlDefaultSnippet(config), [config]);
  useEffect(() => {
    if (!payloadDirty) setDraftPayload(payload);
  }, [payload, payloadDirty]);
  const setNumber = (key: keyof Pick<VisualControlConfig, "glow" | "contrast" | "density" | "spacing" | "motion" | "uiScale" | "glass">, value: string) => {
    onConfig(normalizeVisualControlConfig({ ...config, [key]: Number(value) }));
    setPayloadDirty(false);
    setPayloadError("");
  };
  const setLabels = (labels: VisualLabelMode) => {
    onConfig(normalizeVisualControlConfig({ ...config, labels }));
    setPayloadDirty(false);
    setPayloadError("");
  };
  const applyConfig = (next: VisualControlConfig) => {
    onConfig(normalizeVisualControlConfig(next));
    setPayloadDirty(false);
    setPayloadError("");
  };
  const applyDraftPayload = () => {
    try {
      const parsed = JSON.parse(draftPayload);
      const source = parsed && typeof parsed === "object" && "config" in parsed
        ? (parsed as { config?: unknown }).config
        : parsed;
      onConfig(normalizeVisualControlConfig(source));
      setPayloadDirty(false);
      setPayloadError("");
    } catch {
      setPayloadError(t("visualControl.json.invalid"));
    }
  };
  const copyPayload = async () => {
    try {
      await navigator.clipboard.writeText(payloadDirty ? draftPayload : payload);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  };
  const copySnippet = async () => {
    try {
      await navigator.clipboard.writeText(defaultSnippet);
      setCopiedSnippet(true);
      window.setTimeout(() => setCopiedSnippet(false), 1400);
    } catch {
      setCopiedSnippet(false);
    }
  };
  const sliders: { key: keyof Pick<VisualControlConfig, "glow" | "contrast" | "density" | "spacing" | "motion" | "uiScale" | "glass">; min: number; max: number; step: number }[] = [
    { key: "glow", min: 0.55, max: 1.8, step: 0.05 },
    { key: "contrast", min: 0.8, max: 1.35, step: 0.05 },
    { key: "density", min: 0.7, max: 1.35, step: 0.05 },
    { key: "spacing", min: 0.72, max: 1.85, step: 0.05 },
    { key: "motion", min: 0, max: 1.4, step: 0.05 },
    { key: "uiScale", min: 0.9, max: 1.12, step: 0.01 },
    { key: "glass", min: 0.55, max: 1.15, step: 0.05 }
  ];

  return (
    <aside className="visualControlPanel" role="dialog" aria-label={t("visualControl.aria")}>
      <span className="visualControlMotes" aria-hidden>
        <i />
        <i />
        <i />
        <i />
        <i />
        <i />
      </span>
      <header className="visualControlHeader">
        <span className="visualControlIcon" aria-hidden><SlidersHorizontal size={15} /></span>
        <div>
          <strong>{t("visualControl.title")}</strong>
          <small>{t("visualControl.subtitle")}</small>
        </div>
        <button className="readerClose" aria-label={t("visualControl.close")} onClick={onClose} title={t("visualControl.close")} type="button">
          <X size={14} />
        </button>
      </header>
      <div className="visualControlPresetGrid" role="group" aria-label={t("visualControl.presets.aria")}>
        {Object.entries(VISUAL_CONTROL_PRESETS).map(([name, preset]) => (
          <button key={name} onClick={() => applyConfig(preset)} type="button">
            {t(`visualControl.preset.${name}`)}
          </button>
        ))}
      </div>
      <div className="visualControlGrid">
        {sliders.map((slider) => (
          <label className="visualControlSlider" key={slider.key}>
            <span>
              <b>{t(`visualControl.slider.${slider.key}`)}</b>
              <small>{config[slider.key].toFixed(slider.step < 0.05 ? 2 : 1)}×</small>
            </span>
            <input
              type="range"
              min={slider.min}
              max={slider.max}
              step={slider.step}
              value={config[slider.key]}
              onChange={(event) => setNumber(slider.key, event.target.value)}
            />
          </label>
        ))}
      </div>
      <div className="visualControlModes" role="group" aria-label={t("visualControl.labels.aria")}>
        {(["quiet", "balanced", "dense"] as VisualLabelMode[]).map((mode) => (
          <button
            key={mode}
            className={config.labels === mode ? "active" : ""}
            onClick={() => setLabels(mode)}
            type="button"
          >
            {t(`visualControl.labels.${mode}`)}
          </button>
        ))}
      </div>
      <label className="visualControlToggle">
        <input
          type="checkbox"
          checked={config.particles}
          onChange={(event) => applyConfig({ ...config, particles: event.target.checked })}
        />
        <span>{t("visualControl.particles")}</span>
      </label>
      <textarea
        className={payloadError ? "visualControlOutput invalid" : "visualControlOutput"}
        value={draftPayload}
        aria-label={t("visualControl.json.aria")}
        spellCheck={false}
        onChange={(event) => {
          setDraftPayload(event.target.value);
          setPayloadDirty(true);
          setPayloadError("");
        }}
      />
      <div className="visualControlPayloadHint" role={payloadError ? "alert" : undefined}>
        {payloadError || t("visualControl.json.hint")}
      </div>
      <label className="visualControlSnippet">
        <span>
          <b>{t("visualControl.snippet.title")}</b>
          <small>{t("visualControl.snippet.subtitle")}</small>
        </span>
        <textarea
          value={defaultSnippet}
          aria-label={t("visualControl.snippet.aria")}
          readOnly
          spellCheck={false}
        />
      </label>
      <div className="visualControlActions">
        <button className="textButton" onClick={() => {
          onReset();
          setPayloadDirty(false);
          setPayloadError("");
        }} type="button">
          <RotateCcw size={13} /> {t("visualControl.action.reset")}
        </button>
        <button className="textButton" disabled={!payloadDirty} onClick={applyDraftPayload} type="button">
          {t("visualControl.action.apply")}
        </button>
        <button className="textButton" onClick={copySnippet} type="button">
          <Copy size={13} /> {copiedSnippet ? t("visualControl.action.snippetCopied") : t("visualControl.action.copyDefault")}
        </button>
        <button className="primaryButton compact" onClick={copyPayload} type="button">
          <Copy size={13} /> {copied ? t("visualControl.action.copied") : t("visualControl.action.copyJson")}
        </button>
      </div>
    </aside>
  );
}

export function WorldView({
  bundle,
  runtime,
  route,
  bornPageIds,
  onRun,
  onNotice,
  onComposeBrief,
  navigation,
  loadPageContent,
  loadTemporalGraph,
  onSnapshotMismatch,
  worldRuntime,
  worldState
}: {
  bundle: SnapshotBundle;
  runtime: RuntimeConfig;
  route: WorldRoute;
  // Pages that did not exist in the previous bundle — the scene greets them
  // with a birth burst (genesis stage advances; later, real post-merge loads).
  bornPageIds?: string[];
  onRun: (action: OperatorCommandCard) => void;
  onNotice?: (text: string) => void;
  onComposeBrief?: (spec: BriefSpec) => void;
  navigation: NavigationPort;
  loadPageContent: OperatorPort["loadPageContent"];
  loadTemporalGraph: OperatorPort["loadTemporalGraph"];
  onSnapshotMismatch?: () => void;
  worldRuntime: import("../world/WorldRuntime").WorldRuntime;
  worldState: import("../world/contracts").WorldState;
}) {
  const pages = bundle.pages.pages;
  const packSurfaceActive = Boolean(route.query.packView);
  const activePackView = experiencePackView(bundle.experiencePacks, route.query.packView);
  const temporalViewActive = worldState.view === "timeline" && !packSurfaceActive;
  const temporalGraphAvailable = bundle.manifest.capabilities?.includes("temporal_graph") ?? false;
  const temporalSnapshotId = bundle.manifest.snapshot_id || bundle.manifest.source_commit || bundle.manifest.generated_at;
  const temporalRequestRef = useRef(0);
  const [temporalResource, setTemporalResource] = useState<{
    snapshotId: string;
    payload: SnapshotBundle["temporalGraph"];
    error: string;
    code: string;
  }>(() => ({ snapshotId: temporalSnapshotId, payload: undefined, error: "", code: "" }));
  const temporalGraph = temporalResource.snapshotId === temporalSnapshotId
    ? temporalResource.payload
    : undefined;
  const temporalGraphError = temporalResource.snapshotId === temporalSnapshotId
    ? temporalResource.error
    : "";
  const temporalGraphErrorCode = temporalResource.snapshotId === temporalSnapshotId
    ? temporalResource.code
    : "";
  useEffect(() => {
    if (!temporalViewActive || !temporalGraphAvailable || temporalGraph || temporalGraphError) return undefined;
    const controller = new AbortController();
    const requestId = temporalRequestRef.current + 1;
    temporalRequestRef.current = requestId;
    loadTemporalGraph(bundle, { signal: controller.signal })
      .then((payload) => {
        if (controller.signal.aborted || temporalRequestRef.current !== requestId) return;
        setTemporalResource({ snapshotId: temporalSnapshotId, payload, error: "", code: "" });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || temporalRequestRef.current !== requestId) return;
        setTemporalResource({
          snapshotId: temporalSnapshotId,
          payload: undefined,
          error: error instanceof Error ? error.message : String(error),
          code: typeof error === "object" && error && "code" in error && typeof error.code === "string"
            ? error.code
            : "network"
        });
      });
    return () => {
      controller.abort();
      if (temporalRequestRef.current === requestId) temporalRequestRef.current += 1;
    };
  }, [bundle, loadTemporalGraph, temporalGraph, temporalGraphAvailable, temporalGraphError, temporalSnapshotId, temporalViewActive]);
  const selectedPage = findPage(pages, route.pageId);
  const readerOpen = Boolean(route.pageId && route.query.reader && selectedPage);
  const readerPresence = useSurfacePresence(readerOpen);
  const [lastReaderPage, setLastReaderPage] = useState<PageRecord | undefined>(selectedPage);
  if (selectedPage && selectedPage !== lastReaderPage) setLastReaderPage(selectedPage);
  const readerPage = selectedPage ?? lastReaderPage;
  // The URL remains authoritative, while these refs form a one-commit
  // transaction buffer. They let two input events in the same browser task
  // accumulate instead of both projecting from the last React render.
  const routeRef = useRef(route);
  const pendingRouteRef = useRef(route);
  const pendingWorldStateRef = useRef(worldState);
  routeRef.current = route;
  useEffect(() => {
    pendingRouteRef.current = route;
  }, [route]);
  useEffect(() => {
    pendingWorldStateRef.current = worldState;
  }, [worldState]);
  useEffect(() => {
    // A manually composed/shared URL can predate the singleton contract and
    // name several primary surfaces. parseQuery has already selected the
    // deterministic winner; replace the address with that same truth so copy,
    // refresh and the accessibility tree cannot disagree.
    const currentUrl = navigation.getSnapshot();
    const query = new URLSearchParams(currentUrl.includes("?") ? currentUrl.slice(currentUrl.indexOf("?") + 1) : "");
    const requestedSurfaceCount = Number(Boolean(query.get("dock"))) +
      Number(query.get("reader") === "1") + Number(Boolean(query.get("tray")));
    if (requestedSurfaceCount <= 1) return;
    navigation.dispatch({
      type: "navigate",
      target: canonicalWorldUrl(worldState, route.demo, route.query),
      replace: true
    });
  }, [navigation, route.demo, route.query, worldState]);
  const dispatchRuntime = (event: RuntimeEvent) => {
    // Shareable state is route-owned. Project through the exact runtime
    // reducer, write one canonical URL, then let RuntimeWorldView hydrate that
    // route. Mutating here as well created two competing transition writers.
    const currentRoute = pendingRouteRef.current;
    const next = worldRuntime.project(event, pendingWorldStateRef.current);
    const target = canonicalWorldUrl(next, currentRoute.demo, currentRoute.query);
    pendingWorldStateRef.current = next;
    pendingRouteRef.current = navigation.toWorld(navigation.parseUrl(target));
    navigation.dispatch({ type: "navigate", target });
  };
  // Always navigate from the CURRENT route: async callbacks (debounce timers,
  // scene events) must never replay a stale route and revert navigation.
  const [searchDraft, setSearchDraft] = useState(route.query.q);
  const [activeHit, setActiveHit] = useState(0);
  // Keyboard events can arrive back-to-back before React commits the state
  // written by the previous event. Keep the active option in a synchronous
  // ref as well, so a pointer-hovered result from the previous draft cannot
  // leak into an immediate edit -> ArrowDown -> Enter sequence.
  const activeHitRef = useRef(0);
  const updateActiveHit = useCallback((index: number) => {
    activeHitRef.current = index;
    setActiveHit(index);
  }, []);
  // Trays are primary surfaces and therefore shareable route state, not local
  // component toggles. This makes a deep link, refresh and Back/Forward hydrate
  // exactly the same visible surface.
  const trayOpen = route.query.tray === "packet";
  const missionsOpen = route.query.tray === "missions";
  const [missionCardOpen, setMissionCardOpen] = useState(missionCardPref);
  const [worldNavigatorOpen, setWorldNavigatorOpen] = useState(false);
  const [visualPanelOpen, setVisualPanelOpen] = useState(false);
  const [overlayResolving, setOverlayResolving] = useState(false);
  const overlayResolvingRef = useRef(false);
  const overlayResolveTimerRef = useRef<number | null>(null);
  const [visualConfig, setVisualConfig] = useState<VisualControlConfig>(() =>
    loadVisualControlConfig(typeof window === "undefined" ? undefined : window.localStorage)
  );
  const [previewQuadrant, setPreviewQuadrant] = useState<SceneFacet | null>(null);
  const [tourOpen, setTourOpen] = useState(() => {
    if (typeof window === "undefined") return false;
    const params = new URLSearchParams(window.location.search);
    const requestedTour = params.get("tour");
    return (
      params.get("visual") !== "1" &&
      !route.query.genesis && // the genesis IS the tour
      (requestedTour === "1" || (requestedTour !== "0" && !tourSeen()))
    );
  });
  const [isolateRelation, setIsolateRelation] = useState<RelationGroupKey | null>(null);
  const [hoverLinkId, setHoverLinkId] = useState<string | null>(null);
  const [walk, setWalk] = useState<{ ids: string[]; step: number } | null>(null);
  const [trailIds, setTrailIds] = useState<string[]>([]);
  const primarySurfaceOpen = Boolean(
    worldState.dock ||
    worldState.readerId ||
    readerPresence.mounted ||
    trayOpen ||
    missionsOpen
  );
  const searchRef = useRef<HTMLInputElement>(null);
  const workspaceRef = useRef<HTMLElement>(null);
  const readerWasMountedRef = useRef(readerPresence.mounted);
  const readerOpenerRef = useRef<HTMLElement | null>(null);
  const dockOpenerRef = useRef<HTMLElement | null>(null);
  const dockFocusRestoreRef = useRef<number | null>(null);
  const previousDockRef = useRef(route.query.dock);
  const trayOpenerRef = useRef<HTMLElement | null>(null);
  const trayFocusTimerRef = useRef<number | null>(null);
  const previousTrayRef = useRef<typeof route.query.tray>("");
  const searchRouteTimerRef = useRef<number | null>(null);
  // Enter commits query + reader atomically. React may flush the draft effect
  // after the key handler, so remember the submitted value as well as clearing
  // an already-created timer; otherwise that late effect can replay the route
  // that existed before a dock closed and replace the reader with that dock.
  const submittedSearchRef = useRef<string | null>(null);
  const tourOpenerRef = useRef<HTMLElement | null>(null);
  const openTour = useCallback(() => {
    tourOpenerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setTourOpen(true);
  }, []);

  useEffect(() => {
    if (primarySurfaceOpen && visualPanelOpen) setVisualPanelOpen(false);
  }, [primarySurfaceOpen, visualPanelOpen]);

  // Primary surfaces keep the world visible for context, but the scene and
  // instruments behind them are inert until the surface closes. This is the
  // runtime surface-stack contract, not a per-dock convention.
  useEffect(() => {
    const touched = new Set<HTMLElement>();
    const applySurfaceState = () => {
      const root = workspaceRef.current;
      if (!root) return;
      const targetState = new Map<HTMLElement, boolean>();
      root.querySelectorAll<HTMLElement>(".sceneCanvasFrame, .sceneFallback, .radarStatusStrip, .worldMinimap").forEach((target) => {
        targetState.set(target, primarySurfaceOpen || worldNavigatorOpen || temporalViewActive || packSurfaceActive);
      });
      root.querySelectorAll<HTMLElement>(".worldCommandBar").forEach((target) => {
        targetState.set(target, primarySurfaceOpen || worldNavigatorOpen);
      });
      root.querySelectorAll<HTMLElement>(".worldTopStrip").forEach((target) => {
        targetState.set(target, primarySurfaceOpen);
      });
      root.querySelectorAll<HTMLElement>(
        ".worldBreadcrumbs, .conditionStrip, .worldMeta, .worldMissionCard, .worldMissionSlim, .quadrantCompass, .focusLegend"
      ).forEach((target) => {
        const activeSearchSurface = Boolean(target.closest('[data-search-active="true"]'));
        targetState.set(
          target,
          (targetState.get(target) ?? false) ||
            primarySurfaceOpen ||
            worldNavigatorOpen ||
            ((temporalViewActive || packSurfaceActive) && !activeSearchSurface)
        );
      });
      root.querySelectorAll<HTMLElement>(".timelineSurface, .packWorkbenchSurface").forEach((target) => {
        targetState.set(target, primarySurfaceOpen || worldNavigatorOpen);
      });
      for (const [target, active] of targetState) {
        touched.add(target);
        if (active) {
          target.inert = true;
          target.setAttribute("aria-hidden", "true");
        } else {
          target.inert = false;
          target.removeAttribute("aria-hidden");
        }
      }
    };
    applySurfaceState();
    const observer = typeof MutationObserver === "undefined" ? null : new MutationObserver(applySurfaceState);
    if (observer && workspaceRef.current) observer.observe(workspaceRef.current, { childList: true, subtree: true });
    return () => {
      observer?.disconnect();
      touched.forEach((target) => {
      target.inert = false;
      target.removeAttribute("aria-hidden");
      });
    };
  }, [packSurfaceActive, primarySurfaceOpen, temporalViewActive, worldNavigatorOpen]);

  useEffect(() => {
    if (readerWasMountedRef.current && !readerPresence.mounted) {
      const restoreFocus = () => {
        const opener = readerOpenerRef.current;
        if (opener?.isConnected && !opener.closest("[inert]")) opener.focus({ preventScroll: true });
        else searchRef.current?.focus({ preventScroll: true });
        readerOpenerRef.current = null;
      };
      // Presence keeps the closing reader mounted and the background inert
      // through its exit animation. Restore only after that surface is truly
      // gone, then wait one frame for the same commit to reactivate the HUD.
      if (typeof window.requestAnimationFrame === "function") window.requestAnimationFrame(restoreFocus);
      else window.setTimeout(restoreFocus, 0);
    }
    readerWasMountedRef.current = readerPresence.mounted;
  }, [readerPresence.mounted]);

  useEffect(() => {
    const pendingRestore = dockFocusRestoreRef.current;
    if (pendingRestore !== null) {
      window.cancelAnimationFrame?.(pendingRestore);
      window.clearTimeout(pendingRestore);
      dockFocusRestoreRef.current = null;
    }

    const previousDock = previousDockRef.current;
    const currentDock = route.query.dock;
    if (currentDock && !previousDock) {
      dockOpenerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    } else if (!currentDock && previousDock) {
      const restoreFocus = () => {
        dockFocusRestoreRef.current = null;
        // A guided flow can open the next dock before this deferred restore
        // runs. Never steal focus back from that newly opened surface.
        if (routeRef.current.query.dock) return;
        const opener = dockOpenerRef.current;
        if (opener?.isConnected && !opener.closest("[inert]")) opener.focus({ preventScroll: true });
        else searchRef.current?.focus({ preventScroll: true });
        dockOpenerRef.current = null;
      };
      dockFocusRestoreRef.current = typeof window.requestAnimationFrame === "function"
        ? window.requestAnimationFrame(restoreFocus)
        : window.setTimeout(restoreFocus, 0);
    }
    previousDockRef.current = currentDock;

    return () => {
      const restore = dockFocusRestoreRef.current;
      if (restore === null) return;
      window.cancelAnimationFrame?.(restore);
      window.clearTimeout(restore);
      dockFocusRestoreRef.current = null;
    };
  }, [route.query.dock]);

  useEffect(() => {
    const pendingFocus = trayFocusTimerRef.current;
    if (pendingFocus !== null) {
      window.cancelAnimationFrame?.(pendingFocus);
      window.clearTimeout(pendingFocus);
      trayFocusTimerRef.current = null;
    }

    const previousTray = previousTrayRef.current;
    const currentTray = route.query.tray;
    if (currentTray && currentTray !== previousTray) {
      if (!previousTray) {
        const activeElement = document.activeElement;
        trayOpenerRef.current = activeElement instanceof HTMLElement && activeElement !== document.body
          ? activeElement
          : null;
      }
      const focusSurface = () => {
        trayFocusTimerRef.current = null;
        if (routeRef.current.query.tray !== currentTray) return;
        workspaceRef.current
          ?.querySelector<HTMLElement>(".packetTray .readerClose, .missionsPanel .readerClose")
          ?.focus({ preventScroll: true });
      };
      trayFocusTimerRef.current = typeof window.requestAnimationFrame === "function"
        ? window.requestAnimationFrame(focusSurface)
        : window.setTimeout(focusSurface, 0);
    } else if (!currentTray && previousTray) {
      const restoreFocus = () => {
        trayFocusTimerRef.current = null;
        const current = routeRef.current.query;
        if (current.tray || current.dock || current.reader) return;
        const opener = trayOpenerRef.current;
        if (opener?.isConnected && !opener.closest("[inert]")) opener.focus({ preventScroll: true });
        else searchRef.current?.focus({ preventScroll: true });
        trayOpenerRef.current = null;
      };
      trayFocusTimerRef.current = typeof window.requestAnimationFrame === "function"
        ? window.requestAnimationFrame(restoreFocus)
        : window.setTimeout(restoreFocus, 0);
    }
    previousTrayRef.current = currentTray;

    return () => {
      const pending = trayFocusTimerRef.current;
      if (pending === null) return;
      window.cancelAnimationFrame?.(pending);
      window.clearTimeout(pending);
      trayFocusTimerRef.current = null;
    };
  }, [route.query.tray]);

  // Canonical page navigation: selecting a page emits query-owned state, while
  // compatibility inputs still retain enough positional context to normalize.
  const canonicalPatch = (patch: WorldPatch): WorldPatch => {
    const current = pendingRouteRef.current;
    const activeView = patch.view && isNativeWorldViewId(patch.view)
      ? patch.view
      : pendingWorldStateRef.current.view;
    const perspective = (patch.perspective ?? activeView ?? current.perspective) as ScenePerspectiveId;
    if (patch.view && patch.view !== current.query.view && patch.group === undefined) {
      patch = { ...patch, group: null, worldGroup: null };
    }
    if (perspective === "quadrants" && typeof patch.group === "string" && patch.group.startsWith("family:")) {
      patch = { ...patch, group: null, worldGroup: patch.group };
    }
    // A perspective switch while a page is locked re-derives the page's group
    // for the NEW perspective, so the positional URL never degenerates.
    if (patch.perspective && patch.pageId === undefined && current.pageId) {
      patch = { ...patch, pageId: current.pageId };
    }
    if (typeof patch.pageId !== "string") return patch;
    const page = findPage(pages, patch.pageId);
    if (!page) return patch;
    return {
      ...patch,
      pageId: page.id,
      context: page.context || "system",
      // A quadrant family is an explicit density-reduction step, not a page's
      // canonical location. Opening a real page from the quadrant root must
      // therefore not invent `family:<type>` (which produced empty technical
      // collections and false breadcrumbs). An already-open collection stays
      // in the base route; other perspectives still derive their real group.
      ...(perspective === "quadrants"
        ? {}
        : { group: isEgoPerspective(perspective) ? null : groupKeyForPage(perspective, page) ?? null })
    };
  };
  const canonicalV8Route = (base: WorldRoute, patch: WorldPatch) => {
    const queryPatch: WorldPatch = {
      ...patch,
      // In native v8, selected page and family group live in query state. Keep
      // the compatibility positional fields synchronized only as an input to
      // hydration; the emitted URL remains the single `/w?...` grammar.
      ...(patch.pageId !== undefined ? { page: patch.pageId } : {}),
      ...(patch.worldGroup === undefined && patch.group !== undefined ? { worldGroup: patch.group } : {})
    };
    return navigation.patch(base, queryPatch);
  };
  const canonicalV8State = (patchedRoute: WorldRoute) => hydrateWorldRoute({
    route: patchedRoute,
    pages: worldRuntime.pages,
    rootId: rootAnchor(bundle)?.id ?? pendingWorldStateRef.current.centerId,
    emptyWorld: pendingWorldStateRef.current.emptyWorld,
    kernel: worldRuntime.kernel,
    mode: "v8"
  });
  const navigateWorld = (patch: WorldPatch, options: { replace?: boolean } = {}) => {
    const resolvedPatch = canonicalPatch(patch);
    const currentRoute = pendingRouteRef.current;
    if (resolvedPatch.reader === true && !currentRoute.query.reader) {
      readerOpenerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    }
    // Every action inside a native v8 view — not only the view buttons — uses
    // one canonical query grammar. Selection, reader, dock, filter, packet and
    // fallback links can therefore never reintroduce `/w/quadrants/...` while
    // the effective view is Sources or Work.
    const nativeView = typeof resolvedPatch.view === "string" && isNativeWorldViewId(resolvedPatch.view)
      ? resolvedPatch.view
      : pendingWorldStateRef.current.view;
    if (pendingWorldStateRef.current.mode === "v8" && isNativeWorldViewId(nativeView)) {
      const patchedRoute = canonicalV8Route(currentRoute, resolvedPatch);
      const canonicalState = canonicalV8State(patchedRoute);
      const target = canonicalWorldUrl(canonicalState, currentRoute.demo, patchedRoute.query);
      pendingWorldStateRef.current = canonicalState;
      pendingRouteRef.current = navigation.toWorld(navigation.parseUrl(target));
      navigation.dispatch({
        type: "navigate",
        target,
        replace: options.replace
      });
      return;
    }
    const patchedRoute = navigation.patch(currentRoute, resolvedPatch);
    pendingRouteRef.current = patchedRoute;
    pendingWorldStateRef.current = hydrateWorldRoute({
      route: patchedRoute,
      pages: worldRuntime.pages,
      rootId: rootAnchor(bundle)?.id ?? pendingWorldStateRef.current.centerId,
      emptyWorld: pendingWorldStateRef.current.emptyWorld,
      kernel: worldRuntime.kernel,
      mode: pendingWorldStateRef.current.mode
    });
    navigation.dispatch({
      type: "navigate",
      target: navigation.href(patchedRoute),
      replace: options.replace
    });
  };
  const makeHref = (patch: ScenePatch) => {
    const resolvedPatch = canonicalPatch(patch as WorldPatch);
    const nativeView = typeof resolvedPatch.view === "string" && isNativeWorldViewId(resolvedPatch.view)
      ? resolvedPatch.view
      : pendingWorldStateRef.current.view;
    const currentRoute = pendingRouteRef.current;
    if (pendingWorldStateRef.current.mode === "v8" && isNativeWorldViewId(nativeView)) {
      const patchedRoute = canonicalV8Route(currentRoute, resolvedPatch);
      return canonicalWorldUrl(canonicalV8State(patchedRoute), currentRoute.demo, patchedRoute.query);
    }
    return navigation.hrefForPatch(currentRoute, resolvedPatch);
  };
  const visualWorkspaceStyle = useMemo(
    () => ({
      "--visual-glow": String(visualConfig.glow),
      "--visual-contrast": String(visualConfig.contrast),
      "--visual-density": String(visualConfig.density),
      "--visual-spacing": String(visualConfig.spacing),
      "--visual-motion": String(visualConfig.motion),
      "--visual-ui-scale": String(visualConfig.uiScale),
      "--visual-glass": String(visualConfig.glass),
      ...motionCssVariables(visualConfig.motion)
    }) as CSSProperties,
    [visualConfig]
  );

  const releaseOverlayResolve = useCallback(() => {
    if (overlayResolveTimerRef.current === null && !overlayResolvingRef.current) return;
    if (overlayResolveTimerRef.current !== null) window.clearTimeout(overlayResolveTimerRef.current);
    overlayResolveTimerRef.current = null;
    overlayResolvingRef.current = false;
    setOverlayResolving(false);
  }, []);

  const changeOverlay = (nextOverlay: OverlayId) => {
    if (nextOverlay === worldRuntime.getState().overlay || overlayResolvingRef.current) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const duration = overlayResolveDurationMs(visualConfig.motion, reduced);
    overlayResolvingRef.current = duration > 0;
    setOverlayResolving(duration > 0);
    dispatchRuntime({ type: "setOverlay", overlay: nextOverlay });
    if (overlayResolveTimerRef.current !== null) window.clearTimeout(overlayResolveTimerRef.current);
    if (duration > 0) {
      overlayResolveTimerRef.current = window.setTimeout(() => {
        releaseOverlayResolve();
      }, duration);
    }
  };

  useEffect(() => {
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const cutIfReduced = () => {
      if (visualConfig.motion <= 0 || media?.matches) releaseOverlayResolve();
    };
    cutIfReduced();
    media?.addEventListener?.("change", cutIfReduced);
    return () => media?.removeEventListener?.("change", cutIfReduced);
  }, [releaseOverlayResolve, visualConfig.motion]);

  useEffect(() => () => {
    if (overlayResolveTimerRef.current !== null) window.clearTimeout(overlayResolveTimerRef.current);
    overlayResolveTimerRef.current = null;
    overlayResolvingRef.current = false;
  }, []);

  // Docks are siblings of the world workspace in App. Mirror only the shared
  // motion grammar to :root so those surfaces honor the same user speed/off
  // choice without leaking the rest of the visual tuning outside the world.
  useEffect(() => {
    const root = document.documentElement;
    const variables = motionCssVariables(visualConfig.motion);
    const previous = new Map<string, string>();
    Object.entries(variables).forEach(([name, value]) => {
      previous.set(name, root.style.getPropertyValue(name));
      root.style.setProperty(name, value);
    });
    return () => {
      previous.forEach((value, name) => {
        if (value) root.style.setProperty(name, value);
        else root.style.removeProperty(name);
      });
    };
  }, [visualConfig.motion]);

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
    if (route.perspective === "quadrants") return Boolean(parseRealFamilyGroupId(segment));
    return false;
  };

  // AUTO-DRILL + pin: any off-level selection (search result, wiki-link,
  // packet item, legacy alias, hand-typed URL) canonicalizes the URL to the
  // page's level — the silent no-op is banned.
  useEffect(() => {
    // Every query-owned route keeps selection and reader state in `?page=` —
    // including an explicit `runtime=compat` normalization of an old link.
    // Auto-drill repairs only positional inputs; applying it to a canonical
    // query would recreate context/group fields the writer intentionally no
    // longer emits and could loop on every hydration.
    if (route.query.view) return;
    // A trailing segment that is actually a page id (typed/legacy URLs) is
    // re-read as the locked page, never dropped.
    if (!route.pageId && route.group && !knownGroupKey(route.group)) {
      const page = findPage(pages, route.group);
      if (page) {
        navigation.dispatch({ type: "patch-world", route, patch: canonicalPatch({ pageId: page.id, reader: route.query.reader }), replace: true });
        return;
      }
    }
    if (!route.pageId) return;
    const page = findPage(pages, route.pageId);
    if (!page) return;
    const context = page.context || "system";
    const group = isEgoPerspective(route.perspective) ? undefined : groupKeyForPage(route.perspective, page);
    if (route.context !== context || (!isEgoPerspective(route.perspective) && route.group !== group)) {
      navigation.dispatch({ type: "patch-world", route, patch: { context, group: group ?? null }, replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pages, route, worldState.mode]);

  // Selecting a page opens a new read: stale evidence-walk highlights and
  // relation isolation from the previous page never leak into this one.
  useEffect(() => {
    setWalk(null);
    setIsolateRelation(null);
    setHoverLinkId(null);
  }, [route.pageId, route.query.reader]);

  // A pageId that does not exist in THIS universe (demo id in the real world,
  // a deleted page after refresh, or a hand-authored bad deep link) cannot own
  // a reader surface. Announce it once, then replace-normalize both page and
  // reader state. `replace` avoids a poisoned Back entry; dropping the raw
  // reader bit from primarySurfaceOpen above keeps the HUD operable even in
  // the single frame before this effect commits.
  const missingNoticeRef = useRef("");
  useEffect(() => {
    const missingPage = Boolean(route.pageId && !selectedPage);
    const orphanReader = Boolean(route.query.reader && !selectedPage);
    if (!missingPage && !orphanReader) {
      missingNoticeRef.current = "";
      return;
    }
    const missingKey = route.pageId || "reader-without-page";
    if (missingPage && missingNoticeRef.current !== missingKey) {
      missingNoticeRef.current = missingKey;
      onNotice?.(t("world.missingInUniverse"));
    }
    navigateWorld({ pageId: null, reader: false }, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pages, route.pageId, route.query.reader, selectedPage]);

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
      if (event.key === "?") openTour();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openTour]);

  useEffect(() => {
    try {
      window.localStorage.setItem(VISUAL_CONTROL_STORAGE_KEY, JSON.stringify(visualConfig));
    } catch {
      /* private mode — session-only */
    }
  }, [visualConfig]);

  // Search field mirrors ?q= (deep-linkable transient state).
  useEffect(() => {
    setSearchDraft(route.query.q);
  }, [route.query.q]);
  useEffect(() => {
    if (!isVisualControlCommand(searchDraft)) return;
    setVisualPanelOpen(true);
    setSearchDraft("");
    navigateWorld({ q: null, tray: null }, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchDraft]);
  useEffect(() => {
    // Keep the marker for the whole lifetime of the submitted draft. Clearing
    // it as soon as `route.q` commits is too early: under CPU contention a
    // draft effect created before that commit can still flush afterward. A
    // genuine edit moves away from the submitted value and releases it.
    if (submittedSearchRef.current !== null && submittedSearchRef.current !== searchDraft) {
      submittedSearchRef.current = null;
    }
    if (searchDraft === route.query.q) return undefined;
    if (isVisualControlCommand(searchDraft)) return undefined;
    // A direct Enter submission owns this draft. Its one route transaction
    // already wrote `q`, `page`, `reader` and `dock=null`; never let a later
    // debounce reduce that state back to a query-only route.
    if (submittedSearchRef.current === searchDraft) return undefined;
    const timer = window.setTimeout(() => {
      navigateWorld(searchDraft
        ? { q: searchDraft, searchLimit: null, dock: null }
        : {
            q: null,
            searchType: null,
            searchContext: null,
            searchScope: null,
            searchLimit: null,
            dock: null
          }, { replace: true });
    }, 250);
    searchRouteTimerRef.current = timer;
    return () => {
      window.clearTimeout(timer);
      if (searchRouteTimerRef.current === timer) searchRouteTimerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route.query.q, searchDraft]);

  const searchAllowedIds = useMemo(() => {
    if (route.query.searchScope !== "world") return undefined;
    const anchorId = focusAnchorId(bundle, worldState.centerId ?? undefined) ?? rootAnchor(bundle)?.id ?? null;
    const record = anchorRecord(bundle, anchorId ?? undefined);
    const scoped = scopeGraphToCompiledAnchor(bundle.graph, anchorId, record?.derived?.quadrant_assignments);
    const ids = new Set<string>();
    scoped.nodes.forEach((node) => {
      ids.add(node.id);
      ids.add(node.path);
    });
    return ids;
  }, [bundle, route.query.searchScope, worldState.centerId]);
  const searchResult = useMemo(
    () => searchPages(pages, searchDraft, {
      pageType: route.query.searchType || undefined,
      context: route.query.searchContext || undefined,
      allowedIds: searchAllowedIds
    }),
    [pages, route.query.searchContext, route.query.searchType, searchAllowedIds, searchDraft]
  );
  const searchHits = searchResult.hits;
  // Keyboard result navigation resets whenever the query changes.
  useEffect(() => updateActiveHit(0), [
    searchDraft,
    route.query.searchContext,
    route.query.searchScope,
    route.query.searchType,
    updateActiveHit
  ]);
  const visibleHits = searchHits.slice(0, route.query.searchLimit);
  const openHit = (page?: PageRecord, query?: string) => {
    if (page) {
      // Search is a direct read intent and therefore owns the primary-surface
      // slot. Clear any dock in the same route transaction so an adaptive
      // renderer switch cannot replay a stale Create/source surface over the
      // requested reader.
      navigateWorld({
        ...(query === undefined ? {} : { q: query || null }),
        dock: null,
        pageId: page.id,
        reader: true
      });
    }
  };
  const onSearchKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    const currentSearchValue = event.currentTarget.value;
    if (event.key === "Enter" && isVisualControlCommand(currentSearchValue)) {
      event.preventDefault();
      setVisualPanelOpen(true);
      setSearchDraft("");
      navigateWorld({ q: null, tray: null }, { replace: true });
      return;
    }
    const keyboardHits = currentSearchValue === route.query.q
      ? visibleHits
      : searchPages(pages, currentSearchValue, {
          pageType: route.query.searchType || undefined,
          context: route.query.searchContext || undefined,
          allowedIds: searchAllowedIds
        }).hits.slice(0, route.query.searchLimit);
    if (!keyboardHits.length) {
      if (event.key === "Escape") setSearchDraft("");
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      updateActiveHit(Math.min(activeHitRef.current + 1, keyboardHits.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      updateActiveHit(Math.max(activeHitRef.current - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      // Commit search + reader as one route transition. Otherwise the pending
      // debounced `?q=` write can land after the reader navigation and replay a
      // route with no `reader=1`, which is especially visible in canonical v8
      // where page state no longer has a positional-path fallback.
      if (searchRouteTimerRef.current !== null) {
        window.clearTimeout(searchRouteTimerRef.current);
        searchRouteTimerRef.current = null;
      }
      // If the debounce already committed this query, no later draft effect is
      // pending and retaining the marker would suppress a future identical
      // query after the reader closes.
      if (currentSearchValue !== route.query.q) submittedSearchRef.current = currentSearchValue;
      openHit(
        keyboardHits[Math.min(activeHitRef.current, keyboardHits.length - 1)] ?? keyboardHits[0],
        currentSearchValue
      );
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
  const toggleTray = () => {
    navigateWorld({ tray: trayOpen ? null : "packet" });
  };
  const toggleMissions = () => {
    navigateWorld({ tray: missionsOpen ? null : "missions" });
  };

  const refreshAction =
    bundle.actions.actions.find((action) => action.id === "refresh-cockpit-check") ||
    bundle.actions.actions.find((action) => action.id === "graph-check");
  const gateCommand = bundle.actions.actions.find((action) => action.id === "run-honesty-gates");
  const prCommand = bundle.actions.actions.find((action) => action.id === "pr-summary");
  const reviewCommand = bundle.actions.actions.find((action) => action.id === "review-local-changes");

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
      onClick: () => navigation.dispatch({ type: "navigate", target: route.demo ? "/demo/review" : "/review" })
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
      onClick: () => navigateWorld({ view: "radar", filter: "stale", group: null, worldGroup: null }),
      action:
        onComposeBrief && stalePages.length > 0
          ? {
              label: t("mission.stale.fix"),
              title: route.demo ? t("demo.readOnlyControl") : t("mission.stale.fixTitle"),
              disabled: route.demo,
              onClick: route.demo ? undefined : () => onComposeBrief(staleRefreshSpec(stalePages))
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
      onClick: () => navigateWorld({ view: "quadrants", context: null, group: null, worldGroup: null })
    });
  }

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
    () => focusAnchorId(bundle, worldState.centerId ?? undefined) ?? rootAnchor(bundle)?.id ?? null,
    [bundle, worldState.centerId]
  );
  const activeQuadrantAnchor = useMemo(
    () => anchorRecord(bundle, activeQuadrantAnchorId ?? undefined),
    [bundle, activeQuadrantAnchorId]
  );
  const activeCenterHasQuadrants = useMemo(
    () => anchorSupportsQuadrants(activeQuadrantAnchor),
    [activeQuadrantAnchor]
  );
  const runtimePerspective = worldState.view;
  // Timeline is a registered 2D semantic-time view. Keep the existing world
  // mounted underneath for identity/continuity, but never pretend the spatial
  // layout engine owns a temporal geometry it does not implement.
  const spatialPerspective: ScenePerspectiveId = runtimePerspective === "timeline"
    ? "quadrants"
    : runtimePerspective;
  const effectivePerspective: ScenePerspectiveId =
    spatialPerspective === "quadrants" && !activeCenterHasQuadrants ? "focus" : spatialPerspective;
  const activeCommandPerspective = effectivePerspective;
  const activeRegionPayloads = useMemo(() => regionPayloadByKey(activeQuadrantAnchor), [activeQuadrantAnchor]);

  // The AUTHORITATIVE per-page quadrant classification: the compiler's derived
  // quadrant_assignments on the ACTIVE anchor, inverted into a pageId → facet
  // map. Only the explicit center selects the active anchor; an inspected page
  // never changes this map. The scene and compass read THIS. The static
  // page-type map is only the fallback outside the compiled scope.
  const quadrantHomes = useMemo<QuadrantHomes | undefined>(() => {
    return quadrantHomesFromAssignments(activeQuadrantAnchor?.derived?.quadrant_assignments);
  }, [activeQuadrantAnchor]);

  // Every native view receives the same graph for the ACTIVE local world. A
  // view is a stable spatial projection, never a request to swap the data
  // under the canvas. Once the compiler emits quadrant assignments for an
  // anchor, that scope is authoritative: retain the center plus its exact
  // members instead of leaking unrelated global pages back in through the
  // page-type fallback. Legacy/bare snapshots without assignments continue to
  // receive the complete canonical graph.
  const runtimeSceneGraph = useMemo(
    () => scopeGraphToCompiledAnchor(
      bundle.graph,
      activeQuadrantAnchorId,
      activeQuadrantAnchor?.derived?.quadrant_assignments
    ),
    [activeQuadrantAnchor, activeQuadrantAnchorId, bundle.graph]
  );
  const centerableIds = useMemo(
    () => new Set(
      Object.entries(bundle.blockStacks?.anchors ?? {})
        .filter(([, record]) => anchorSupportsQuadrants(record))
        .map(([pageId]) => pageId)
    ),
    [bundle.blockStacks]
  );

  // Quadrant lens: live per-quadrant home counts (+ the honest core) for the
  // active center. It is independent from the base view, so Q1–Q4 can focus
  // Radar, Sources and Work without silently switching the world to Quadrants.
  const quadrantCounts = useMemo(() => {
    const counts = new Map<SceneFacet, number>(SCENE_FACETS.map((facet) => [facet, 0]));
    let core = 0;
    runtimeSceneGraph.nodes.forEach((node) => {
      if (node.id === activeQuadrantAnchorId) return;
      const home = nodeQuadrant(node.id, node.page_type, quadrantHomes);
      if (home) counts.set(home, (counts.get(home) ?? 0) + 1);
      else core += 1;
    });
    return { quadrants: SCENE_FACETS.map((facet) => ({ facet, count: counts.get(facet) ?? 0, region: activeRegionPayloads.get(facet) })), core };
  }, [activeQuadrantAnchor, activeQuadrantAnchorId, activeRegionPayloads, quadrantHomes, runtimeSceneGraph]);
  const quadrantTotal = useMemo(
    () => quadrantCounts.quadrants.reduce((total, quadrant) => total + quadrant.count, quadrantCounts.core),
    [quadrantCounts]
  );

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
  useEffect(() => {
    if (route.query.tray !== "missions" || instruments.missionsEnabled) return;
    // A route cannot manufacture a surface that the active block stack did
    // not install. Normalize stale/shared links rather than rendering a hidden
    // or empty local state that disagrees with the command bar.
    navigation.dispatch({
      type: "patch-world",
      route,
      patch: { tray: null },
      replace: true
    });
  }, [instruments.missionsEnabled, navigation, route]);

  // Spatial-first routing: the founding rite and the seed flow live IN the
  // canvas; the 2D twins (DOM cards, the bottom sheet) are the declared
  // fallback for reduced-motion / no-WebGL / visual-test mode. LIVE state —
  // it must track the same media signal SystemScene's internal fallback does,
  // or the two branches disagree and no surface renders at all.
  const [environmentFallbackActive, setEnvironmentFallbackActive] = useState(sceneFallbackPreferred);
  const [performanceFallbackActive, setPerformanceFallbackActive] = useState(runtimePerformanceFallbackLatched);
  const [compactViewport, setCompactViewport] = useState(
    () => typeof window !== "undefined" && window.matchMedia?.("(max-width: 620px)").matches === true
  );
  const fallbackActive = environmentFallbackActive || performanceFallbackActive;
  // The three spatial founding cards need desktop camera room. On a compact
  // viewport the equivalent DOM rite is the primary responsive presentation,
  // preserving one action and one truth without overlapping hit regions.
  const foundingFallbackActive = fallbackActive || (instruments.worldEmpty && compactViewport);
  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const compact = window.matchMedia?.("(max-width: 620px)");
    const updateEnvironment = () => setEnvironmentFallbackActive(sceneFallbackPreferred());
    const updateCompact = () => setCompactViewport(compact?.matches === true);
    const activatePerformanceFallback = () => setPerformanceFallbackActive(true);
    media?.addEventListener?.("change", updateEnvironment);
    compact?.addEventListener?.("change", updateCompact);
    window.addEventListener(RUNTIME_PERFORMANCE_FALLBACK_EVENT, activatePerformanceFallback);
    window.addEventListener("popstate", updateEnvironment);
    return () => {
      media?.removeEventListener?.("change", updateEnvironment);
      compact?.removeEventListener?.("change", updateCompact);
      window.removeEventListener(RUNTIME_PERFORMANCE_FALLBACK_EVENT, activatePerformanceFallback);
      window.removeEventListener("popstate", updateEnvironment);
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
      if (visualPanelOpen) {
        event.stopImmediatePropagation();
        event.stopPropagation();
        setVisualPanelOpen(false);
        return;
      }
      if (worldNavigatorOpen) {
        event.stopImmediatePropagation();
        event.stopPropagation();
        setWorldNavigatorOpen(false);
        return;
      }
      if (trayOpen || missionsOpen) {
        event.stopImmediatePropagation();
        event.stopPropagation();
        navigation.dispatch({
          type: "patch-world",
          route: routeRef.current,
          patch: { tray: null }
        });
        return;
      }
      const current = routeRef.current;
      if (current.query.reader) {
        event.stopImmediatePropagation();
        event.stopPropagation();
        navigation.dispatch({
          type: "patch-world",
          route: current,
          patch: { reader: false }
        });
        return;
      }
      if (current.query.dock) {
        event.stopImmediatePropagation();
        event.stopPropagation();
        navigation.dispatch({
          type: "patch-world",
          route: current,
          patch: {
            dock: null,
            src: null,
            lens: current.query.dock === "create" ? null : undefined,
            quadrant: current.query.dock === "create" ? null : undefined
          }
        });
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [trayOpen, missionsOpen, visualPanelOpen, worldNavigatorOpen]);

  // An EMPTY world has exactly one interface: the founding rite. A dock in the
  // URL there (deep link, stale history) would open a surface over nothing.
  useEffect(() => {
    if (instruments.worldEmpty && route.query.dock) {
      navigation.dispatch({ type: "patch-world", route, patch: { dock: null, src: null }, replace: true });
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
          readOnly: route.demo && !route.query.genesis,
          initialType: route.query.src || undefined,
          onSeed: (spec) => onComposeBrief?.(spec),
          onCancel: () => navigateWorld({ dock: null, src: null, lens: null, quadrant: null }),
          onPreviewQuadrant: (facet) => setPreviewQuadrant(SCENE_FACETS.includes(facet as SceneFacet) ? (facet as SceneFacet) : null)
        }
      : null;

  // R5 — the tutorial guide, anchored to each stage's subject. Present before,
  // during and after the action; Back/Skip live on the beacon itself. Demo
  // only — a stray ?genesis=1 on a real wiki must not summon the simulation.
  const goStage = (stage: number) => navigation.dispatch({ type: "navigate", target: genesisUrl(stage, { visual: route.query.visual }) });
  const skipHref = demoWorldUrl({ visual: route.query.visual });
  const guideData = route.demo && route.query.genesis ? genesisGuide(route.query.stage) : null;
  const handleQuadrantSelect = (facet: SceneFacet) => {
    const canonicalLens = facet === "intencao" ? "q1_intencao" : facet === "pratica" ? "q2_pratica" : facet === "relacoes" ? "q3_relacoes" : "q4_sistemas";
    const active = worldState.lens === canonicalLens;
    setPreviewQuadrant(null);
    if (active) {
      dispatchRuntime({ type: "setLens", lens: "all" });
      return;
    }
    dispatchRuntime({ type: "setLens", lens: canonicalLens });
    if (route.demo && route.query.genesis && genesisQuadrantMatches(route.query.stage, facet)) {
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
  // platform constant: only a bare entry URL normalizes to the stack's
  // default. Explicit compatibility deep links remain addressable even when
  // the template does not advertise them as navigation buttons — discovery
  // and route validity are separate contracts.
  useEffect(() => {
    if (route.query.lens) setPreviewQuadrant(null);
  }, [route.query.lens]);

  useEffect(() => {
    // The positional perspective is only a compatibility reader once a v8
    // query view is explicit. Rewriting it here would turn the canonical
    // `/w?view=radar` writer back into the conflicting
    // `/w/quadrants?view=radar` double grammar.
    if (worldState.mode === "v8" && route.query.view) return;
    // Positional `/w/radar`, `/w/atlas`, `/w/districts`, ... URLs are the
    // supported legacy reader grammar. Their registered view/lens/overlay
    // mapping must win over the current template's discoverable-view list.
    if (route.perspectiveExplicit) return;
    // Applies to the EMPTY world too: before any lens exists there is no
    // quadrant map — the frame materializes only when the block attaches.
    if (!instruments.perspectives.includes(route.perspective) && route.perspective !== "focus") {
      navigation.dispatch({ type: "patch-world", route, patch: { perspective: instruments.defaultPerspective }, replace: true });
      return;
    }
    if (!route.perspectiveExplicit && route.perspective !== instruments.defaultPerspective) {
      navigation.dispatch({ type: "patch-world", route, patch: { perspective: instruments.defaultPerspective }, replace: true });
    }
  }, [instruments, route, worldState.mode]);

  // Breadcrumbs: URL-derived, every segment clickable, registry labels.
  const realFamilyGroup = effectivePerspective === "quadrants" ? parseRealFamilyGroupId(route.query.worldGroup) : null;
  const sourceFlowCollection = effectivePerspective === "sources" && worldState.group === "family:source"
    ? { key: "family:source", kind: "source_flow", labelKey: "emitters" } as const
    : null;
  const sceneGroup: string | undefined = effectivePerspective === "quadrants"
    ? realFamilyGroup?.key
    : sourceFlowCollection?.key ?? route.group;
  const previewQuadrantFacet =
    SCENE_FACETS.includes(previewQuadrant as SceneFacet) ? previewQuadrant : null;
  const runtimeQuadrantFacet: SceneFacet | null =
    worldState.lens === "q1_intencao" ? "intencao" :
    worldState.lens === "q2_pratica" ? "pratica" :
    worldState.lens === "q3_relacoes" ? "relacoes" :
    worldState.lens === "q4_sistemas" ? "sistemas" : null;
  const selectedQuadrantFacet = runtimeQuadrantFacet;
  const activeQuadrantFacet = (previewQuadrantFacet || selectedQuadrantFacet) as SceneFacet | null;
  const cameraQuadrantFacet = runtimeQuadrantFacet ?? undefined;
  const familyMembers = useMemo(() => {
    if (!realFamilyGroup) return [];
    const ids = new Set(
      runtimeSceneGraph.nodes
        .filter((node) => node.id !== activeQuadrantAnchorId)
        .filter((node) => !runtimeQuadrantFacet || nodeQuadrant(node.id, node.page_type, quadrantHomes) === runtimeQuadrantFacet)
        .filter((node) => pageTypeStyle(node.page_type).family === realFamilyGroup.family)
        .map((node) => node.id)
    );
    return pages
      .filter((page) => ids.has(page.id))
      .sort((a, b) => a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
  }, [activeQuadrantAnchorId, pages, quadrantHomes, realFamilyGroup, runtimeQuadrantFacet, runtimeSceneGraph.nodes]);
  const sourceFlowMembers = useMemo(() => {
    if (!sourceFlowCollection) return [];
    const ids = new Set(
      runtimeSceneGraph.nodes
        .filter((node) => isSourceEmitterType(node.page_type))
        .map((node) => node.id)
    );
    return pages
      .filter((page) => ids.has(page.id))
      .sort((a, b) => a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
  }, [pages, runtimeSceneGraph.nodes, sourceFlowCollection]);
  const semanticCollection = realFamilyGroup
    ? { key: realFamilyGroup.key, kind: "family", labelKey: realFamilyGroup.family, facet: runtimeQuadrantFacet ?? "all", members: familyMembers }
    : sourceFlowCollection
      ? { ...sourceFlowCollection, facet: "all", members: sourceFlowMembers }
      : null;
  const centeredRealPage =
    activeQuadrantAnchorId
      ? findPage(pages, activeQuadrantAnchorId)
      : undefined;
  const crumbs: { label: string; patch: WorldPatch }[] = [
    { label: t("world.galaxy"), patch: { context: null, group: null, pageId: null, reader: false } }
  ];
  if (route.context) crumbs.push({ label: contextLabel(route.context), patch: { group: null, pageId: null, reader: false } });
  if (centeredRealPage) {
    crumbs.push({
      label: centeredRealPage.title,
      patch: { center: centeredRealPage.id, group: null, worldGroup: null, pageId: null, reader: false }
    });
  }
  if (sceneGroup && !isEgoPerspective(route.perspective)) {
    if (realFamilyGroup) {
      if (runtimeQuadrantFacet) {
        crumbs.push({
          label: t(`facet.${runtimeQuadrantFacet}`),
          patch: { lens: worldState.lens, group: null, worldGroup: null, pageId: null, reader: false }
        });
      }
      crumbs.push({ label: worldGroupLabel("family", realFamilyGroup.family), patch: { pageId: null, reader: false } });
    } else if (sourceFlowCollection) {
      crumbs.push({
        label: t("world.view.sources"),
        patch: { view: "sources", group: null, worldGroup: null, pageId: null, reader: false }
      });
      crumbs.push({
        label: worldGroupLabel(sourceFlowCollection.kind, sourceFlowCollection.labelKey),
        patch: { pageId: null, reader: false }
      });
    } else {
      const groupKind = route.perspective === "districts" ? "page_type" : route.perspective === "atlas" ? "hub" : "attention";
      crumbs.push({ label: worldGroupLabel(groupKind, sceneGroup), patch: { pageId: null, reader: false } });
    }
  }
  if (selectedPage && selectedPage.id !== centeredRealPage?.id) crumbs.push({ label: selectedPage.title, patch: {} });

  const navigatorView = isNativeWorldViewId(worldState.view) ? worldState.view : null;
  const compatibilityNavigatorView = navigatorView
    ? undefined
    : { id: worldState.view, ...perspectiveLabel(worldState.view) };
  const activeViewLabel = navigatorView
    ? t(`world.view.${navigatorView}`)
    : compatibilityNavigatorView?.label ?? worldState.view;
  const activeViewHint = navigatorView
    ? t(`world.experience.view.${navigatorView}.description`)
    : compatibilityNavigatorView?.hint ?? "";

  const sceneRoute = {
    perspective: effectivePerspective,
    runtimeMode: worldState.mode,
    view: worldState.view,
    context: route.context,
    group: sceneGroup,
    pageId: route.pageId,
    centerId: activeQuadrantAnchorId ?? worldState.centerId ?? undefined,
    reader: route.query.reader,
    filter: route.query.filter,
    lens: cameraQuadrantFacet
  };

  return (
    <main
      ref={workspaceRef}
      tabIndex={-1}
      className={[
        "worldWorkspace",
        `visualLabels-${visualConfig.labels}`,
        visualConfig.particles ? "" : "visualParticlesOff",
        visualPanelOpen ? "visualControlOpen" : "",
        worldNavigatorOpen ? "worldNavigatorOpen" : "",
        semanticCollection ? "familyDrillOpen" : ""
      ].filter(Boolean).join(" ")}
      style={visualWorkspaceStyle}
      aria-label={t("world.aria")}
      data-runtime-mode={worldState.mode}
      data-world-empty={worldState.emptyWorld ? "true" : "false"}
      data-primary-surface-open={primarySurfaceOpen ? "true" : "false"}
      data-world-center={worldState.centerId ?? undefined}
      data-world-view={worldState.view}
      data-world-page-count={pages.length}
      data-world-lens={worldState.lens}
      data-world-overlay={worldState.overlay}
      data-pack-view={route.query.packView || undefined}
      data-world-fallback-active={fallbackActive ? "true" : "false"}
      data-visual-motion={visualConfig.motion.toFixed(2)}
      data-runtime-warnings={worldState.warnings.map((warning) => warning.code).join(",")}
    >
      <Suspense fallback={<div className="sceneLoading" role="status">{t("world.loading")}</div>}>
      <SystemScene
        nodes={runtimeSceneGraph.nodes}
        overlay={worldState.overlay}
        sourceNodeCount={bundle.graph.nodes.length}
        edges={runtimeSceneGraph.edges}
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
        suspended={temporalViewActive || packSurfaceActive}
        visualTuning={visualConfig}
        bornPageIds={bornPageIds}
        missionMarkers={missionMarkers}
        flyToPageId={flyToPageId}
        anchorInfo={anchorInfo}
        activeAnchorRecord={activeQuadrantAnchor}
        centerHasQuadrants={activeCenterHasQuadrants}
        centerableIds={centerableIds}
        quadrantHomes={quadrantHomes}
        founding={foundingFallbackActive ? null : founding}
        seed={fallbackActive ? null : seed}
        guide={fallbackActive ? null : guide}
        onMarkerResolve={
          !route.demo && onComposeBrief
            ? (pageId) => {
                const mission = missions.find((entry) => entry.pageId === pageId);
                const spec = mission ? missionBriefSpec(mission) : null;
                if (spec) onComposeBrief(spec);
              }
            : undefined
        }
        onMarkerDismiss={(pageId) => setDismissedQuests((prev) => new Set([...prev, pageId]))}
        onNavigate={(patch) => navigateWorld(patch as WorldPatch)}
        onRetreat={() => navigation.dispatch({ type: "retreat-world", route: routeRef.current })}
        onHistoryBack={() => navigation.dispatch({ type: "history-back" })}
        onFocusSearch={() => searchRef.current?.focus()}
        onTogglePacket={togglePacket}
        onRunRefresh={route.demo ? undefined : () => refreshAction && onRun(refreshAction)}
        makeHref={makeHref}
      >
        {/* TOP strip: breadcrumb trail + snapshot age + mode + true total.
            The EMPTY world shows nothing — "0 pages · demo" over the founding
            void is noise, and the founding rite is the only interface. */}
        {!instruments.worldEmpty && (
        <MeasuredWorldTopStrip ariaLabel={t("world.breadcrumbsAria")}>
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
          <WorldNavigator
            registryKernel={worldRuntime.kernel}
            view={navigatorView}
            compatibilityView={compatibilityNavigatorView}
            overlay={worldState.overlay}
            overlayResolving={overlayResolving}
            lens={worldState.lens}
            unavailableViews={temporalGraphAvailable ? [] : ["timeline"]}
            lensAvailable={!temporalViewActive && !packSurfaceActive}
            overlayAvailable={!temporalViewActive && !packSurfaceActive}
            experiencePacks={bundle.experiencePacks}
            activePackView={route.query.packView}
            expanded={worldNavigatorOpen}
            onExpandedChange={setWorldNavigatorOpen}
            onViewChange={(view) => navigateWorld({ view, packView: null })}
            onOverlayChange={changeOverlay}
            onLensChange={(lens) => dispatchRuntime({ type: "setLens", lens })}
            onPackViewChange={(contribution) => {
              setWorldNavigatorOpen(false);
              navigateWorld({ packView: contribution, dock: null, reader: false });
            }}
          />
          {bundle.manifest.compatibility?.state !== "current" && (
            <aside className="snapshotCompatibilityNotice" role="alert">
              <strong>{t("snapshot.compatibility.title")}</strong>
              <span>{t("snapshot.compatibility.body")}</span>
            </aside>
          )}
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
        </MeasuredWorldTopStrip>
        )}

        {semanticCollection && !temporalViewActive && (
          <aside
            className="familyCollectionPanel"
            data-world-group-summary={semanticCollection.key}
            data-world-group-count={semanticCollection.members.length}
            data-world-group-facet={semanticCollection.facet}
            aria-label={worldGroupLabel(semanticCollection.kind, semanticCollection.labelKey)}
          >
            <header>
              <strong>{worldGroupLabel(semanticCollection.kind, semanticCollection.labelKey)}</strong>
              <span>{t("group.collection.count", { n: semanticCollection.members.length })}</span>
            </header>
            <p>{worldGroupDescription(semanticCollection.kind, semanticCollection.labelKey)}</p>
            <div className="familyCollectionExamples">
              <small>{t("group.collection.examples")}</small>
              {semanticCollection.members.slice(0, 3).map((page) => {
                const recenters = centerableIds.has(page.id) && page.id !== worldState.centerId;
                return (
                  <button
                    key={page.id}
                    data-world-member-id={page.id}
                    title={page.title}
                    onClick={() => navigateWorld(
                      recenters
                        ? { center: page.id, lens: "all", group: null, worldGroup: null, pageId: null, reader: false }
                        : { pageId: page.id, reader: true }
                    )}
                    type="button"
                  >
                    <strong>{page.title}</strong>
                    <span>{pageTypeLabel(page.page_type)}</span>
                  </button>
                );
              })}
            </div>
          </aside>
        )}

        {/* FOCUS legend: the four lenses with live counts. An empty lens is an
            honest absence — labelled "no X lens registered" with an offer to
            fill it (agent adds a real relation only if one exists). */}
        {focusFacets && selectedPage && !temporalViewActive && !packSurfaceActive && (
          <div className="focusLegend" role="region" aria-label={t("focus.legend")}>
            <span className="focusLegendTitle">{t("focus.legend")}</span>
            {focusFacets.map(({ facet, count }) => {
              const label = t(`facet.${facet}`);
              return (
                <div key={facet} className={count === 0 ? "focusLens empty" : "focusLens"}>
                  <strong>{label}</strong>
                  {count === 0 ? (
                    !route.demo && onComposeBrief ? (
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

        {/* LEFT mission surface. Collapsed by choice it is a single honest
            chip (worst tone + pending count) — the world stays visible;
            expanded it is the do-now card. Search results always render:
            the keyboard search flow must never depend on the card state.
            It precedes the compass so the fallback flow has the same semantic
            order as the layered HUD: context, mission, then navigation. */}
        {(!temporalViewActive && !packSurfaceActive || Boolean(searchDraft)) && <MissionCard
          rows={missionRows}
          viewLabel={activeViewLabel}
          viewHint={activeViewHint}
          viewBadge={compatibilityNavigatorView ? t("world.experience.compatibility.badge") : undefined}
          overlayLabel={t(`world.overlay.${worldState.overlay}`)}
          missionsEnabled={!temporalViewActive && !packSurfaceActive && instruments.missionsEnabled}
          open={missionCardOpen}
          onToggle={() => {
            setMissionCardOpen((open) => {
              persistMissionCard(!open);
              return !open;
            });
          }}
          query={searchDraft}
          searchHits={searchHits}
          visibleHits={visibleHits}
          activeHit={activeHit}
          searchType={route.query.searchType}
          searchContext={route.query.searchContext}
          searchScope={route.query.searchScope}
          searchPageTypes={searchResult.pageTypes}
          searchContexts={searchResult.contexts}
          onActiveHit={updateActiveHit}
          onOpenHit={openHit}
          onSearchFilter={(patch) => navigateWorld({ ...patch, searchLimit: null })}
          onShowMore={() => navigateWorld({ searchLimit: Math.min(1000, route.query.searchLimit + SEARCH_VISIBLE) })}
        />}

        {packSurfaceActive && (
          <Suspense fallback={<div className="timelineLoading" role="status">{t("world.loading")}</div>}>
            <PackWorkbench
              composition={bundle.experiencePacks}
              requestedView={route.query.packView}
              activeView={activePackView}
              pages={pages}
              inactive={primarySurfaceOpen || worldNavigatorOpen}
              onSelectView={(contribution) => navigateWorld({ packView: contribution })}
              onOpenPage={(pageId) => navigateWorld({ pageId, page: pageId, reader: true })}
              onOpenTimeline={() => navigateWorld({ packView: null, view: "timeline", timeCursor: null })}
              onClose={() => navigateWorld({ packView: null })}
            />
          </Suspense>
        )}

        {temporalViewActive && temporalGraph && (
          <Suspense fallback={<div className="timelineLoading" role="status">{t("world.loading")}</div>}>
            <TimelineView
              payload={temporalGraph}
              pages={pages}
              query={route.query}
              experiencePacks={bundle.experiencePacks}
              packTimelineProfiles={bundle.experiencePacks?.slots.timelines}
              inactive={primarySurfaceOpen || worldNavigatorOpen}
              onQueryChange={(patch) => navigateWorld(patch)}
              onOpenPage={(pageId) => navigateWorld({ pageId, page: pageId, reader: true })}
            />
          </Suspense>
        )}
        {temporalViewActive && temporalGraphAvailable && !temporalGraph && !temporalGraphError && (
          <div className="timelineLoading" role="status">{t("timeline.loading")}</div>
        )}
        {temporalViewActive && temporalGraphError && (
          <section
            className="timelineSurface timelineUnavailable"
            role="alert"
            aria-labelledby="timeline-load-error-heading"
            data-temporal-error-code={temporalGraphErrorCode}
          >
            <div>
              <span className="timelineEyebrow">{t("timeline.eyebrow")}</span>
              <h2 id="timeline-load-error-heading">{t("timeline.loadError.title")}</h2>
              <p>{t("timeline.loadError.body")}</p>
              <span className="timelineErrorCode">{t(`timeline.loadError.code.${temporalGraphErrorCode || "unknown"}`)}</span>
              <code>{temporalGraphError}</code>
              {temporalGraphErrorCode !== "unsupported" && (
                <button
                  type="button"
                  onClick={() => setTemporalResource({ snapshotId: temporalSnapshotId, payload: undefined, error: "", code: "" })}
                >
                  <RotateCcw size={15} aria-hidden="true" /> {t("timeline.loadError.retry")}
                </button>
              )}
            </div>
          </section>
        )}
        {temporalViewActive && !temporalGraphAvailable && (
          <section className="timelineSurface timelineUnavailable" role="alert" aria-labelledby="timeline-unavailable-heading">
            <div>
              <span className="timelineEyebrow">{t("timeline.eyebrow")}</span>
              <h2 id="timeline-unavailable-heading">{t("timeline.unavailable.title")}</h2>
              <p>{t("timeline.unavailable.body")}</p>
            </div>
          </section>
        )}

        {/* QUADRANT compass: each cell selects a conceptual lens and moves the
            camera inside the same 3D world. Counts are honest home-quadrant
            totals + core; no quadrant cell is a replacement center object. */}
        {quadrantCounts && activeCenterHasQuadrants && !temporalViewActive && (
          <div
            className={[
              "quadrantCompass",
              "quadrantCompassApprovedTextOnly",
              effectivePerspective !== "quadrants" ? "crossViewMode" : "",
              selectedQuadrantFacet ? "drillMode" : "",
              realFamilyGroup ? "familyDrillMode" : ""
            ].filter(Boolean).join(" ")}
            role="group"
            aria-label={t("world.quadrantCompassAria")}
          >
            <div className="quadrantGrid quadrantTextGrid">
              {quadrantCounts.quadrants.map(({ facet, count, region }) => {
                const facetLabel = t(`facet.${facet}`);
                const aqalText = quadrantAqalText(facet);
                const total = count;
                const instrumentLabel = quadrantInstrumentLabel(facetLabel, total, region);
                return (
                  <button
                    key={facet}
                    className={[
                      "quadrantTextCell",
                      `quadrantTextCell-${facet}`,
                      selectedQuadrantFacet === facet ? "active" : "",
                      activeQuadrantFacet === facet && selectedQuadrantFacet !== facet ? "preview" : "",
                      region?.attention_hints.length ? "hasAttention" : "",
                      region?.summary.raw ? "hasRaw" : ""
                    ].filter(Boolean).join(" ")}
                    onClick={() => handleQuadrantSelect(facet)}
                    title={instrumentLabel}
                    type="button"
                    data-wilber-quadrant={SCENE_FACETS.indexOf(facet) + 1}
                    aria-pressed={selectedQuadrantFacet === facet}
                    aria-label={instrumentLabel.replace(/\n/g, ". ")}
                  >
                    <span className="quadrantAreaDot" style={quadrantHealthStyle(region, count)} aria-hidden />
                    <span className="quadrantAreaCopy">
                      <strong>{aqalText.mark}</strong>
                      <span className="quadrantAqalPosition">{aqalText.position}</span>
                      <small>{facetLabel} · {total}</small>
                    </span>
                    {region?.action_hints[0] && <span className="quadrantAreaAction">{region.action_hints[0].count}</span>}
                    {region && (
                      <span className="quadrantHoverPanel" role="tooltip">
                        <strong>{t(`facet.${facet}`)}</strong>
                        <small>
                          {total === 1 ? "1 page" : `${total} pages`}
                          {region.summary.total !== total ? ` · ${t("quadrant.instrument.classified", { n: region.summary.total })}` : ""}
                          {region.summary.hidden > 0 ? ` · ${region.summary.hidden} hidden` : ""}
                        </small>
                        <span>{t("quadrant.instrument.types", { items: regionTextList(region.type_mix.slice(0, 4), typeMixLabel) })}</span>
                        <span>
                          Attention: {region.attention_hints.length > 0 ? region.attention_hints.slice(0, 4).map((hint) => t(`region.attention.${hint.kind}`, { n: hint.count })).join(", ") : t("region.healthy")}
                        </span>
                        {region.action_hints[0] && <em>Next: {t(region.action_hints[0].label_key, { n: region.action_hints[0].count })}</em>}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
            <div className="quadrantCompassFooter">
              <button
                className={!selectedQuadrantFacet ? "quadrantAll active" : "quadrantAll"}
                type="button"
                aria-pressed={!selectedQuadrantFacet}
                data-quadrant-all
                title={t("world.experience.lens.all.description")}
                onClick={() => dispatchRuntime({ type: "setLens", lens: "all" })}
              >
                <span>{t("world.experience.lens.all.label")}</span>
                <small>{quadrantTotal}</small>
              </button>
              {quadrantCounts.core > 0 && (
                <span className="quadrantCore">{t("quadrant.core")} · {quadrantCounts.core}</span>
              )}
            </div>
            <button
              className="quadrantSeed"
              onClick={() => navigateWorld({ dock: "create", lens: selectedQuadrantFacet, quadrant: null })}
              title={t("create.title")}
              type="button"
            >
              ＋ {t("create.seedHere")}
            </button>
          </div>
        )}

        {/* RIGHT: the in-world reader dock. */}
        {readerPresence.mounted && readerPage && (
          <div
            className={readerPresence.phase === "closing" ? "readerSurfacePresence closing" : "readerSurfacePresence"}
            aria-hidden={readerPresence.phase === "closing" ? true : undefined}
            ref={(target) => {
              if (target) target.inert = readerPresence.phase === "closing";
            }}
            data-surface-phase={readerPresence.phase}
            onAnimationEnd={(event) => {
              if (readerPresence.phase === "closing" && event.currentTarget === event.target) readerPresence.completeExit();
            }}
          >
          <div className="readerDockBackdrop" aria-hidden="true" />
          <Suspense fallback={<aside className="pageReader" role="status">{t("world.readerLoading")}</aside>}>
          <PageReader
            bundle={bundle}
            pageId={readerPage.id}
            demo={route.demo}
            snapshotSource={runtime.snapshotBase}
            loadPageContent={loadPageContent}
            devMode={(runtime.mode || bundle.manifest.mode) === "local_operator" && !route.demo}
            trail={trailPages}
            packetIds={route.query.packet}
            activeCenterId={activeQuadrantAnchorId}
            onNavigatePage={(id) => navigateWorld({ pageId: id, reader: true })}
            onClose={() => navigateWorld(
              effectivePerspective === "quadrants"
                ? { pageId: null, reader: false }
                : { reader: false }
            )}
            onTogglePacket={togglePacket}
            onRunOperatorCommand={onRun}
            onComposeBrief={onComposeBrief}
            onHoverLink={setHoverLinkId}
            onIsolateRelation={setIsolateRelation}
            onEvidenceStep={(ids, step) => setWalk({ ids, step })}
            onSnapshotMismatch={onSnapshotMismatch}
          />
          </Suspense>
          </div>
        )}

        {/* BOTTOM command bar: search, perspective glyphs, packet tray. In an
            EMPTY world there are no instruments yet — the bar itself only
            exists once the root brings the first ones (genesis stage 0 shows
            nothing but the founding prompt). */}
        {!instruments.worldEmpty && (
          <CommandBar
          route={route}
          activePerspective={activeCommandPerspective}
          showCompatibilityPerspectives={worldState.mode !== "v8"}
          instruments={instruments}
            condition={condition}
            changedCount={changed}
            openMissionCount={openMissionCount}
            trayOpen={trayOpen}
            missionsOpen={missionsOpen}
            canComposeBrief={Boolean(onComposeBrief)}
            searchRef={searchRef}
            searchDraft={searchDraft}
            searchExpanded={Boolean(searchDraft)}
            searchResultsId={SEARCH_RESULTS_ID}
            searchActiveDescendant={visibleHits.length > 0 ? searchResultOptionId(Math.min(activeHit, visibleHits.length - 1)) : undefined}
            onSearchDraft={(value) => {
              // Reset synchronously. The result list can sit under the pointer
              // and update activeHit through hover while filters reshape it;
              // waiting for the draft effect would make an immediate keyboard
              // submission inherit that stale pointer position.
              updateActiveHit(0);
              setSearchDraft(value);
            }}
            onSearchKeyDown={onSearchKeyDown}
            onNavigateWorld={navigateWorld}
            onToggleTray={toggleTray}
            onToggleMissions={toggleMissions}
            onOpenTour={openTour}
          />
        )}

        {/* Decision-packet slide-up tray (replaces ImpactBundlePanel). */}
        {trayOpen && (
          <PacketTray
            packetPages={packetPages}
            reviewCommand={reviewCommand}
            gateCommand={gateCommand}
            prCommand={prCommand}
            demo={route.demo}
            onRun={onRun}
            onOpenPage={(id) => navigateWorld({ pageId: id, reader: true })}
            onTogglePacket={togglePacket}
            onClearPacket={() => navigateWorld({ packet: [] }, { replace: true })}
            onClose={() => navigateWorld({ tray: null })}
          />
        )}
        {missionsOpen && instruments.missionsEnabled && (
          <MissionsPanel
            bundle={bundle}
            demo={route.demo}
            onOpenPage={(id) => {
              navigateWorld({ tray: null, pageId: id, reader: true });
            }}
            onComposeBrief={
              onComposeBrief
                ? (spec) => {
                    navigateWorld({ tray: null });
                    onComposeBrief(spec);
                  }
                : undefined
            }
            onClose={() => navigateWorld({ tray: null })}
          />
        )}
        {visualPanelOpen && (
          <VisualControlPanel
            config={visualConfig}
            onConfig={setVisualConfig}
            onReset={() => setVisualConfig(DEFAULT_VISUAL_CONTROL_CONFIG)}
            onClose={() => setVisualPanelOpen(false)}
          />
        )}
      </SystemScene>
      </Suspense>

      {/* The declared 2D fallback of the create flow: the bottom sheet, only
          when the canvas cannot host the spatial seeder. */}
      {seedActive && fallbackActive && (
        <CreateDock
          bundle={bundle}
          initialType={route.query.src}
          initialQuadrant={route.query.lens || route.query.quadrant}
          demo={route.demo}
          genesis={route.query.genesis}
          onComposeBrief={(spec) => onComposeBrief?.(spec)}
          onHighlightQuadrant={(facet) => navigateWorld({ lens: facet, quadrant: null }, { replace: true })}
          onClose={() => navigateWorld({ dock: null, src: null, lens: null, quadrant: null })}
        />
      )}
      {/* 2D twins of the founding rite and the guide beacon (fallback mode). */}
      {foundingFallbackActive && founding && (
        <FoundingFallback demo={route.demo} skipHref={route.demo ? skipHref : undefined} onFound={foundWorld} />
      )}
      {fallbackActive && guide && !founding && <GuideFallback guide={guide} />}
      <CoachMarks
        open={tourOpen}
        returnFocusTo={tourOpenerRef.current}
        onClose={() => setTourOpen(false)}
      />
    </main>
  );
}
