// In-house pushState router. Canonical writers keep the world identity and
// registered projection state in one query-owned grammar:
//   /w?view=<view>&center=<page>&lens=<lens>&overlay=<metric>
// Search, filters, packets and primary surfaces are query state too. Legacy
// positional /w/:perspective/:context?/:group?/:pageId? routes remain readable
// only as compatibility inputs and normalize to the canonical form. The
// browser back button, breadcrumbs and deep links are all the same thing;
// internal navigation never reloads the app.

import { useSyncExternalStore } from "react";
import { DOCK_IDS } from "./world/contracts";
import type { DockId, RuntimeMode } from "./world/contracts";
import { TEMPORAL_LANE_IDS } from "./data/temporalPresentation";
import { isDemoScenarioId } from "./data/demoScenarios";
import type { DemoScenarioId } from "./data/demoScenarios";

// `focus` is a valid URL perspective (page-centered lenses) reachable only with
// a page locked; `quadrants` is the AQAL home map (key 5). Quadrants is the
// DEFAULT landing view: it should set the tone for the whole wiki; radar
// and the rest stay one keystroke away.
export const PERSPECTIVES = ["radar", "atlas", "districts", "trails", "focus", "quadrants"] as const;
export type PerspectiveId = (typeof PERSPECTIVES)[number];
export const DEFAULT_PERSPECTIVE: PerspectiveId = "quadrants";
// Perspectives that a selected AQAL quadrant can scope: the map itself plus the
// two spatial views (radar/districts emphasize the quadrant's pages). atlas,
// trails and focus ignore it.
const QUADRANT_AWARE = new Set<PerspectiveId>(["quadrants", "radar", "districts"]);

export type WorldQuery = {
  q: string;
  filter: string;
  searchType: string;
  searchContext: string;
  searchScope: "" | "world";
  searchLimit: number;
  packet: string[];
  reader: boolean;
  // Test-harness flag: forces the 2D fallback; must survive every redirect.
  visual: boolean;
  // One-world task surfaces (the three 2D pages, dissolved into the world).
  dock: DockId; // "" | approve | intake | gates | codex | work | source | create
  src: string; // intake source path/url (meaningful with dock=intake); page_type seed (dock=create)
  diff: boolean; // PageReader opens on the Diff tab (needs a locked page)
  station: number; // gate station 1..6 (0 = none)
  ack: string[]; // acknowledged blocker ids (scope/risk)
  tray: TrayId; // "" | packet | missions (Work is the URL-owned dock=work surface)
  lens: string; // active conceptual lens (meaningful under perspective=quadrants)
  view: string; // canonical v8 world geometry; legacy positional perspective remains readable
  overlay: string; // canonical v8 visual metric
  page: string; // canonical v8 selected page
  worldGroup: string; // real grouping opened inside a world lens, encoded as ?group=family:*
  compatContext: string; // legacy positional context, query-owned only while runtime=compat|legacy
  quadrant: string; // legacy active AQAL quadrant, kept only until callers migrate to lens
  center: string; // active recursive quadrant/template anchor; independent from reader page
  runtime: RuntimeMode | ""; // explicit rollback/compat flag; v8 is the canonical default
  // Genesis tutorial (demo only): the world starts EMPTY and each stage is a
  // real pre-built snapshot. `genesis` keeps the whole world grammar usable
  // inside the tutorial; `stage` picks which staged snapshot is loaded.
  genesis: boolean;
  stage: number;
  // Demo-only, allowlisted universe and walkthrough preference. Both survive
  // canonical v8 state writes so a view/lens change never swaps datasets or
  // exits/restarts the requested learning flow.
  demoScenario: "" | DemoScenarioId;
  tour: "" | "0" | "1";
  // Chronoscope state is URL-owned so a temporal reading survives refresh,
  // sharing and browser history.  These fields describe a projection of the
  // canonical temporal graph; they never imply that a historical world can be
  // reconstructed or played back.
  timeFrom: string;
  timeTo: string;
  timeCursor: string;
  timeMode: "" | "event" | "occurred" | "recorded";
  timeLanes: string[];
  compareRevision: string;
  // Active experience-pack view contribution. The native world geometry stays
  // in `view`; this namespaced overlay can therefore round-trip without
  // weakening the closed core ViewId registry.
  packView: string;
};

// Compatibility re-export. The canonical surface vocabulary belongs to the
// world contract; legacy route consumers may keep importing these names while
// migration completes without reversing the dependency direction.
export const DOCKS = DOCK_IDS;
export type { DockId } from "./world/contracts";
export const TRAYS = ["packet", "missions"] as const;
export type TrayId = "" | (typeof TRAYS)[number];

function asDock(value: string | null): DockId {
  return (DOCKS as readonly string[]).includes(value || "") ? (value as DockId) : "";
}
function asTray(value: string | null): TrayId {
  return (TRAYS as readonly string[]).includes(value || "") ? (value as TrayId) : "";
}

export type WorldRoute = {
  kind: "world";
  demo: boolean;
  perspective: PerspectiveId;
  // True when the URL carried the perspective segment. When false, the shell
  // normalizes to the STACK's home view (interface.views.default) after load —
  // the default view is a template decision, not a platform constant.
  perspectiveExplicit?: boolean;
  context?: string;
  group?: string;
  pageId?: string;
  query: WorldQuery;
};

export type Route =
  | WorldRoute
  | { kind: "demoGate"; demo: true } // /demo — the title screen: start from zero, or full world
  | { kind: "review"; demo: boolean }
  | { kind: "sources"; demo: boolean }
  | { kind: "health"; demo: boolean }
  | { kind: "pageAlias"; demo: boolean; pageId?: string; query: WorldQuery };

const EMPTY_QUERY: WorldQuery = {
  q: "",
  filter: "",
  searchType: "",
  searchContext: "",
  searchScope: "",
  searchLimit: 10,
  packet: [],
  reader: false,
  visual: false,
  dock: "",
  src: "",
  diff: false,
  station: 0,
  ack: [],
  tray: "",
  lens: "",
  view: "",
  overlay: "",
  page: "",
  worldGroup: "",
  compatContext: "",
  quadrant: "",
  center: "",
  runtime: "",
  genesis: false,
  stage: 0,
  demoScenario: "",
  tour: "",
  timeFrom: "",
  timeTo: "",
  timeCursor: "",
  timeMode: "",
  timeLanes: [],
  compareRevision: "",
  packView: ""
};

function isPerspective(value: string): value is PerspectiveId {
  return (PERSPECTIVES as readonly string[]).includes(value);
}

function asRuntimeMode(value: string | null): RuntimeMode | "" {
  return value === "legacy" || value === "compat" || value === "v8" ? value : "";
}

function asTemporalMode(value: string | null): WorldQuery["timeMode"] {
  return value === "event" || value === "occurred" || value === "recorded" ? value : "";
}

function temporalDate(value: string | null): string {
  const candidate = (value || "").trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(candidate)) return "";
  const parsed = new Date(`${candidate}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === candidate ? candidate : "";
}

function safeTemporalToken(value: string | null, maxLength: number): string {
  const candidate = (value || "").trim();
  if (!candidate || candidate.length > maxLength) return "";
  return /^[a-z0-9][a-z0-9._:@/+~-]*$/i.test(candidate) ? candidate : "";
}

function safeCompatibilityContext(value: string | null): string {
  const candidate = (value || "").trim();
  if (!candidate || candidate.length > 200 || /[\u0000-\u001f\\/]/.test(candidate)) return "";
  return candidate;
}

function safeSearchFacet(value: string | null): string {
  const candidate = (value || "").trim();
  if (!candidate || candidate.length > 120 || /[\u0000-\u001f\\/]/.test(candidate)) return "";
  return candidate;
}

function searchLimit(value: string | null): number {
  const parsed = Number.parseInt(value || "10", 10);
  if (!Number.isFinite(parsed)) return 10;
  return Math.max(10, Math.min(1000, Math.floor(parsed / 10) * 10));
}

function decodeRouteSegment(value: string): string | null {
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
}

function temporalLanes(value: string | null): string[] {
  const allowed = new Set<string>(TEMPORAL_LANE_IDS);
  return [...new Set((value || "")
    .split(",")
    .map((item) => item.trim())
    .filter((item) => allowed.has(item)))]
    .slice(0, TEMPORAL_LANE_IDS.length);
}

function parseQuery(search: string): WorldQuery {
  const params = new URLSearchParams(search);
  const stationRaw = Number.parseInt(params.get("station") || "0", 10);
  const requestedScenario = params.get("demo_scenario");
  const requestedTour = params.get("tour");
  const requestedTray = params.get("tray");
  // `tray=work` was briefly emitted before Work became a proper dock. Keep
  // that historical input readable, but normalize it immediately to the only
  // rendered/shareable owner: `dock=work`.
  const requestedDock = asDock(params.get("dock")) || (requestedTray === "work" ? "work" : "");
  const query: WorldQuery = {
    q: params.get("q") || "",
    filter: params.get("filter") || "",
    searchType: safeSearchFacet(params.get("search_type")),
    searchContext: safeSearchFacet(params.get("search_context")),
    searchScope: params.get("search_scope") === "world" ? "world" : "",
    searchLimit: searchLimit(params.get("search_limit")),
    packet: (params.get("packet") || "").split(",").map((item) => item.trim()).filter(Boolean),
    reader: params.get("reader") === "1",
    visual: params.get("visual") === "1",
    dock: requestedDock,
    src: params.get("src") || "",
    diff: params.get("diff") === "1",
    station: Number.isFinite(stationRaw) && stationRaw > 0 ? stationRaw : 0,
    ack: (params.get("ack") || "").split(",").map((item) => item.trim()).filter(Boolean),
    tray: asTray(requestedTray),
    lens: params.get("lens") || "",
    view: params.get("view") || "",
    overlay: params.get("overlay") || "",
    page: params.get("page") || "",
    worldGroup: params.get("group") || "",
    compatContext: safeCompatibilityContext(params.get("compat_context")),
    quadrant: params.get("quadrant") || "",
    center: params.get("center") || "",
    runtime: asRuntimeMode(params.get("runtime")),
    genesis: params.get("genesis") === "1",
    stage: (() => {
      const raw = Number.parseInt(params.get("stage") || "0", 10);
      return Number.isFinite(raw) && raw > 0 ? raw : 0;
    })(),
    demoScenario: isDemoScenarioId(requestedScenario) ? requestedScenario : "",
    tour: requestedTour === "0" || requestedTour === "1" ? requestedTour : "",
    timeFrom: temporalDate(params.get("time_from")),
    timeTo: temporalDate(params.get("time_to")),
    timeCursor: safeTemporalToken(params.get("time_cursor"), 160),
    timeMode: asTemporalMode(params.get("time_mode")),
    timeLanes: temporalLanes(params.get("time_lanes")),
    compareRevision: safeTemporalToken(params.get("compare"), 160),
    packView: safeTemporalToken(params.get("pack_view"), 180)
  };
  // The surface singleton holds at parse time too. A hand-crafted URL has no
  // event ordering, so it uses one documented precedence: dock > reader >
  // tray. Canonical writers never emit the conflict, but old/shared links are
  // still deterministic and cannot stack two inert work surfaces.
  if (query.dock) {
    query.reader = false;
    query.tray = "";
  } else if (query.reader) {
    query.tray = "";
  }
  return query;
}

export function parseRoute(pathname: string, search = ""): Route {
  let path = pathname.replace(/\/+$/, "") || "/";
  const demo = path === "/demo" || path.startsWith("/demo/");
  if (demo) path = path.slice("/demo".length) || "/";

  if (path === "/review" || path.startsWith("/review/")) return { kind: "review", demo };
  if (path === "/sources" || path.startsWith("/sources/")) return { kind: "sources", demo };
  if (path === "/health" || path.startsWith("/health/")) return { kind: "health", demo };
  if (path === "/pages") return { kind: "pageAlias", demo, query: parseQuery(search) };
  if (path.startsWith("/pages/")) {
    const pageId = decodeRouteSegment(path.slice("/pages/".length));
    return { kind: "pageAlias", demo, ...(pageId ? { pageId } : {}), query: parseQuery(search) };
  }

  const query = parseQuery(search);
  // The demo TITLE SCREEN: bare /demo offers "start from zero" vs "full world".
  if (demo && path === "/") return { kind: "demoGate", demo: true };
  // /demo/world = the full demo straight away; /demo/genesis = the tutorial.
  if (demo && (path === "/world" || path.startsWith("/world/"))) {
    return { kind: "world", demo, perspective: DEFAULT_PERSPECTIVE, perspectiveExplicit: false, query };
  }
  if (demo && (path === "/genesis" || path.startsWith("/genesis/"))) {
    return {
      kind: "world",
      demo,
      perspective: DEFAULT_PERSPECTIVE,
      perspectiveExplicit: false,
      query: { ...query, genesis: true }
    };
  }
  if (path === "/" || path === "/ops" || path === "/w") {
    const canonicalView = isPerspective(query.view) ? query.view : DEFAULT_PERSPECTIVE;
    const compatibilityContext = query.runtime === "compat" || query.runtime === "legacy"
      ? query.compatContext || undefined
      : undefined;
    return {
      kind: "world",
      demo,
      perspective: canonicalView,
      perspectiveExplicit: Boolean(query.view),
      context: compatibilityContext,
      pageId: query.page || undefined,
      query
    };
  }
  if (path.startsWith("/w/")) {
    const rawSegments = path.slice("/w/".length).split("/").filter(Boolean);
    const head = rawSegments.length > 0 ? decodeRouteSegment(rawSegments[0]) : "";
    const rest = rawSegments.slice(1).map(decodeRouteSegment);
    const explicit = Boolean(head && isPerspective(head));
    const perspective = head && isPerspective(head) ? head : DEFAULT_PERSPECTIVE;
    // Malformed percent escapes are invalid route state, not an exception that
    // may crash the shell. Keep a valid perspective question when possible,
    // but discard every undecodable positional descendant.
    if (head === null || rest.some((segment) => segment === null)) {
      return { kind: "world", demo, perspective, perspectiveExplicit: explicit, query };
    }
    const decodedRest = rest as string[];
    // Positional grammar: context › group › page. Trails is ego-centric and
    // ignores the group slot, so its second segment is already the page.
    let [context, group, pageId] = decodedRest;
    if (context === "~") context = "";
    if ((perspective === "trails" || perspective === "focus") && decodedRest.length === 2) {
      pageId = decodedRest[1];
      group = "";
    }
    return {
      kind: "world",
      demo,
      perspective,
      perspectiveExplicit: explicit,
      context: context || undefined,
      group: group || undefined,
      pageId: pageId || undefined,
      query: {
        ...query,
        compatContext: context || query.compatContext
      }
    };
  }
  return { kind: "world", demo, perspective: DEFAULT_PERSPECTIVE, perspectiveExplicit: false, query };
}

export function buildUrl(route: Route): string {
  if (route.kind === "demoGate") return "/demo";
  const prefix = route.demo ? "/demo" : "";
  if (route.kind === "review" || route.kind === "sources" || route.kind === "health") {
    return `${prefix}/${route.kind}` || "/";
  }
  if (route.kind === "pageAlias") {
    return route.pageId ? `${prefix}/pages/${encodeURIComponent(route.pageId)}` : `${prefix}/pages`;
  }
  // `buildUrl` is a canonical writer, not a legacy formatter. Positional
  // `/w/:perspective/...` routes remain parseable above, but any code that
  // turns route state back into a URL normalizes it into `/w?view=...`.
  // Compatibility inputs carry `runtime=compat` so normalizing the path never
  // falsely promotes an old geometry into a native-v8 claim.
  const canonicalView = route.query.view || route.perspective;
  const canonicalPage = route.query.page || route.pageId || "";
  const canonicalGroup = route.query.worldGroup || route.group || "";
  const canonicalRuntime = route.query.runtime ||
    (!route.query.view && (route.perspectiveExplicit || route.context || route.group || route.pageId) ? "compat" : "");
  const canonicalCompatContext = canonicalRuntime !== "" && canonicalRuntime !== "v8"
    ? route.query.compatContext || route.context || ""
    : "";
  const canonicalDock = route.query.dock;
  const canonicalReader = !canonicalDock && route.query.reader;
  const canonicalTray = !canonicalDock && !canonicalReader ? route.query.tray : "";
  const params = new URLSearchParams();
  params.set("view", canonicalView);
  if (route.query.center) params.set("center", route.query.center);
  if (route.query.lens) params.set("lens", route.query.lens);
  if (route.query.overlay) params.set("overlay", route.query.overlay);
  if (canonicalGroup) params.set("group", canonicalGroup);
  if (canonicalPage) params.set("page", canonicalPage);
  if (canonicalCompatContext) params.set("compat_context", canonicalCompatContext);
  if (route.query.q) params.set("q", route.query.q);
  if (route.query.filter) params.set("filter", route.query.filter);
  if (route.query.searchType) params.set("search_type", route.query.searchType);
  if (route.query.searchContext) params.set("search_context", route.query.searchContext);
  if (route.query.searchScope) params.set("search_scope", route.query.searchScope);
  if (route.query.searchLimit > 10) params.set("search_limit", String(route.query.searchLimit));
  if (route.query.packet.length > 0) params.set("packet", route.query.packet.join(","));
  if (canonicalReader) params.set("reader", "1");
  if (route.query.visual) params.set("visual", "1");
  if (canonicalDock) params.set("dock", canonicalDock);
  if (route.query.src) params.set("src", route.query.src);
  if (route.query.diff) params.set("diff", "1");
  if (route.query.station > 0) params.set("station", String(route.query.station));
  if (route.query.ack.length > 0) params.set("ack", route.query.ack.join(","));
  if (canonicalTray) params.set("tray", canonicalTray);
  if (route.query.quadrant) params.set("quadrant", route.query.quadrant);
  if (canonicalRuntime) params.set("runtime", canonicalRuntime);
  if (route.query.genesis) {
    params.set("genesis", "1");
    if (route.query.stage > 0) params.set("stage", String(route.query.stage));
  }
  if (route.query.demoScenario) params.set("demo_scenario", route.query.demoScenario);
  if (route.query.tour) params.set("tour", route.query.tour);
  if (route.query.timeFrom) params.set("time_from", route.query.timeFrom);
  if (route.query.timeTo) params.set("time_to", route.query.timeTo);
  if (route.query.timeCursor) params.set("time_cursor", route.query.timeCursor);
  if (route.query.timeMode) params.set("time_mode", route.query.timeMode);
  if (route.query.timeLanes.length > 0) params.set("time_lanes", route.query.timeLanes.join(","));
  if (route.query.compareRevision) params.set("compare", route.query.compareRevision);
  if (route.query.packView) params.set("pack_view", route.query.packView);
  return `${prefix}/w?${params.toString()}`;
}

export type WorldPatch = {
  demo?: boolean;
  perspective?: PerspectiveId;
  context?: string | null;
  group?: string | null;
  pageId?: string | null;
  q?: string | null;
  filter?: string | null;
  searchType?: string | null;
  searchContext?: string | null;
  searchScope?: "world" | null;
  searchLimit?: number | null;
  packet?: string[];
  reader?: boolean;
  dock?: DockId | null;
  src?: string | null;
  diff?: boolean;
  station?: number | null;
  ack?: string[];
  tray?: TrayId | null;
  lens?: string | null;
  view?: string | null;
  overlay?: string | null;
  page?: string | null;
  worldGroup?: string | null;
  quadrant?: string | null;
  center?: string | null;
  runtime?: RuntimeMode | null;
  genesis?: boolean;
  stage?: number | null;
  demoScenario?: DemoScenarioId | null;
  tour?: "0" | "1" | null;
  timeFrom?: string | null;
  timeTo?: string | null;
  timeCursor?: string | null;
  timeMode?: "event" | "occurred" | "recorded" | null;
  timeLanes?: string[];
  compareRevision?: string | null;
  packView?: string | null;
};

export function patchWorld(route: WorldRoute, patch: WorldPatch): WorldRoute {
  const centerChanged = typeof patch.center === "string" && patch.center !== route.query.center;
  // Once a legacy positional input has been normalized, `?page=` and
  // `?group=` are the canonical selection fields even while runtime=compat.
  // Keep those query fields synchronized with the compatibility aliases on
  // every later patch. Otherwise a second selection can update `pageId` while
  // the older `query.page` keeps winning in buildUrl(), reopening the previous
  // reader (and retreat can never actually release that stale selection).
  const queryOwned = Boolean(route.query.view);
  const canonicalPagePatch = patch.page !== undefined
    ? patch.page
    : queryOwned && patch.pageId !== undefined
      ? patch.pageId
      : undefined;
  const canonicalGroupPatch = patch.worldGroup !== undefined
    ? patch.worldGroup
    : queryOwned && patch.group !== undefined
      ? patch.group
      : undefined;
  const normalizesLegacyPerspective = Boolean(
    patch.perspective && !route.query.view && route.perspectiveExplicit && patch.runtime === undefined
  );
  const compatibilityRoute = route.query.runtime === "compat" || route.query.runtime === "legacy" ||
    (!route.query.view && Boolean(route.perspectiveExplicit || route.context || route.group || route.pageId));
  const next: WorldRoute = {
    kind: "world",
    demo: patch.demo ?? route.demo,
    perspective: patch.perspective ?? route.perspective,
  // Any programmatic compatibility navigation makes the perspective explicit;
  // buildUrl then records it as query-owned `view` plus `runtime=compat`.
    perspectiveExplicit: patch.perspective ? true : route.perspectiveExplicit,
    context: patch.context === null ? undefined : patch.context ?? route.context,
    group: patch.group === null ? undefined : patch.group ?? route.group,
    pageId: patch.pageId === null ? undefined : patch.pageId ?? route.pageId,
    query: {
      q: patch.q === null ? "" : patch.q ?? route.query.q,
      filter: patch.filter === null ? "" : patch.filter ?? route.query.filter,
      searchType: patch.searchType === null ? "" : patch.searchType ?? route.query.searchType,
      searchContext: patch.searchContext === null ? "" : patch.searchContext ?? route.query.searchContext,
      searchScope: patch.searchScope === null ? "" : patch.searchScope ?? route.query.searchScope,
      searchLimit: patch.searchLimit === null ? 10 : patch.searchLimit ?? route.query.searchLimit,
      packet: patch.packet ?? route.query.packet,
      reader: patch.reader ?? route.query.reader,
      visual: route.query.visual,
      dock: patch.dock === null ? "" : patch.dock ?? route.query.dock,
      src: patch.src === null ? "" : patch.src ?? route.query.src,
      diff: patch.diff ?? route.query.diff,
      station: patch.station === null ? 0 : patch.station ?? route.query.station,
      ack: patch.ack ?? route.query.ack,
      tray: patch.tray === null ? "" : patch.tray ?? route.query.tray,
      lens: patch.lens === null ? "" : patch.lens ?? route.query.lens,
      view: patch.view === null
        ? ""
        : patch.view ?? (patch.perspective ? patch.perspective : route.query.view),
      overlay: patch.overlay === null ? "" : patch.overlay ?? route.query.overlay,
      page: canonicalPagePatch === null ? "" : canonicalPagePatch ?? route.query.page,
      worldGroup: canonicalGroupPatch === null ? "" : canonicalGroupPatch ?? route.query.worldGroup,
      compatContext: compatibilityRoute
        ? patch.context === null ? "" : (patch.context ?? route.query.compatContext) || route.context || ""
        : route.query.compatContext,
      quadrant: patch.quadrant === null ? "" : patch.quadrant ?? route.query.quadrant,
      center: patch.center === null ? "" : patch.center ?? route.query.center,
      runtime: patch.runtime === null
        ? ""
        : patch.runtime ?? (normalizesLegacyPerspective ? "compat" : route.query.runtime),
      genesis: patch.genesis ?? route.query.genesis,
      stage: patch.stage === null ? 0 : patch.stage ?? route.query.stage,
      demoScenario: patch.demoScenario === null ? "" : patch.demoScenario ?? route.query.demoScenario,
      tour: patch.tour === null ? "" : patch.tour ?? route.query.tour,
      timeFrom: patch.timeFrom === null ? "" : patch.timeFrom ?? route.query.timeFrom,
      timeTo: patch.timeTo === null ? "" : patch.timeTo ?? route.query.timeTo,
      timeCursor: patch.timeCursor === null ? "" : patch.timeCursor ?? route.query.timeCursor,
      timeMode: patch.timeMode === null ? "" : patch.timeMode ?? route.query.timeMode,
      timeLanes: patch.timeLanes ?? route.query.timeLanes,
      compareRevision: patch.compareRevision === null ? "" : patch.compareRevision ?? route.query.compareRevision,
      packView: patch.packView === null ? "" : patch.packView ?? route.query.packView
    }
  };
  // A center is a new subject, not a filter on the old one. Normalize every
  // route writer here (including docks that bypass the runtime reducer) so a
  // stale quadrant/group/reader cannot describe the previous center.
  if (centerChanged) {
    next.group = undefined;
    next.pageId = undefined;
    next.query.lens = "all";
    next.query.worldGroup = "";
    next.query.page = "";
    next.query.reader = false;
  }
  // Grammar is positional: most groups need a context, and a locked page needs
  // one. Quadrants are conceptual lenses, not groups; only derived real-family
  // groups inside the quadrant map may use the global "~" placeholder.
  if (!next.context && next.perspective !== "quadrants") {
    next.group = undefined;
  }
  if (!next.context) {
    next.pageId = undefined;
  }
  const projectionChanged = Boolean(
    (patch.perspective && patch.perspective !== route.perspective) ||
    (patch.view && patch.view !== route.query.view)
  );
  if (projectionChanged && patch.group === undefined && patch.worldGroup === undefined) {
    // View/perspective switches preserve context/page but group keys are
    // projection-specific, so drop both compatibility and canonical aliases
    // unless the caller explicitly supplied the next group.
    next.group = undefined;
    next.query.worldGroup = "";
  }
  if (!next.pageId) {
    next.query.reader = false;
    next.query.diff = false; // the Diff tab needs a locked page
  }
  // ONE work surface at a time (the surface singleton): a dock, a tray and the
  // reader never stack — opening one closes the others, so the URL never
  // claims two working surfaces at once. (The locked page's summary plate is
  // not a work surface; it coexists.)
  if (patch.dock && next.query.dock) {
    next.query.tray = "";
    next.query.reader = false;
  } else if (patch.tray && next.query.tray) {
    next.query.dock = "";
    next.query.reader = false;
  } else if (patch.reader === true) {
    next.query.dock = "";
    next.query.tray = "";
  } else if (next.query.dock) {
    // Normalize malformed/pre-singleton route objects even when this patch is
    // unrelated to surfaces. This matches parseQuery's fixed precedence.
    next.query.reader = false;
    next.query.tray = "";
  } else if (next.query.reader) {
    next.query.tray = "";
  }
  // The gate station only means something inside the approve dock.
  if (next.query.dock !== "approve") next.query.station = 0;
  // ?src= qualifies a dock (intake source, create seed, blocks anchor) — with
  // no dock open it is a dead parameter that would leak into later opens.
  if (!next.query.dock) next.query.src = "";
  // The active quadrant scopes the quadrant-aware perspectives (the AQAL map and
  // the two spatial views that can honor it); it is meaningless in atlas / trails
  // / focus, so it clears there.
  if (!QUADRANT_AWARE.has(next.perspective)) {
    next.query.lens = "";
    next.query.quadrant = "";
  }
  return next;
}

// One level up: page lock → group → context → galaxy. Used by Esc/RETREAT
// and by breadcrumbs; always the exact reverse of the drill that got us here.
export function retreat(route: WorldRoute): WorldRoute {
  if (route.query.page || route.pageId) return patchWorld(route, { pageId: null, page: null, reader: false });
  if (route.query.worldGroup || route.group) return patchWorld(route, { group: null, worldGroup: null });
  if (route.query.compatContext || route.context) return patchWorld(route, { context: null });
  return route;
}

export function worldFromRoute(route: Route): WorldRoute {
  if (route.kind === "world") return route;
  if (route.kind === "demoGate") {
    return { kind: "world", demo: true, perspective: DEFAULT_PERSPECTIVE, perspectiveExplicit: false, query: { ...EMPTY_QUERY } };
  }
  const query = route.kind === "pageAlias" ? route.query : EMPTY_QUERY;
  return {
    kind: "world",
    demo: route.demo,
    perspective: DEFAULT_PERSPECTIVE,
    perspectiveExplicit: false,
    query: { ...query, packet: [...query.packet], ack: [...query.ack] }
  };
}

// --- history plumbing -------------------------------------------------------

type Listener = () => void;
const ROUTE_CHANGE_EVENT = "wiki-viva:route-change";

export function navigate(target: Route | string, options: { replace?: boolean } = {}): void {
  const url = typeof target === "string" ? target : buildUrl(target);
  const method = options.replace ? "replaceState" : "pushState";
  if (window.location.pathname + window.location.search !== url) {
    window.history[method]({}, "", url);
  }
  // A browser event is deliberately used instead of a module-local listener
  // set. RuntimeWorldView is a lazy capability chunk; a route write must wake
  // the App shell even if the bundler/runtime evaluates router plumbing in a
  // separate module instance.
  window.dispatchEvent(new Event(ROUTE_CHANGE_EVENT));
}

export function subscribeRouteUrl(listener: Listener): () => void {
  window.addEventListener("popstate", listener);
  window.addEventListener(ROUTE_CHANGE_EVENT, listener);
  return () => {
    window.removeEventListener("popstate", listener);
    window.removeEventListener(ROUTE_CHANGE_EVENT, listener);
  };
}

// Strings are Object.is-comparable, so reading location directly keeps the
// snapshot fresh even when history changes outside navigate() (tests, other
// scripts) without breaking useSyncExternalStore's caching contract.
export function getRouteUrlSnapshot(): string {
  return window.location.pathname + window.location.search;
}

export function useRouteUrl(): string {
  return useSyncExternalStore(subscribeRouteUrl, getRouteUrlSnapshot, () => "/");
}

// Intercept internal anchor clicks so plain <a href> stays the navigation
// primitive (keyboard/screen-reader friendly) without full document reloads.
export function installLinkInterceptor(): () => void {
  const onClick = (event: MouseEvent) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = (event.target as HTMLElement | null)?.closest?.("a");
    if (!anchor) return;
    const href = anchor.getAttribute("href") || "";
    if (!href.startsWith("/") || anchor.target === "_blank" || anchor.hasAttribute("download")) return;
    if (href.startsWith("/api/")) return;
    event.preventDefault();
    navigate(href);
  };
  document.addEventListener("click", onClick);
  return () => document.removeEventListener("click", onClick);
}
