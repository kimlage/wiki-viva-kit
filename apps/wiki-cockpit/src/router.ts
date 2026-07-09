// In-house pushState router. One URL grammar carries the whole world state:
//   /w/:perspective/:context?/:group?/:pageId?
// with transient state in the query string (?q= search, ?filter= trust,
// ?packet=id,id, ?reader=1). The browser back button, breadcrumbs and deep
// links are all the same thing; internal navigation never reloads the app.

import { useSyncExternalStore } from "react";
import { DOCK_IDS } from "./world/contracts";
import type { DockId, RuntimeMode } from "./world/contracts";

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
  tray: TrayId; // "" | packet | missions | work (trays are URL state now)
  lens: string; // active conceptual lens (meaningful under perspective=quadrants)
  view: string; // canonical v8 world geometry; legacy positional perspective remains readable
  overlay: string; // canonical v8 visual metric
  page: string; // canonical v8 selected page
  worldGroup: string; // real grouping opened inside a world lens, encoded as ?group=family:*
  quadrant: string; // legacy active AQAL quadrant, kept only until callers migrate to lens
  center: string; // active recursive quadrant/template anchor; independent from reader page
  runtime: RuntimeMode | ""; // explicit rollback/compat flag; v8 is the canonical default
  // Genesis tutorial (demo only): the world starts EMPTY and each stage is a
  // real pre-built snapshot. `genesis` keeps the whole world grammar usable
  // inside the tutorial; `stage` picks which staged snapshot is loaded.
  genesis: boolean;
  stage: number;
};

// Compatibility re-export. The canonical surface vocabulary belongs to the
// world contract; legacy route consumers may keep importing these names while
// migration completes without reversing the dependency direction.
export const DOCKS = DOCK_IDS;
export type { DockId } from "./world/contracts";
export const TRAYS = ["packet", "missions", "work"] as const;
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
  quadrant: "",
  center: "",
  runtime: "",
  genesis: false,
  stage: 0
};

function isPerspective(value: string): value is PerspectiveId {
  return (PERSPECTIVES as readonly string[]).includes(value);
}

function asRuntimeMode(value: string | null): RuntimeMode | "" {
  return value === "legacy" || value === "compat" || value === "v8" ? value : "";
}

function parseQuery(search: string): WorldQuery {
  const params = new URLSearchParams(search);
  const stationRaw = Number.parseInt(params.get("station") || "0", 10);
  const query: WorldQuery = {
    q: params.get("q") || "",
    filter: params.get("filter") || "",
    packet: (params.get("packet") || "").split(",").map((item) => item.trim()).filter(Boolean),
    reader: params.get("reader") === "1",
    visual: params.get("visual") === "1",
    dock: asDock(params.get("dock")),
    src: params.get("src") || "",
    diff: params.get("diff") === "1",
    station: Number.isFinite(stationRaw) && stationRaw > 0 ? stationRaw : 0,
    ack: (params.get("ack") || "").split(",").map((item) => item.trim()).filter(Boolean),
    tray: asTray(params.get("tray")),
    lens: params.get("lens") || "",
    view: params.get("view") || "",
    overlay: params.get("overlay") || "",
    page: params.get("page") || "",
    worldGroup: params.get("group") || "",
    quadrant: params.get("quadrant") || "",
    center: params.get("center") || "",
    runtime: asRuntimeMode(params.get("runtime")),
    genesis: params.get("genesis") === "1",
    stage: (() => {
      const raw = Number.parseInt(params.get("stage") || "0", 10);
      return Number.isFinite(raw) && raw > 0 ? raw : 0;
    })()
  };
  // The surface singleton holds at parse time too: a hand-crafted URL never
  // claims a dock and the reader at once (the dock wins, matching patchWorld).
  if (query.dock) query.reader = false;
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
    return { kind: "pageAlias", demo, pageId: decodeURIComponent(path.slice("/pages/".length)), query: parseQuery(search) };
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
    return {
      kind: "world",
      demo,
      perspective: canonicalView,
      perspectiveExplicit: Boolean(query.view),
      pageId: query.page || undefined,
      query
    };
  }
  if (path.startsWith("/w/")) {
    const segments = path.slice("/w/".length).split("/").filter(Boolean).map(decodeURIComponent);
    const [head, ...rest] = segments;
    const explicit = Boolean(head && isPerspective(head));
    const perspective = head && isPerspective(head) ? head : DEFAULT_PERSPECTIVE;
    // Positional grammar: context › group › page. Trails is ego-centric and
    // ignores the group slot, so its second segment is already the page.
    let [context, group, pageId] = rest;
    if (context === "~") context = "";
    if ((perspective === "trails" || perspective === "focus") && rest.length === 2) {
      pageId = rest[1];
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
      query
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
  const segments = [route.perspective, route.context || (route.group ? "~" : undefined), route.group, route.pageId]
    .filter((segment): segment is string => Boolean(segment))
    .map(encodeURIComponent);
  const params = new URLSearchParams();
  if (route.query.q) params.set("q", route.query.q);
  if (route.query.filter) params.set("filter", route.query.filter);
  if (route.query.packet.length > 0) params.set("packet", route.query.packet.join(","));
  if (route.query.reader) params.set("reader", "1");
  if (route.query.visual) params.set("visual", "1");
  if (route.query.dock) params.set("dock", route.query.dock);
  if (route.query.src) params.set("src", route.query.src);
  if (route.query.diff) params.set("diff", "1");
  if (route.query.station > 0) params.set("station", String(route.query.station));
  if (route.query.ack.length > 0) params.set("ack", route.query.ack.join(","));
  if (route.query.tray) params.set("tray", route.query.tray);
  if (route.query.lens) params.set("lens", route.query.lens);
  if (route.query.view) params.set("view", route.query.view);
  if (route.query.overlay) params.set("overlay", route.query.overlay);
  if (route.query.page) params.set("page", route.query.page);
  if (route.query.worldGroup) params.set("group", route.query.worldGroup);
  if (route.query.quadrant) params.set("quadrant", route.query.quadrant);
  if (route.query.center) params.set("center", route.query.center);
  if (route.query.runtime) params.set("runtime", route.query.runtime);
  if (route.query.genesis) {
    params.set("genesis", "1");
    if (route.query.stage > 0) params.set("stage", String(route.query.stage));
  }
  const suffix = params.toString();
  return `${prefix}/w/${segments.join("/")}${suffix ? `?${suffix}` : ""}`;
}

export type WorldPatch = {
  demo?: boolean;
  perspective?: PerspectiveId;
  context?: string | null;
  group?: string | null;
  pageId?: string | null;
  q?: string | null;
  filter?: string | null;
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
};

export function patchWorld(route: WorldRoute, patch: WorldPatch): WorldRoute {
  const next: WorldRoute = {
    kind: "world",
    demo: patch.demo ?? route.demo,
    perspective: patch.perspective ?? route.perspective,
    // Any programmatic navigation makes the perspective explicit (buildUrl
    // writes it into the path); only a bare entry URL leaves it implicit.
    perspectiveExplicit: patch.perspective ? true : route.perspectiveExplicit,
    context: patch.context === null ? undefined : patch.context ?? route.context,
    group: patch.group === null ? undefined : patch.group ?? route.group,
    pageId: patch.pageId === null ? undefined : patch.pageId ?? route.pageId,
    query: {
      q: patch.q === null ? "" : patch.q ?? route.query.q,
      filter: patch.filter === null ? "" : patch.filter ?? route.query.filter,
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
      view: patch.view === null ? "" : patch.view ?? route.query.view,
      overlay: patch.overlay === null ? "" : patch.overlay ?? route.query.overlay,
      page: patch.page === null ? "" : patch.page ?? route.query.page,
      worldGroup: patch.worldGroup === null ? "" : patch.worldGroup ?? route.query.worldGroup,
      quadrant: patch.quadrant === null ? "" : patch.quadrant ?? route.query.quadrant,
      center: patch.center === null ? "" : patch.center ?? route.query.center,
      runtime: patch.runtime === null ? "" : patch.runtime ?? route.query.runtime,
      genesis: patch.genesis ?? route.query.genesis,
      stage: patch.stage === null ? 0 : patch.stage ?? route.query.stage
    }
  };
  // Grammar is positional: most groups need a context, and a locked page needs
  // one. Quadrants are conceptual lenses, not groups; only derived real-family
  // groups inside the quadrant map may use the global "~" placeholder.
  if (!next.context && next.perspective !== "quadrants") {
    next.group = undefined;
  }
  if (!next.context) {
    next.pageId = undefined;
  }
  if (patch.perspective && patch.perspective !== route.perspective && patch.group === undefined) {
    // Perspective switch preserves context/page but group keys are
    // perspective-specific, so drop the group unless explicitly kept.
    next.group = undefined;
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
  }
  if (patch.tray && next.query.tray) next.query.dock = "";
  if (patch.reader === true && !patch.dock) next.query.dock = "";
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
  if (next.perspective !== "quadrants") next.query.worldGroup = "";
  return next;
}

// One level up: page lock → group → context → galaxy. Used by Esc/RETREAT
// and by breadcrumbs; always the exact reverse of the drill that got us here.
export function retreat(route: WorldRoute): WorldRoute {
  if (route.pageId) return patchWorld(route, { pageId: null, reader: false });
  if (route.group) return patchWorld(route, { group: null });
  if (route.context) return patchWorld(route, { context: null });
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
const listeners = new Set<Listener>();

function emit(): void {
  listeners.forEach((listener) => listener());
}

export function navigate(target: Route | string, options: { replace?: boolean } = {}): void {
  const url = typeof target === "string" ? target : buildUrl(target);
  const method = options.replace ? "replaceState" : "pushState";
  if (window.location.pathname + window.location.search !== url) {
    window.history[method]({}, "", url);
  }
  emit();
}

export function subscribeRouteUrl(listener: Listener): () => void {
  listeners.add(listener);
  const onPop = () => emit();
  window.addEventListener("popstate", onPop);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("popstate", onPop);
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
