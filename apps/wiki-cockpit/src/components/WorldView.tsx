// WorldView: the 3D-first cockpit shell. The scene IS the navigation surface;
// everything else is a thin HUD fixed to the sceneShell edges — top strip
// (breadcrumbs + snapshot age + honest totals), left mission card, right
// PageReader dock, bottom command bar (search, perspective glyphs, packet
// tray, minimap hint). The old below-the-fold panel stack is gone: every ops
// action is reachable inside the viewport.

import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent } from "react";
import { Copy, RotateCcw, SlidersHorizontal, X } from "lucide-react";
import { t } from "../data/i18n";
import { contextLabel, pageTypeLabel, worldGroupLabel } from "../data/presentation";
import { groupKeyForPage } from "../scene/perspectives";
import { SCENE_FACETS, nodeQuadrant, quadrantHomesFromAssignments, sceneFacetOf } from "../scene/facets";
import type { QuadrantHomes, SceneFacet } from "../scene/facets";
import { parseRealFamilyGroupId } from "../scene/worldState";
import { computeCondition } from "../scene/condition";
import { rankPages } from "../scene/search";
import { canonicalWorldUrl } from "../world/state/routeHydration";
import type { RuntimeEvent } from "../world/contracts";
import type { WorldPatch, WorldRoute } from "../router";
import type { NavigationPort, OperatorPort } from "../application/ports";
import { anchorDeclaresQuadrants, anchorRecord, focusAnchorId } from "../data/blocks";
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
import { MissionCard, SEARCH_VISIBLE } from "./world/MissionCard";
import type { MissionRow } from "./world/MissionCard";
import { PacketTray } from "./world/PacketTray";
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

const SystemScene = lazy(() => import("./SystemScene").then((module) => ({ default: module.SystemScene })));
const PageReader = lazy(() => import("./PageReader").then((module) => ({ default: module.PageReader })));

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
  const total = Math.max(region?.summary.total ?? fallbackCount, 1);
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
    `${facetLabel}: ${t("world.pages", { n: region.summary.total })}`,
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
      setPayloadError("JSON invalido");
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
  const sliders: { key: keyof Pick<VisualControlConfig, "glow" | "contrast" | "density" | "spacing" | "motion" | "uiScale" | "glass">; label: string; min: number; max: number; step: number }[] = [
    { key: "glow", label: "Glow", min: 0.55, max: 1.8, step: 0.05 },
    { key: "contrast", label: "Contrast", min: 0.8, max: 1.35, step: 0.05 },
    { key: "density", label: "Density", min: 0.7, max: 1.35, step: 0.05 },
    { key: "spacing", label: "Spacing", min: 0.72, max: 1.85, step: 0.05 },
    { key: "motion", label: "Motion", min: 0, max: 1.4, step: 0.05 },
    { key: "uiScale", label: "UI scale", min: 0.9, max: 1.12, step: 0.01 },
    { key: "glass", label: "Glass", min: 0.55, max: 1.15, step: 0.05 }
  ];

  return (
    <aside className="visualControlPanel" role="dialog" aria-label="God mode visual controls">
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
          <strong>God mode</strong>
          <small>Live world tuning</small>
        </div>
        <button className="readerClose" onClick={onClose} title="Close visual controls" type="button">
          <X size={14} />
        </button>
      </header>
      <div className="visualControlPresetGrid" role="group" aria-label="Visual presets">
        {Object.entries(VISUAL_CONTROL_PRESETS).map(([name, preset]) => (
          <button key={name} onClick={() => applyConfig(preset)} type="button">
            {name}
          </button>
        ))}
      </div>
      <div className="visualControlGrid">
        {sliders.map((slider) => (
          <label className="visualControlSlider" key={slider.key}>
            <span>
              <b>{slider.label}</b>
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
      <div className="visualControlModes" role="group" aria-label="Label density">
        {(["quiet", "balanced", "dense"] as VisualLabelMode[]).map((mode) => (
          <button
            key={mode}
            className={config.labels === mode ? "active" : ""}
            onClick={() => setLabels(mode)}
            type="button"
          >
            {mode}
          </button>
        ))}
      </div>
      <label className="visualControlToggle">
        <input
          type="checkbox"
          checked={config.particles}
          onChange={(event) => applyConfig({ ...config, particles: event.target.checked })}
        />
        <span>Particle overlays</span>
      </label>
      <textarea
        className={payloadError ? "visualControlOutput invalid" : "visualControlOutput"}
        value={draftPayload}
        aria-label="Visual config JSON"
        spellCheck={false}
        onChange={(event) => {
          setDraftPayload(event.target.value);
          setPayloadDirty(true);
          setPayloadError("");
        }}
      />
      <div className="visualControlPayloadHint" role={payloadError ? "alert" : undefined}>
        {payloadError || "Cole um payload salvo aqui para reaplicar; copie o JSON quando quiser promover como default."}
      </div>
      <label className="visualControlSnippet">
        <span>
          <b>Default snippet</b>
          <small>reviewed code candidate</small>
        </span>
        <textarea
          value={defaultSnippet}
          aria-label="Default visual config snippet"
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
          <RotateCcw size={13} /> Reset
        </button>
        <button className="textButton" disabled={!payloadDirty} onClick={applyDraftPayload} type="button">
          Aplicar JSON
        </button>
        <button className="textButton" onClick={copySnippet} type="button">
          <Copy size={13} /> {copiedSnippet ? "Snippet copied" : "Copy default"}
        </button>
        <button className="primaryButton compact" onClick={copyPayload} type="button">
          <Copy size={13} /> {copied ? "Copied" : "Copy JSON"}
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
  worldRuntime: import("../world/WorldRuntime").WorldRuntime;
  worldState: import("../world/contracts").WorldState;
}) {
  const pages = bundle.pages.pages;
  const dispatchRuntime = (event: RuntimeEvent) => {
    const next = worldRuntime.dispatch(event);
    navigation.dispatch({ type: "navigate", target: canonicalWorldUrl(next, route.demo) });
  };
  // Always navigate from the CURRENT route: async callbacks (debounce timers,
  // scene events) must never replay a stale route and revert navigation.
  const routeRef = useRef(route);
  routeRef.current = route;
  const [searchDraft, setSearchDraft] = useState(route.query.q);
  const [activeHit, setActiveHit] = useState(0);
  const [trayOpen, setTrayOpen] = useState(false);
  const [missionsOpen, setMissionsOpen] = useState(false);
  const [missionCardOpen, setMissionCardOpen] = useState(missionCardPref);
  const [visualPanelOpen, setVisualPanelOpen] = useState(false);
  const [visualConfig, setVisualConfig] = useState<VisualControlConfig>(() =>
    loadVisualControlConfig(typeof window === "undefined" ? undefined : window.localStorage)
  );
  const [previewQuadrant, setPreviewQuadrant] = useState<SceneFacet | null>(null);
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

  // Primary surfaces keep the world visible for context, but the scene and
  // instruments behind them are inert until the surface closes. This is the
  // runtime surface-stack contract, not a per-dock convention.
  useEffect(() => {
    const active = Boolean(worldState.dock || worldState.readerId || route.query.reader);
    const targets = [...document.querySelectorAll<HTMLElement>(".sceneCanvasFrame, .worldTopStrip, .worldCommandBar")];
    for (const target of targets) {
      if (active) {
        target.inert = true;
        target.setAttribute("aria-hidden", "true");
      } else {
        target.inert = false;
        target.removeAttribute("aria-hidden");
      }
    }
    return () => targets.forEach((target) => {
      target.inert = false;
      target.removeAttribute("aria-hidden");
    });
  }, [route.query.reader, worldState.dock, worldState.readerId]);

  // Canonical page navigation: selecting a page ALWAYS emits the full URL
  // (context › group › page), so the positional grammar stays unambiguous and
  // off-level selections auto-drill instead of silently no-oping.
  const canonicalPatch = (patch: WorldPatch): WorldPatch => {
    const current = routeRef.current;
    const perspective = patch.perspective ?? current.perspective;
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
      group: isEgoPerspective(perspective) ? null : groupKeyForPage(perspective, page) ?? null
    };
  };
  const navigateWorld = (patch: WorldPatch, options: { replace?: boolean } = {}) => {
    if (typeof patch.center === "string") worldRuntime.dispatch({ type: "selectCenter", entityId: patch.center });
    if (typeof patch.pageId === "string") {
      worldRuntime.dispatch({ type: "selectEntity", entityId: patch.pageId });
      if (patch.reader) worldRuntime.dispatch({ type: "readEntity", entityId: patch.pageId });
    }
    if (patch.reader === false && !patch.pageId) worldRuntime.dispatch({ type: "closeSurface" });
    if (patch.dock) worldRuntime.dispatch({ type: "openSurface", dock: patch.dock });
    if (patch.dock === null) worldRuntime.dispatch({ type: "closeSurface" });
    navigation.dispatch({
      type: "patch-world",
      route: routeRef.current,
      patch: canonicalPatch(patch),
      replace: options.replace
    });
  };
  const makeHref = (patch: ScenePatch) => navigation.hrefForPatch(route, canonicalPatch(patch as WorldPatch));
  const visualWorkspaceStyle = useMemo(
    () => ({
      "--visual-glow": String(visualConfig.glow),
      "--visual-contrast": String(visualConfig.contrast),
      "--visual-density": String(visualConfig.density),
      "--visual-spacing": String(visualConfig.spacing),
      "--visual-motion": String(visualConfig.motion),
      "--visual-ui-scale": String(visualConfig.uiScale),
      "--visual-glass": String(visualConfig.glass)
    }) as CSSProperties,
    [visualConfig]
  );

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
    setTrayOpen(false);
    setMissionsOpen(false);
    setVisualPanelOpen(true);
    setSearchDraft("");
    navigateWorld({ q: null }, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchDraft]);
  useEffect(() => {
    if (searchDraft === route.query.q) return undefined;
    if (isVisualControlCommand(searchDraft)) return undefined;
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
    const currentSearchValue = event.currentTarget.value;
    if (event.key === "Enter" && isVisualControlCommand(currentSearchValue)) {
      event.preventDefault();
      setTrayOpen(false);
      setMissionsOpen(false);
      setVisualPanelOpen(true);
      setSearchDraft("");
      navigateWorld({ q: null }, { replace: true });
      return;
    }
    const keyboardHits =
      currentSearchValue === route.query.q
        ? visibleHits
        : rankPages(pages, currentSearchValue).slice(0, SEARCH_VISIBLE);
    if (!keyboardHits.length) {
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
      openHit(keyboardHits[activeHit] ?? keyboardHits[0]);
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
  const activeCenterHasQuadrants = useMemo(() => {
    if (selectedPage) return anchorDeclaresQuadrants(anchorRecord(bundle, selectedPage.id));
    return anchorDeclaresQuadrants(activeQuadrantAnchor);
  }, [activeQuadrantAnchor, bundle, selectedPage]);
  const runtimePerspective = worldState.view === "sources" ? "radar" : worldState.view === "work" ? "districts" : worldState.view;
  const effectivePerspective =
    runtimePerspective === "quadrants" && !activeCenterHasQuadrants ? "focus" : runtimePerspective;
  const displayPerspective = runtimePerspective === "quadrants" && !activeCenterHasQuadrants ? "center" : runtimePerspective;
  const activeCommandPerspective = displayPerspective === "center" ? "focus" : runtimePerspective;
  const activeRegionPayloads = useMemo(() => regionPayloadByKey(activeQuadrantAnchor), [activeQuadrantAnchor]);

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
    if (effectivePerspective !== "quadrants" || !assignments || !activeQuadrantAnchorId) {
      return bundle.graph;
    }
    const visibleIds = new Set<string>([activeQuadrantAnchorId]);
    Object.values(assignments).forEach((ids) => ids.forEach((id) => visibleIds.add(id)));
    const selected = route.pageId ? findPage(pages, route.pageId) : null;
    if (selected) {
      visibleIds.add(selected.id);
      bundle.graph.edges.forEach((edge) => {
        if (edge.source === selected.id) visibleIds.add(edge.target);
        if (edge.target === selected.id) visibleIds.add(edge.source);
      });
    }
    const nodes = bundle.graph.nodes.filter((node) => visibleIds.has(node.id));
    const edges = bundle.graph.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target));
    return { nodes, edges };
  }, [activeQuadrantAnchor, activeQuadrantAnchorId, bundle.graph, effectivePerspective, pages, route.pageId]);

  const runtimeSceneGraph = useMemo(() => {
    if (worldState.view !== "sources" && worldState.view !== "work") return quadrantSceneGraph;
    const wantedType = worldState.view === "sources" ? "source" : "action";
    const visibleIds = new Set(
      quadrantSceneGraph.nodes
        .filter((node) => node.id === worldState.centerId || (wantedType === "source" ? node.page_type.startsWith("source") : node.page_type === "action"))
        .map((node) => node.id)
    );
    visibleIds.add(worldState.centerId);
    return {
      nodes: quadrantSceneGraph.nodes.filter((node) => visibleIds.has(node.id)),
      edges: quadrantSceneGraph.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target))
    };
  }, [quadrantSceneGraph, worldState.centerId, worldState.view]);

  // Quadrant compass: live per-quadrant home counts (+ the honest core) for the
  // Quadrants perspective — the 2×2 grid you fly by. Computed from the same
  // classification the layout uses, so it never overstates.
  const quadrantCounts = useMemo(() => {
    if (effectivePerspective !== "quadrants") return null;
    const assignments = activeQuadrantAnchor?.derived?.quadrant_assignments;
    if (assignments) {
      const countWithoutCenter = (ids: string[] | undefined) =>
        (ids ?? []).filter((id) => id !== activeQuadrantAnchorId).length;
      return {
        quadrants: SCENE_FACETS.map((facet) => ({
          facet,
          count: countWithoutCenter(assignments[facet === "intencao" ? "q1" : facet === "pratica" ? "q2" : facet === "relacoes" ? "q3" : "q4"]),
          region: activeRegionPayloads.get(facet)
        })),
        core: countWithoutCenter(assignments.q0_core)
      };
    }
    const counts = new Map<SceneFacet, number>(SCENE_FACETS.map((facet) => [facet, 0]));
    let core = 0;
    bundle.graph.nodes.forEach((node) => {
      if (node.id === activeQuadrantAnchorId) return;
      const home = nodeQuadrant(node.id, node.page_type, quadrantHomes);
      if (home) counts.set(home, (counts.get(home) ?? 0) + 1);
      else core += 1;
    });
    return { quadrants: SCENE_FACETS.map((facet) => ({ facet, count: counts.get(facet) ?? 0, region: activeRegionPayloads.get(facet) })), core };
  }, [effectivePerspective, activeQuadrantAnchor, activeQuadrantAnchorId, activeRegionPayloads, bundle.graph, quadrantHomes]);

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
      if (visualPanelOpen) {
        event.stopImmediatePropagation();
        event.stopPropagation();
        setVisualPanelOpen(false);
        return;
      }
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
  }, [trayOpen, missionsOpen, visualPanelOpen]);

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
    dispatchRuntime({ type: "setView", view: "quadrants" });
    if (!active) dispatchRuntime({ type: "setLens", lens: canonicalLens });
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
    if (effectivePerspective !== "quadrants" || route.query.lens) setPreviewQuadrant(null);
  }, [effectivePerspective, route.query.lens]);

  useEffect(() => {
    // Applies to the EMPTY world too: before any lens exists there is no
    // quadrant map — the frame materializes only when the block attaches.
    if (!instruments.perspectives.includes(route.perspective) && route.perspective !== "focus") {
      navigation.dispatch({ type: "patch-world", route, patch: { perspective: instruments.defaultPerspective }, replace: true });
      return;
    }
    if (!route.perspectiveExplicit && route.perspective !== instruments.defaultPerspective) {
      navigation.dispatch({ type: "patch-world", route, patch: { perspective: instruments.defaultPerspective }, replace: true });
    }
  }, [instruments, route]);

  // Breadcrumbs: URL-derived, every segment clickable, registry labels.
  const realFamilyGroup = effectivePerspective === "quadrants" ? parseRealFamilyGroupId(route.query.worldGroup) : null;
  const sceneGroup: string | undefined = effectivePerspective === "quadrants" ? realFamilyGroup?.key : route.group;
  const previewQuadrantFacet =
    effectivePerspective === "quadrants" && SCENE_FACETS.includes(previewQuadrant as SceneFacet) ? previewQuadrant : null;
  const runtimeQuadrantFacet: SceneFacet | null =
    worldState.lens === "q1_intencao" ? "intencao" :
    worldState.lens === "q2_pratica" ? "pratica" :
    worldState.lens === "q3_relacoes" ? "relacoes" :
    worldState.lens === "q4_sistemas" ? "sistemas" : null;
  const selectedQuadrantFacet = effectivePerspective === "quadrants" ? runtimeQuadrantFacet : null;
  const activeQuadrantFacet =
    effectivePerspective === "quadrants" ? ((previewQuadrantFacet || selectedQuadrantFacet) as SceneFacet | null) : null;
  const cameraQuadrantFacet = effectivePerspective === "quadrants" ? runtimeQuadrantFacet ?? undefined : undefined;
  const centeredRealPage =
    effectivePerspective === "quadrants" && activeQuadrantAnchorId
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
      crumbs.push({ label: worldGroupLabel("family", realFamilyGroup.family), patch: { pageId: null, reader: false } });
    } else {
      const groupKind = route.perspective === "districts" ? "page_type" : route.perspective === "atlas" ? "hub" : "attention";
      crumbs.push({ label: worldGroupLabel(groupKind, sceneGroup), patch: { pageId: null, reader: false } });
    }
  }
  if (selectedPage && selectedPage.id !== centeredRealPage?.id) crumbs.push({ label: selectedPage.title, patch: {} });

  const sceneRoute = {
    perspective: effectivePerspective,
    context: route.context,
    group: sceneGroup,
    pageId: route.pageId,
    centerId: activeQuadrantAnchorId ?? undefined,
    reader: route.query.reader,
    filter: route.query.filter,
    lens: cameraQuadrantFacet
  };

  return (
    <main
      className={[
        "worldWorkspace",
        `visualLabels-${visualConfig.labels}`,
        visualConfig.particles ? "" : "visualParticlesOff",
        visualPanelOpen ? "visualControlOpen" : "",
        realFamilyGroup ? "familyDrillOpen" : ""
      ].filter(Boolean).join(" ")}
      style={visualWorkspaceStyle}
      aria-label={t("world.aria")}
      data-runtime-mode={worldState.mode}
      data-world-center={worldState.centerId}
      data-world-view={worldState.view}
      data-world-lens={worldState.lens}
      data-world-overlay={worldState.overlay}
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
        visualTuning={visualConfig}
        bornPageIds={bornPageIds}
        missionMarkers={missionMarkers}
        flyToPageId={flyToPageId}
        anchorInfo={anchorInfo}
        activeAnchorRecord={activeQuadrantAnchor}
        centerHasQuadrants={activeCenterHasQuadrants}
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
        onRetreat={() => navigation.dispatch({ type: "retreat-world", route: routeRef.current })}
        onHistoryBack={() => navigation.dispatch({ type: "history-back" })}
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
          <div className="worldRuntimeControls" aria-label={t("world.runtimeControls")}>
            <div className="worldRuntimeControlGroup" role="group" aria-label={t("world.viewControl")}>
              {(["quadrants", "radar", "sources", "work"] as const).map((view) => (
                <button
                  key={view}
                  type="button"
                  aria-pressed={worldState.view === view}
                  className={worldState.view === view ? "runtimeControl active" : "runtimeControl"}
                  onClick={() => dispatchRuntime({ type: "setView", view })}
                >
                  {t(`world.view.${view}`)}
                </button>
              ))}
            </div>
            <label className="worldRuntimeSelect">
              <span>{t("world.overlayControl")}</span>
              <select value={worldState.overlay} onChange={(event) => dispatchRuntime({ type: "setOverlay", overlay: event.target.value as import("../world/contracts").OverlayId })}>
                {(["attention", "freshness", "actions", "ownership", "evidence", "quality"] as const).map((overlay) => (
                  <option key={overlay} value={overlay}>{t(`world.overlay.${overlay}`)}</option>
                ))}
              </select>
            </label>
          </div>
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

        {/* QUADRANT compass: each cell selects a conceptual lens and moves the
            camera inside the same 3D world. Counts are honest home-quadrant
            totals + core; no quadrant cell is a replacement center object. */}
        {quadrantCounts && activeCenterHasQuadrants && (
          <div
            className={[
              "quadrantCompass",
              "quadrantCompassApprovedTextOnly",
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
                const total = region ? region.summary.total : count;
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
                          {region.summary.total === 1 ? "1 page" : `${region.summary.total} pages`}
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
            {quadrantCounts.core > 0 && (
              <span className="quadrantCore">{t("quadrant.core")} · {quadrantCounts.core}</span>
            )}
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

        {/* Quadrant SCOPE chip (radar/districts only): the AQAL map's selection
            carries into the spatial views and mutes everything outside it; this
            chip makes that state visible and one click to clear. */}
        {!quadrantCounts &&
          SCENE_FACETS.includes(route.query.lens as SceneFacet) &&
          (route.perspective === "radar" || route.perspective === "districts") && (
          <button
            className="quadrantScopeChip"
            onClick={() => navigateWorld({ lens: null, quadrant: null })}
            title={t("world.quadrantScopeClear")}
            type="button"
          >
            {t("world.quadrantScope", { facet: t(`facet.${route.query.lens}`) })} <span aria-hidden>✕</span>
          </button>
        )}

        {/* LEFT mission surface. Collapsed by choice it is a single honest
            chip (worst tone + pending count) — the world stays visible;
            expanded it is the do-now card. Search results always render:
            the keyboard search flow must never depend on the card state. */}
        <MissionCard
          rows={missionRows}
          perspective={displayPerspective}
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
          <Suspense fallback={<aside className="pageReader" role="status">{t("world.readerLoading")}</aside>}>
          <PageReader
            bundle={bundle}
            pageId={selectedPage.id}
            demo={route.demo}
            snapshotSource={runtime.snapshotBase}
            loadPageContent={loadPageContent}
            devMode={(runtime.mode || bundle.manifest.mode) === "local_operator" && !route.demo}
            trail={trailPages}
            packetIds={route.query.packet}
            activeCenterId={activeQuadrantAnchorId}
            onNavigatePage={(id) => navigateWorld({ pageId: id, reader: true })}
            onClose={() => navigateWorld({ reader: false })}
            onTogglePacket={togglePacket}
            onRunOperatorCommand={onRun}
            onComposeBrief={onComposeBrief}
            onHoverLink={setHoverLinkId}
            onIsolateRelation={setIsolateRelation}
            onEvidenceStep={(ids, step) => setWalk({ ids, step })}
          />
          </Suspense>
        )}

        {/* BOTTOM command bar: search, perspective glyphs, packet tray. In an
            EMPTY world there are no instruments yet — the bar itself only
            exists once the root brings the first ones (genesis stage 0 shows
            nothing but the founding prompt). */}
        {!instruments.worldEmpty && (
          <CommandBar
          route={route}
          activePerspective={activeCommandPerspective}
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
            reviewCommand={reviewCommand}
            gateCommand={gateCommand}
            prCommand={prCommand}
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
          genesis={route.query.genesis}
          onComposeBrief={(spec) => onComposeBrief?.(spec)}
          onHighlightQuadrant={(facet) => navigateWorld({ lens: facet, quadrant: null }, { replace: true })}
          onClose={() => navigateWorld({ dock: null, src: null, lens: null, quadrant: null })}
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
