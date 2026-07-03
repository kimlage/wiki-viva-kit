// In-house pushState router. One URL grammar carries the whole world state:
//   /w/:perspective/:context?/:group?/:pageId?
// with transient state in the query string (?q= search, ?filter= trust,
// ?packet=id,id, ?reader=1). The browser back button, breadcrumbs and deep
// links are all the same thing; internal navigation never reloads the app.

import { useSyncExternalStore } from "react";

// `focus` is a valid URL perspective (page-centered lenses) reachable only with
// a page locked; `quadrants` is the AQAL home map (key 5). Radar stays default.
export const PERSPECTIVES = ["radar", "atlas", "districts", "trails", "focus", "quadrants"] as const;
export type PerspectiveId = (typeof PERSPECTIVES)[number];

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
  quadrant: string; // active AQAL quadrant (meaningful under perspective=quadrants)
};

export const DOCKS = ["approve", "intake", "gates", "codex", "work", "source", "create"] as const;
export type DockId = "" | (typeof DOCKS)[number];
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
  context?: string;
  group?: string;
  pageId?: string;
  query: WorldQuery;
};

export type Route =
  | WorldRoute
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
  quadrant: ""
};

function isPerspective(value: string): value is PerspectiveId {
  return (PERSPECTIVES as readonly string[]).includes(value);
}

function parseQuery(search: string): WorldQuery {
  const params = new URLSearchParams(search);
  const stationRaw = Number.parseInt(params.get("station") || "0", 10);
  return {
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
    quadrant: params.get("quadrant") || ""
  };
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
  if (path === "/" || path === "/ops" || path === "/w") {
    return { kind: "world", demo, perspective: "radar", query };
  }
  if (path.startsWith("/w/")) {
    const segments = path.slice("/w/".length).split("/").filter(Boolean).map(decodeURIComponent);
    const [head, ...rest] = segments;
    const perspective = head && isPerspective(head) ? head : "radar";
    // Positional grammar: context › group › page. Trails is ego-centric and
    // ignores the group slot, so its second segment is already the page.
    let [context, group, pageId] = rest;
    if ((perspective === "trails" || perspective === "focus") && rest.length === 2) {
      pageId = rest[1];
      group = "";
    }
    return {
      kind: "world",
      demo,
      perspective,
      context: context || undefined,
      group: group || undefined,
      pageId: pageId || undefined,
      query
    };
  }
  return { kind: "world", demo, perspective: "radar", query };
}

export function buildUrl(route: Route): string {
  const prefix = route.demo ? "/demo" : "";
  if (route.kind === "review" || route.kind === "sources" || route.kind === "health") {
    return `${prefix}/${route.kind}` || "/";
  }
  if (route.kind === "pageAlias") {
    return route.pageId ? `${prefix}/pages/${encodeURIComponent(route.pageId)}` : `${prefix}/pages`;
  }
  const segments = [route.perspective, route.context, route.group, route.pageId]
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
  if (route.query.quadrant) params.set("quadrant", route.query.quadrant);
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
  quadrant?: string | null;
};

export function patchWorld(route: WorldRoute, patch: WorldPatch): WorldRoute {
  const next: WorldRoute = {
    kind: "world",
    demo: patch.demo ?? route.demo,
    perspective: patch.perspective ?? route.perspective,
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
      quadrant: patch.quadrant === null ? "" : patch.quadrant ?? route.query.quadrant
    }
  };
  // Grammar is positional: a group needs a context, and a locked page needs
  // both — clearing the context releases the lock instead of emitting a
  // malformed URL whose pageId would be re-parsed as a context.
  if (!next.context) {
    next.group = undefined;
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
  // Opening a dock and a bottom tray occupy the same shell slot — mutually
  // exclusive so the URL never claims two surfaces are open at once.
  if (patch.dock && next.query.dock) next.query.tray = "";
  if (patch.tray && next.query.tray) next.query.dock = "";
  // The gate station only means something inside the approve dock.
  if (next.query.dock !== "approve") next.query.station = 0;
  // The active quadrant only means something in the quadrants perspective.
  if (next.perspective !== "quadrants") next.query.quadrant = "";
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
  const query = route.kind === "pageAlias" ? route.query : EMPTY_QUERY;
  return {
    kind: "world",
    demo: route.demo,
    perspective: "radar",
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

export function currentRoute(): Route {
  if (typeof window === "undefined") return { kind: "world", demo: false, perspective: "radar", query: EMPTY_QUERY };
  return parseRoute(window.location.pathname, window.location.search);
}

function subscribe(listener: Listener): () => void {
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
function getUrlSnapshot(): string {
  return window.location.pathname + window.location.search;
}

export function useRouteUrl(): string {
  return useSyncExternalStore(subscribe, getUrlSnapshot, () => "/");
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
