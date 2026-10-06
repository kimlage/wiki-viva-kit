// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";
import { demoSnapshotBase } from "./data/snapshot";
import {
  buildUrl,
  getRouteUrlSnapshot,
  navigate,
  parseRoute,
  patchWorld,
  subscribeRouteUrl,
  worldFromRoute,
  type WorldPatch,
  type WorldRoute
} from "./router";
import { WorldRuntime } from "./world/WorldRuntime";
import type { PageEntityIndex } from "./world/contracts";
import { canonicalWorldUrl, hydrateWorldRoute } from "./world/state/routeHydration";

const pages: PageEntityIndex = new Map([
  ["root", { id: "root", pageType: "root_entity" }],
  ["source-mail", { id: "source-mail", pageType: "source" }]
]);

const mapState = {
  projection: "2d",
  mapMode: "graph",
  mapFocus: "topic:review",
  mapExpanded: ["root", "topic:review"],
  mapColor: "state",
  mapEdge: "root->topic:review"
} as const;

const mapSearch = "projection=2d&map_view=graph&map_focus=topic%3Areview&map_expand=root&map_expand=topic%3Areview&map_color=state&map_edge=root-%3Etopic%3Areview";

function worldAt(url: string): WorldRoute {
  const parsed = new URL(url, "http://local.test");
  const route = parseRoute(parsed.pathname, parsed.search);
  if (route.kind !== "world") throw new Error("expected world route");
  return route;
}

afterEach(() => {
  window.history.replaceState({}, "", "/");
  vi.restoreAllMocks();
});

describe("opt-in 2D map route state", () => {
  it("preserves a canonical deep-linked reader without an explicit view during controls and original-cockpit return", () => {
    const route = worldAt("/demo/w?projection=2d&page=source-mail&reader=1&demo_scenario=walking_skeleton");
    for (const patch of [{ mapColor: "category" }, { q: "review" }, { projection: null, mapFocus: null, mapExpanded: [] }] satisfies WorldPatch[]) {
      const next = patchWorld(route, patch);
      const restored = worldAt(buildUrl(next));
      expect(restored.query.page).toBe("source-mail");
      expect(restored.query.reader).toBe(true);
      expect(restored.query.demoScenario).toBe("walking_skeleton");
    }
    expect(patchWorld(route, { page: null, pageId: null, reader: false }).query.reader).toBe(false);
  });
  it("keeps existing canonical URLs byte-identical when map state is empty", () => {
    const url = "/demo/w?view=quadrants&center=root&lens=all&overlay=actions&page=source-mail&q=review&reader=1&demo_scenario=walking_skeleton&tour=0";
    const route = worldAt(url);
    expect(route.query).toMatchObject({
      projection: "", mapMode: "", mapFocus: "", mapExpanded: [], mapColor: "", mapEdge: ""
    });
    expect(buildUrl(route)).toBe(url);
    const state = hydrateWorldRoute({ route, pages, rootId: "root" });
    expect(canonicalWorldUrl(state, true, route.query)).toBe(
      "/demo/w?center=root&view=quadrants&lens=all&overlay=actions&page=source-mail&reader=1&q=review&demo_scenario=walking_skeleton&tour=0"
    );
    expect(buildUrl(worldAt("/w"))).toBe("/w?view=quadrants");
  });

  it("round-trips opaque map IDs without treating map focus as the semantic center", () => {
    const route = worldAt("/demo/w?view=quadrants&center=root&page=source-mail&reader=1&demo_scenario=walking_skeleton");
    const focus = "topic:shared / résumé,+?#%";
    const expanded = ["hub:/A,B +?#%", "page:ação/1"];
    const edge = "hub:/A,B +?#%->page:ação/1";
    const patched = patchWorld(route, {
      projection: "2d", mapMode: "list", mapFocus: focus,
      mapExpanded: expanded, mapColor: "category", mapEdge: edge
    });
    const url = new URL(buildUrl(patched), "http://local.test");
    expect(url.searchParams.getAll("map_expand")).toEqual(expanded);
    expect(url.searchParams.get("map_focus")).toBe(focus);
    expect(url.searchParams.get("map_edge")).toBe(edge);
    expect(url.search).toContain("%2F");
    expect(url.search).toContain("%2C");
    expect(url.search).toContain("%2B");
    const restored = worldAt(url.href);
    expect(restored.query).toMatchObject({
      projection: "2d", mapMode: "list", mapFocus: focus,
      mapExpanded: expanded, mapColor: "category", mapEdge: edge,
      center: "root", page: "source-mail", reader: true
    });
    expect(hydrateWorldRoute({ route: restored, pages, rootId: "root" })).toMatchObject({
      centerId: "root", view: "quadrants", selectedId: "source-mail", readerId: "source-mail", warnings: []
    });
  });

  it("keeps expansion ordered, nonempty, unique and bounded across every writer", () => {
    const ids = ["", "  ", "cluster,a", "cluster,a", ...Array.from({ length: 72 }, (_, index) => `node:${index}`)];
    const params = new URLSearchParams({ view: "quadrants", center: "root", projection: "2d" });
    for (const id of ids) params.append("map_expand", id);
    const route = worldAt(`/w?${params}`);
    const expected = ["cluster,a", ...Array.from({ length: 63 }, (_, index) => `node:${index}`)];
    expect(route.query.mapExpanded).toEqual(expected);
    const patched = patchWorld(route, { mapExpanded: ids });
    expect(patched.query.mapExpanded).toEqual(expected);
    const state = hydrateWorldRoute({ route, pages, rootId: "root" });
    const rawRoute = { ...route, query: { ...route.query, mapExpanded: ids } };
    for (const url of [buildUrl(rawRoute), canonicalWorldUrl(state, false, rawRoute.query)]) {
      expect(new URL(url, "http://local.test").searchParams.getAll("map_expand")).toEqual(expected);
      expect(worldAt(url).query.mapExpanded).toEqual(expected);
    }
  });

  it.each([
    ["graph", "topic"], ["list", "category"], ["graph", "state"]
  ])("accepts map mode %s and color %s without extending the native view registry", (mode, color) => {
    const route = worldAt(`/w?view=quadrants&projection=2d&map_view=${mode}&map_color=${color}`);
    expect(route.query).toMatchObject({ view: "quadrants", projection: "2d", mapMode: mode, mapColor: color });
    expect(worldAt(buildUrl(route)).query).toMatchObject({ projection: "2d", mapMode: mode, mapColor: color });
  });

  it("normalizes invalid presentation enums without discarding opaque IDs or world state", () => {
    const route = worldAt("/w?view=quadrants&center=root&projection=3d&map_view=tree&map_color=metric&map_focus=topic%3Areview&map_expand=root&map_edge=root-%3Etopic%3Areview");
    expect(route.query).toMatchObject({
      projection: "", mapMode: "", mapColor: "", mapFocus: "topic:review",
      mapExpanded: ["root"], mapEdge: "root->topic:review", view: "quadrants", center: "root"
    });
    const invalidPatch = { projection: "3d", mapMode: "tree", mapColor: "metric" } as unknown as WorldPatch;
    const patched = patchWorld(route, invalidPatch);
    const state = hydrateWorldRoute({ route: patched, pages, rootId: "root" });
    for (const url of [buildUrl(patched), canonicalWorldUrl(state, false, patched.query)]) {
      const params = new URL(url, "http://local.test").searchParams;
      expect(params.has("projection")).toBe(false);
      expect(params.has("map_view")).toBe(false);
      expect(params.has("map_color")).toBe(false);
      expect(params.get("center")).toBe("root");
    }
  });

  it("preserves omitted map fields and canonical reader state when map controls change", () => {
    const route = worldAt(`/demo/w?view=quadrants&center=root&overlay=actions&page=source-mail&reader=1&q=review&demo_scenario=walking_skeleton&${mapSearch}`);
    const patched = patchWorld(route, { mapMode: "list", mapFocus: "source-mail" });
    expect(patched.query).toMatchObject({
      ...mapState, mapMode: "list", mapFocus: "source-mail",
      center: "root", overlay: "actions", q: "review", page: "source-mail", reader: true,
      demoScenario: "walking_skeleton", genesis: false, stage: 0
    });
    expect(route.query).toMatchObject(mapState);
    expect(worldAt(buildUrl(patched)).query).toMatchObject({ page: "source-mail", reader: true, center: "root" });
    expect(patchWorld(route, { projection: null }).query).toMatchObject({ ...mapState, projection: "" });
    expect(patchWorld(route, { page: null, pageId: null }).query.reader).toBe(false);
    const positional = worldAt("/w/quadrants?center=root&page=source-mail&reader=1");
    expect(patchWorld(positional, { mapFocus: "source-mail" }).query.reader).toBe(false);
  });

  it("clears explicitly patched map fields while preserving the semantic world and dataset", () => {
    const route = worldAt(`/demo/w?view=quadrants&center=root&page=source-mail&reader=1&q=review&demo_scenario=walking_skeleton&${mapSearch}`);
    const cleared = patchWorld(route, {
      projection: null, mapMode: null, mapFocus: null, mapExpanded: [], mapColor: null, mapEdge: null
    });
    expect(cleared.query).toMatchObject({
      projection: "", mapMode: "", mapFocus: "", mapExpanded: [], mapColor: "", mapEdge: "",
      center: "root", q: "review", page: "source-mail", reader: true, demoScenario: "walking_skeleton"
    });
    const params = new URL(buildUrl(cleared), "http://local.test").searchParams;
    expect([...params.keys()].some((key) => key === "projection" || key.startsWith("map_"))).toBe(false);
    expect(patchWorld(route, { mapExpanded: null }).query.mapExpanded).toEqual([]);
    expect(patchWorld(route, { projection: "", mapMode: "", mapColor: "" }).query).toMatchObject({
      projection: "", mapMode: "", mapColor: ""
    });
  });

  it.each([
    ["/w?view=quadrants&center=root&page=source-mail&reader=1", "v8", false],
    ["/demo/w?view=quadrants&center=root&page=source-mail&reader=1&demo_scenario=walking_skeleton", "v8", true],
    ["/demo/w/quadrants/example/family%3Asource/source-mail?center=root&reader=1&demo_scenario=walking_skeleton", "compat", true],
    ["/demo/w?view=quadrants&center=root&page=source-mail&reader=1&runtime=legacy&demo_scenario=walking_skeleton", "legacy", true]
  ] as const)("preserves map and reader state across runtime writes from %s", (url, mode, demo) => {
    const route = worldAt(`${url}&q=review&${mapSearch}`);
    const world = new WorldRuntime({ state: hydrateWorldRoute({ route, pages, rootId: "root" }), pages });
    world.dispatch({ type: "setOverlay", overlay: "evidence" });
    const canonical = canonicalWorldUrl(world.getState(), demo, route.query);
    const restored = worldAt(canonical);
    expect(world.getState().mode).toBe(mode);
    expect(restored).toMatchObject({
      demo,
      query: {
        ...mapState, center: "root", overlay: "evidence", q: "review", page: "source-mail", reader: true,
        demoScenario: demo ? "walking_skeleton" : "", genesis: false, stage: 0
      }
    });
    const params = new URL(canonical, "http://local.test").searchParams;
    expect(params.has("genesis")).toBe(false);
    expect(params.has("stage")).toBe(false);
    expect(params.get("runtime")).toBe(mode === "v8" ? null : mode);
  });

  it.each(["/demo/w/quadrants/example/family%3Asource/source-mail", "/demo/pages/source-mail"])(
    "keeps the walking-skeleton dataset through the supported legacy redirect %s",
    (pathname) => {
      const input = parseRoute(pathname, `?center=root&q=review&reader=1&demo_scenario=walking_skeleton&${mapSearch}`);
      const redirect = patchWorld(worldFromRoute(input), {
        context: "example", pageId: "source-mail", page: "source-mail", view: "atlas", runtime: "compat", reader: true
      });
      const route = worldAt(buildUrl(redirect));
      const state = hydrateWorldRoute({ route, pages, rootId: "root" });
      const url = new URL(canonicalWorldUrl(state, true, route.query), "http://local.test");
      expect(worldAt(url.href).query).toMatchObject({
        ...mapState, demoScenario: "walking_skeleton", q: "review", page: "source-mail", reader: true, genesis: false
      });
      expect(demoSnapshotBase({ search: url.search })).toBe("/sample-snapshot/scenarios/walking_skeleton");
      expect(url.searchParams.has("genesis")).toBe(false);
      expect(url.searchParams.has("stage")).toBe(false);
    }
  );

  it("restores independent focus, mode and expansions on browser back and forward", async () => {
    const first = buildUrl(worldAt(`/demo/w?view=quadrants&center=root&page=source-mail&reader=1&demo_scenario=walking_skeleton&${mapSearch}`));
    const second = buildUrl(patchWorld(worldAt(first), {
      mapMode: "list", mapFocus: "source-mail", mapExpanded: ["root", "source-mail"]
    }));
    const observed: string[] = [];
    const unsubscribe = subscribeRouteUrl(() => observed.push(getRouteUrlSnapshot()));
    try {
      navigate(first);
      navigate(second);
      window.history.back();
      await expect.poll(getRouteUrlSnapshot).toBe(first);
      expect(worldAt(getRouteUrlSnapshot()).query).toMatchObject({ ...mapState, center: "root", reader: true });
      window.history.forward();
      await expect.poll(getRouteUrlSnapshot).toBe(second);
      expect(worldAt(getRouteUrlSnapshot()).query).toMatchObject({
        ...mapState, mapMode: "list", mapFocus: "source-mail", mapExpanded: ["root", "source-mail"], center: "root", reader: true
      });
      expect(observed).toEqual([first, second, first, second]);
    } finally {
      unsubscribe();
    }
  });
});
