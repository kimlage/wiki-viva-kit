import { describe, expect, it } from "vitest";
import { parseRoute } from "../router";
import { historyModeForEvent, type PageEntityIndex } from "./contracts";
import { WorldRuntime } from "./WorldRuntime";
import { canonicalWorldUrl, hydrateWorldRoute } from "./state/routeHydration";

const pages: PageEntityIndex = new Map([
  ["root", { id: "root", pageType: "root_entity" }],
  ["source-mail", { id: "source-mail", pageType: "source" }],
  ["person-bea", { id: "person-bea", pageType: "person" }],
  ["action-review", { id: "action-review", pageType: "action" }]
]);

function runtime(url = "/w/quadrants?center=root") {
  const parsed = new URL(url, "http://local.test");
  const route = parseRoute(parsed.pathname, parsed.search);
  if (route.kind !== "world") throw new Error("expected world route");
  const state = hydrateWorldRoute({ route, pages, rootId: "root" });
  return new WorldRuntime({ state, pages });
}

describe("WorldRuntime walking skeleton", () => {
  it("normalizes legacy route state and writes the canonical grammar", () => {
    const world = runtime("/w/radar/example/family:source/source-mail?lens=relacoes&reader=1");
    expect(world.getState()).toMatchObject({ centerId: "root", view: "radar", lens: "q3_relacoes", overlay: "freshness", selectedId: "source-mail", readerId: "source-mail" });
    expect(canonicalWorldUrl(world.getState())).toBe("/w?center=root&view=radar&lens=q3_relacoes&overlay=freshness&group=family%3Asource&page=source-mail&reader=1&runtime=compat");
  });

  it("defaults canonical routes to v8 and honors compat/legacy rollback flags", () => {
    expect(runtime("/w?center=root&view=quadrants").getState().mode).toBe("v8");
    expect(runtime("/w?center=root&view=quadrants&runtime=compat").getState().mode).toBe("compat");
    expect(runtime("/w?center=root&view=quadrants&runtime=legacy").getState().mode).toBe("legacy");
  });

  it.each([
    ["sources", "evidence"],
    ["work", "actions"]
  ] as const)("hydrates a bare native %s route with its registered defaults", (view, overlay) => {
    const state = runtime(`/w?center=root&view=${view}`).getState();

    expect(state).toMatchObject({
      mode: "v8",
      centerId: "root",
      view,
      lens: "all",
      overlay,
      warnings: []
    });
    expect(canonicalWorldUrl(state)).toBe(`/w?center=root&view=${view}&lens=all&overlay=${overlay}`);
  });

  it("preserves bounded demo and workflow query state when runtime state becomes canonical", () => {
    const parsed = new URL(
      "http://local.test/demo/w?center=root&view=quadrants&lens=all&overlay=actions&q=source&filter=stale&packet=page-a%2Cpage-b&genesis=1&stage=3&demo_scenario=dense_stress&tour=0"
    );
    const route = parseRoute(parsed.pathname, parsed.search);
    if (route.kind !== "world") throw new Error("expected world route");
    const state = hydrateWorldRoute({ route, pages, rootId: "root" });

    const canonical = canonicalWorldUrl(
      { ...state, view: "radar", overlay: "freshness" },
      true,
      route.query
    );
    const canonicalUrl = new URL(canonical, "http://local.test");
    expect(parseRoute(canonicalUrl.pathname, canonicalUrl.search)).toMatchObject({
      kind: "world",
      demo: true,
      query: {
        center: "root",
        view: "radar",
        lens: "all",
        overlay: "freshness",
        q: "source",
        filter: "stale",
        packet: ["page-a", "page-b"],
        genesis: true,
        stage: 3,
        demoScenario: "dense_stress",
        tour: "0"
      }
    });
  });

  it("keeps inspect, select, read and recenter as distinct transitions", () => {
    const world = runtime();
    world.dispatch({ type: "inspectHover", entityId: "person-bea" });
    expect(world.getState()).toMatchObject({ centerId: "root", hoveredId: "person-bea" });
    world.dispatch({ type: "selectEntity", entityId: "person-bea" });
    expect(world.getState()).toMatchObject({ centerId: "root", selectedId: "person-bea" });
    world.dispatch({ type: "readEntity" });
    expect(world.getState()).toMatchObject({ centerId: "root", readerId: "person-bea" });
    world.dispatch({ type: "selectCenter", entityId: "person-bea" });
    expect(world.getState()).toMatchObject({ centerId: "person-bea", selectedId: undefined, readerId: undefined });
  });

  it("rejects derived objects as centers and keeps lens/overlay changes local", () => {
    const world = runtime();
    world.dispatch({ type: "selectCenter", entityId: "region:source" });
    world.dispatch({ type: "setLens", lens: "q4_sistemas" });
    world.dispatch({ type: "setOverlay", overlay: "evidence" });
    expect(world.getState()).toMatchObject({ centerId: "root", lens: "q4_sistemas", overlay: "evidence" });
  });

  it("normalizes invalid center, page and region routes without inventing entities", () => {
    const parsed = new URL("http://local.test/w?center=region:source&view=unknown&lens=bogus&overlay=bogus&group=region:q1&page=missing");
    const route = parseRoute(parsed.pathname, parsed.search);
    if (route.kind !== "world") throw new Error("expected world route");
    const state = hydrateWorldRoute({ route, pages, rootId: "root" });
    expect(state.centerId).toBe("root");
    expect(state.group).toBeUndefined();
    expect(state.selectedId).toBeUndefined();
    expect(state.warnings.map((warning) => warning.code)).toEqual(expect.arrayContaining(["invalid_center", "invalid_view", "invalid_lens", "invalid_overlay", "legacy_region_group", "invalid_page"]));
  });

  it.each([
    ["quadrants", "quadrants", "all", "actions"],
    ["radar", "radar", "all", "freshness"],
    ["districts", "districts", "type", "actions"],
    ["trails", "trails", "relations", "evidence"],
    ["atlas", "atlas", "type", "actions"],
    ["focus", "focus", "relations", "evidence"]
  ])("keeps the explicit v8 compatibility mapping for legacy %s", (legacy, view, lens, overlay) => {
    const world = runtime(`/w/${legacy}?center=root`);
    expect(world.getState()).toMatchObject({ mode: "compat", view, lens, overlay });
    expect(world.getState().warnings.map((warning) => warning.code)).toContain("legacy_route");
  });

  it("enforces the surface singleton", () => {
    const world = runtime();
    world.dispatch({ type: "selectEntity", entityId: "source-mail" });
    world.dispatch({ type: "readEntity" });
    world.dispatch({ type: "openSurface", dock: "source" });
    expect(world.getState()).toMatchObject({ dock: "source", readerId: undefined });
  });

  it("requires complete cross-input behavior metadata for every registered interaction", () => {
    const world = runtime();
    for (const entry of world.kernel.interactions.values()) {
      expect(entry.semanticEffect).toBeTruthy();
      expect(entry.visualEffect).toBeTruthy();
      expect(entry.desktop).toBeTruthy();
      expect(entry.mobile).toContain("44px");
      expect(entry.fallback).toBeTruthy();
      expect(entry.testId).toBe(`runtime-${entry.id}`);
    }
    expect(historyModeForEvent({ type: "inspectHover", entityId: "person-bea" })).toBe("none");
    expect(historyModeForEvent({ type: "selectCenter", entityId: "person-bea" })).toBe("push");
  });

  it("keeps bounded redacted runtime diagnostics", () => {
    const world = runtime();
    for (let index = 0; index < 205; index += 1) world.dispatch({ type: "inspectHover", entityId: index % 2 ? "person-bea" : undefined });
    expect(world.diagnostics.records()).toHaveLength(200);
    const records = world.diagnostics.records();
    expect(records[records.length - 1]?.centerId).toBe("root");
  });
});
