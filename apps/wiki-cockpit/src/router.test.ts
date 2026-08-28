import { describe, expect, it } from "vitest";
import { CORE_DEMO_SCENARIO_IDS } from "./data/demoScenarios";
import { buildUrl, parseRoute, patchWorld, retreat } from "./router";
import type { WorldQuery, WorldRoute } from "./router";

const BASE_QUERY: WorldQuery = {
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

const world = (
  over: Partial<Omit<WorldRoute, "query">> & { query?: Partial<WorldQuery> } = {}
): WorldRoute => ({
  kind: "world",
  demo: false,
  perspective: "radar",
  ...over,
  query: { ...BASE_QUERY, ...(over.query ?? {}) }
});

describe("router grammar", () => {
  it("round-trips bounded typed search facets, scope and disclosure", () => {
    const parsed = parseRoute(
      "/w",
      "?view=quadrants&q=source&search_type=source_catalog&search_context=system&search_scope=world&search_limit=37"
    );
    expect(parsed).toMatchObject({
      kind: "world",
      query: {
        q: "source",
        searchType: "source_catalog",
        searchContext: "system",
        searchScope: "world",
        searchLimit: 30
      }
    });
    expect(buildUrl(parsed)).toContain("search_type=source_catalog");
    expect(buildUrl(parsed)).toContain("search_context=system");
    expect(buildUrl(parsed)).toContain("search_scope=world");
    expect(buildUrl(parsed)).toContain("search_limit=30");

    const unsafe = parseRoute("/w", "?search_type=..%2Fsecret&search_context=a%2Fb&search_scope=global&search_limit=9999");
    expect(unsafe).toMatchObject({
      query: { searchType: "", searchContext: "", searchScope: "", searchLimit: 1000 }
    });
  });

  it("hydrates the canonical v8 query grammar without conflating view, lens and overlay", () => {
    expect(parseRoute("/w", "?center=root&view=radar&lens=q3_relacoes&overlay=evidence&page=source-mail&reader=1")).toMatchObject({
      kind: "world",
      perspective: "radar",
      pageId: "source-mail",
      query: { center: "root", view: "radar", lens: "q3_relacoes", overlay: "evidence", page: "source-mail", reader: true }
    });
  });

  it("round-trips explicit runtime rollback modes without changing semantic route fields", () => {
    const parsed = parseRoute("/w", "?center=root&view=quadrants&runtime=legacy");
    expect(parsed).toMatchObject({ kind: "world", query: { center: "root", view: "quadrants", runtime: "legacy" } });
    if (parsed.kind !== "world") throw new Error("expected world route");
    expect(buildUrl(parsed)).toContain("runtime=legacy");
    expect(patchWorld(parsed, { runtime: "compat" })).toMatchObject({ query: { runtime: "compat", center: "root" } });
  });
  it("parses the world grammar /w/:perspective/:context?/:group?/:pageId?", () => {
    const route = parseRoute("/w/atlas/financeiro/faturas/custo-starlink", "?reader=1&q=star");
    expect(route).toMatchObject({
      kind: "world",
      perspective: "atlas",
      context: "financeiro",
      group: "faturas",
      pageId: "custo-starlink",
      query: { reader: true, q: "star" }
    });
  });

  it("round-trips URLs through buildUrl using only the canonical query-owned grammar", () => {
    const route = world({
      perspective: "districts",
      context: "financeiro",
      group: "decision",
      pageId: "abc",
      query: { q: "", filter: "stale", packet: ["a", "b"], reader: true, visual: false }
    });
    const url = buildUrl(route);
    expect(url).toBe(
      "/w?view=districts&group=decision&page=abc&compat_context=financeiro&filter=stale&packet=a%2Cb&reader=1&runtime=compat"
    );
    const [pathname, search] = url.split("?");
    expect(parseRoute(pathname, `?${search}`)).toMatchObject({
      perspective: "districts",
      context: "financeiro",
      pageId: "abc",
      query: {
        view: "districts",
        worldGroup: "decision",
        compatContext: "financeiro",
        page: "abc",
        filter: "stale",
        packet: ["a", "b"],
        reader: true,
        runtime: "compat"
      }
    });
  });

  it("keeps positional routes as readable inputs but normalizes every writer back to /w?view", () => {
    const legacy = parseRoute("/demo/w/atlas/financeiro/faturas/custo-starlink", "?reader=1&q=star");
    expect(legacy).toMatchObject({
      kind: "world",
      perspective: "atlas",
      context: "financeiro",
      group: "faturas",
      pageId: "custo-starlink"
    });
    if (legacy.kind !== "world") throw new Error("expected world route");
    expect(buildUrl(legacy)).toBe(
      "/demo/w?view=atlas&group=faturas&page=custo-starlink&compat_context=financeiro&q=star&reader=1&runtime=compat"
    );
    expect(buildUrl(patchWorld(legacy, { perspective: "districts" }))).toContain(
      "view=districts"
    );
    expect(buildUrl(patchWorld(legacy, { perspective: "districts" }))).toContain(
      "runtime=compat"
    );
  });

  it("keeps canonical compat page and group query state synchronized after normalization", () => {
    const normalized = parseRoute(
      "/demo/w",
      "?view=atlas&group=old-group&page=old-page&compat_context=clientes&reader=1&runtime=compat"
    );
    if (normalized.kind !== "world") throw new Error("expected world route");

    const nextPage = patchWorld(normalized, {
      context: "clientes",
      group: "new-group",
      pageId: "new-page",
      reader: true
    });
    expect(buildUrl(nextPage)).toBe(
      "/demo/w?view=atlas&group=new-group&page=new-page&compat_context=clientes&reader=1&runtime=compat"
    );

    const nextPageUrl = new URL(buildUrl(nextPage), "http://local.test");
    const reparsed = parseRoute(nextPageUrl.pathname, nextPageUrl.search);
    if (reparsed.kind !== "world") throw new Error("expected round-tripped world route");
    expect(buildUrl(patchWorld(reparsed, { reader: false }))).toContain("group=new-group");

    const withoutPage = retreat(reparsed);
    expect(buildUrl(withoutPage)).toBe(
      "/demo/w?view=atlas&group=new-group&compat_context=clientes&runtime=compat"
    );
    const withoutPageUrl = new URL(buildUrl(withoutPage), "http://local.test");
    const reparsedWithoutPage = parseRoute(withoutPageUrl.pathname, withoutPageUrl.search);
    if (reparsedWithoutPage.kind !== "world") throw new Error("expected round-tripped world route");
    const withoutGroup = retreat(reparsedWithoutPage);
    expect(buildUrl(withoutGroup)).toBe(
      "/demo/w?view=atlas&compat_context=clientes&runtime=compat"
    );
    const withoutGroupUrl = new URL(buildUrl(withoutGroup), "http://local.test");
    const reparsedWithoutGroup = parseRoute(withoutGroupUrl.pathname, withoutGroupUrl.search);
    if (reparsedWithoutGroup.kind !== "world") throw new Error("expected round-tripped world route");
    expect(buildUrl(retreat(reparsedWithoutGroup))).toBe(
      "/demo/w?view=atlas&runtime=compat"
    );
  });

  it("round-trips a conceptual lens without drilling into a group route", () => {
    const route = world({
      perspective: "quadrants",
      query: { lens: "pratica" }
    });
    const url = buildUrl(route);
    expect(url).toBe("/w?view=quadrants&lens=pratica");
    const parsed = parseRoute("/w/quadrants", "?lens=pratica");
    expect(parsed).toMatchObject({
      kind: "world",
      perspective: "quadrants",
      context: undefined,
      group: undefined,
      query: { lens: "pratica" }
    });
    expect(patchWorld(world({ perspective: "quadrants" }), { lens: "pratica" })).toMatchObject({
      perspective: "quadrants",
      context: undefined,
      group: undefined,
      query: { lens: "pratica" }
    });
  });

  it("round-trips a real family group separately from conceptual lens", () => {
    const route = world({
      perspective: "quadrants",
      query: { center: "root-alex-rivera", lens: "pratica", worldGroup: "family:source" }
    });
    const url = buildUrl(route);
    expect(url).toBe("/w?view=quadrants&center=root-alex-rivera&lens=pratica&group=family%3Asource");
    const parsed = parseRoute("/w/quadrants", "?center=root-alex-rivera&lens=pratica&group=family%3Asource");
    expect(parsed).toMatchObject({
      kind: "world",
      perspective: "quadrants",
      context: undefined,
      group: undefined,
      query: { center: "root-alex-rivera", lens: "pratica", worldGroup: "family:source" }
    });
  });

  it("treats trails as ego-centric: two segments mean context + page", () => {
    const route = parseRoute("/w/trails/financeiro/custo-starlink");
    expect(route).toMatchObject({ perspective: "trails", context: "financeiro", pageId: "custo-starlink" });
    expect(route.kind === "world" && route.group).toBeFalsy();
  });

  it("aliases /ops to the default (quadrants) world and keeps /pages/:id as a redirectable alias", () => {
    expect(parseRoute("/ops")).toMatchObject({ kind: "world", perspective: "quadrants" });
    expect(parseRoute("/pages/some%2Fpage.md")).toMatchObject({ kind: "pageAlias", pageId: "some/page.md" });
    expect(parseRoute("/pages")).toMatchObject({ kind: "pageAlias" });
    expect(parseRoute("/review")).toMatchObject({ kind: "review", demo: false });
  });

  it("seals the demo universe: /demo prefixes parse and generate demo URLs", () => {
    const route = parseRoute("/demo/w/radar/financeiro");
    expect(route).toMatchObject({ kind: "world", demo: true, context: "financeiro" });
    expect(buildUrl(world({ demo: true, context: "financeiro" }))).toBe(
      "/demo/w?view=radar&compat_context=financeiro&runtime=compat"
    );
    expect(parseRoute("/demo/review")).toMatchObject({ kind: "review", demo: true });
  });

  it("round-trips the complete demo workflow context across canonical route writes", () => {
    const input =
      "?q=source&filter=stale&packet=page-a%2Cpage-b&genesis=1&stage=4&demo_scenario=dense_stress&tour=1";
    const parsed = parseRoute("/demo/w", input);
    expect(parsed).toMatchObject({
      kind: "world",
      demo: true,
      query: {
        q: "source",
        filter: "stale",
        packet: ["page-a", "page-b"],
        genesis: true,
        stage: 4,
        demoScenario: "dense_stress",
        tour: "1"
      }
    });
    if (parsed.kind !== "world") throw new Error("expected world route");

    const patched = patchWorld(parsed, { view: "radar", lens: "all", overlay: "freshness" });
    const rebuilt = buildUrl(patched);
    const roundTrip = new URL(rebuilt, "http://local.test");
    expect(parseRoute(roundTrip.pathname, roundTrip.search)).toMatchObject({
      kind: "world",
      demo: true,
      query: {
        q: "source",
        filter: "stale",
        packet: ["page-a", "page-b"],
        view: "radar",
        lens: "all",
        overlay: "freshness",
        genesis: true,
        stage: 4,
        demoScenario: "dense_stress",
        tour: "1"
      }
    });
  });

  it("allowlists demo scenario and tour query values", () => {
    for (const scenario of CORE_DEMO_SCENARIO_IDS) {
      expect(parseRoute("/demo/w", `?demo_scenario=${scenario}&tour=0`)).toMatchObject({
        kind: "world",
        query: { demoScenario: scenario, tour: "0" }
      });
    }
    expect(parseRoute("/demo/w", "?demo_scenario=..%2Fprivate&tour=restart")).toMatchObject({
      kind: "world",
      query: { demoScenario: "", tour: "" }
    });
    expect(parseRoute("/demo/w", "?demo_scenario=study_research_showcase&tour=0")).toMatchObject({
      query: { demoScenario: "study_research_showcase", tour: "0" }
    });
    expect(parseRoute("/demo/w", "?demo_scenario=personal_finance_showcase&tour=0")).toMatchObject({
      query: { demoScenario: "personal_finance_showcase", tour: "0" }
    });
  });

  it("round-trips bounded Chronoscope state for refresh, sharing and history", () => {
    const input =
      "?view=timeline&time_from=2025-01-01&time_to=2026-07-11&time_cursor=evt-review-4" +
      "&time_mode=event&time_lanes=source,decision,pack%3Astudy&compare=31b94d81";
    const parsed = parseRoute("/w", input);
    expect(parsed).toMatchObject({
      kind: "world",
      query: {
        view: "timeline",
        timeFrom: "2025-01-01",
        timeTo: "2026-07-11",
        timeCursor: "evt-review-4",
        timeMode: "event",
        timeLanes: ["source", "decision"],
        compareRevision: "31b94d81"
      }
    });
    if (parsed.kind !== "world") throw new Error("expected world route");

    const changed = patchWorld(parsed, {
      timeCursor: "evt-review-5",
      timeMode: "recorded",
      timeLanes: ["action"]
    });
    const roundTrip = new URL(buildUrl(changed), "http://local.test");
    expect(parseRoute(roundTrip.pathname, roundTrip.search)).toMatchObject({
      query: {
        timeFrom: "2025-01-01",
        timeTo: "2026-07-11",
        timeCursor: "evt-review-5",
        timeMode: "recorded",
        timeLanes: ["action"],
        compareRevision: "31b94d81"
      }
    });
  });

  it("fails closed for unknown temporal modes and malformed lane identifiers", () => {
    expect(parseRoute("/w", "?time_mode=playback&time_lanes=source,../../private,pack%3Astudy,has%20space")).toMatchObject({
      query: { timeMode: "", timeLanes: ["source"] }
    });
  });

  it("round-trips a bounded namespaced experience-pack view without changing the native geometry", () => {
    const parsed = parseRoute("/w", "?view=quadrants&pack_view=example-pack.reference-map&center=root");
    expect(parsed).toMatchObject({
      kind: "world",
      query: { view: "quadrants", packView: "example-pack.reference-map", center: "root" }
    });
    if (parsed.kind !== "world") throw new Error("expected world route");
    expect(buildUrl(patchWorld(parsed, { packView: "example-pack.review-queue" }))).toContain(
      "pack_view=example-pack.review-queue"
    );
    expect(parseRoute("/w", "?pack_view=../../private%20page")).toMatchObject({ query: { packView: "" } });
  });

  it("rejects invalid dates, reversed-looking tokens and overlong temporal cursors", () => {
    const cursor = `evt-${"x".repeat(170)}`;
    expect(parseRoute("/w", `?time_from=2026-02-30&time_to=tomorrow&time_cursor=${cursor}&compare=bad%20revision`)).toMatchObject({
      query: { timeFrom: "", timeTo: "", timeCursor: "", compareRevision: "" }
    });
  });

  it("patchWorld keeps grammar positional invariants", () => {
    const base = world({ context: "financeiro", group: "faturas", pageId: "x", query: { q: "", filter: "", packet: [], reader: true, visual: false } });
    // Dropping the context drops the group too.
    expect(patchWorld(base, { context: null })).toMatchObject({ context: undefined, group: undefined });
    // Dropping the page closes the reader.
    expect(patchWorld(base, { pageId: null }).query.reader).toBe(false);
    // Perspective switch preserves context/page but drops perspective-specific groups.
    const switched = patchWorld(base, { perspective: "districts" });
    expect(switched).toMatchObject({ perspective: "districts", context: "financeiro", pageId: "x", group: undefined });
  });

  it("parses conflicting hand-written surfaces with dock > reader > tray precedence", () => {
    const route = parseRoute("/w/radar", "?dock=approve&station=3&ack=scope,risk&diff=1&reader=1&tray=work&src=data%2Fraw%2Fx.pdf");
    // diff needs a locked page, so with no pageId the parse still records diff
    // (the invariant only applies in patchWorld); dock/station/ack survive.
    expect(route).toMatchObject({
      kind: "world",
      query: { dock: "approve", station: 3, ack: ["scope", "risk"], reader: false, tray: "", src: "data/raw/x.pdf" }
    });
    const readerWinsTray = parseRoute("/w", "?view=quadrants&page=root&reader=1&tray=missions");
    expect(readerWinsTray).toMatchObject({ query: { reader: true, tray: "" } });

    const canonicalWrite = new URL(buildUrl(world({
      query: { dock: "gates", reader: true, tray: "missions" }
    })), "http://local.test");
    expect(canonicalWrite.searchParams.get("dock")).toBe("gates");
    expect(canonicalWrite.searchParams.has("reader")).toBe(false);
    expect(canonicalWrite.searchParams.has("tray")).toBe(false);
  });

  it("round-trips one canonical URL-owned tray without a simultaneous dock", () => {
    const built = patchWorld(world({ query: { ack: ["a"] } }), { tray: "missions" });
    const url = buildUrl(built);
    expect(url).toContain("tray=missions");
    expect(url).toContain("ack=a");
    const [pathname, search] = url.split("?");
    expect(parseRoute(pathname, `?${search}`)).toMatchObject({
      query: { dock: "", reader: false, tray: "missions", ack: ["a"] }
    });
  });

  it("rejects unknown dock/tray values (fail closed to '')", () => {
    const route = parseRoute("/w/radar", "?dock=hack&tray=bogus");
    expect(route.kind).toBe("world");
    expect((route as WorldRoute).query).toMatchObject({ dock: "", tray: "" });
  });

  it("fails closed on malformed percent escapes instead of throwing from route parsing", () => {
    expect(() => parseRoute("/pages/%")).not.toThrow();
    const invalidAlias = parseRoute("/pages/%");
    expect(invalidAlias).toMatchObject({ kind: "pageAlias" });
    expect("pageId" in invalidAlias).toBe(false);

    expect(() => parseRoute("/w/radar/%", "?q=safe")).not.toThrow();
    const invalidWorld = parseRoute("/w/radar/%", "?q=safe");
    expect(invalidWorld).toMatchObject({
      kind: "world",
      perspective: "radar",
      perspectiveExplicit: true,
      query: { q: "safe" }
    });
    expect("context" in invalidWorld).toBe(false);
    expect("group" in invalidWorld).toBe(false);
    expect("pageId" in invalidWorld).toBe(false);
  });

  it("patchWorld: dock and tray are mutually exclusive", () => {
    const withTray = world({ query: { tray: "missions" } });
    expect(patchWorld(withTray, { dock: "approve" }).query).toMatchObject({ dock: "approve", tray: "" });
    const withDock = world({ query: { dock: "approve" } });
    expect(patchWorld(withDock, { tray: "missions" }).query).toMatchObject({ tray: "missions", dock: "", reader: false });
    const withReader = world({ context: "system", pageId: "root", query: { reader: true } });
    expect(patchWorld(withReader, { tray: "missions" }).query).toMatchObject({ tray: "missions", dock: "", reader: false });
    const trayOnPage = world({ context: "system", pageId: "root", query: { tray: "missions" } });
    expect(patchWorld(trayOnPage, { reader: true }).query).toMatchObject({ tray: "", dock: "", reader: true });
  });

  it("keeps an explicit recursive quadrant center while the reader changes pages", () => {
    const base = world({
      context: "system",
      group: "claims",
      pageId: "company-claim",
      query: { reader: true, center: "root-alex-rivera" }
    });

    const url = buildUrl(base);
    expect(url).toContain("center=root-alex-rivera");

    const opened = patchWorld(base, { pageId: "template-support-page", reader: true });
    expect(opened.query.center).toBe("root-alex-rivera");
    expect(buildUrl(opened)).toContain("center=root-alex-rivera");

    const recentered = patchWorld(opened, { center: "company-clearpath-labs" });
    expect(recentered).toMatchObject({
      group: undefined,
      pageId: undefined,
      query: {
        center: "company-clearpath-labs",
        lens: "all",
        worldGroup: "",
        page: "",
        reader: false
      }
    });
    expect(patchWorld(opened, { center: null }).query.center).toBe("");
  });

  it("dock=work round-trips: the jobs monitor is deep-linkable URL state", () => {
    const route = parseRoute("/w/radar", "?dock=work");
    expect(route.kind).toBe("world");
    expect((route as WorldRoute).query.dock).toBe("work");
    const url = buildUrl(patchWorld(world(), { dock: "work" }));
    expect(url).toContain("dock=work");

    const legacyTray = parseRoute("/w", "?view=work&tray=work");
    expect(legacyTray).toMatchObject({ query: { dock: "work", tray: "" } });
    expect(buildUrl(legacyTray)).toContain("dock=work");
    expect(buildUrl(legacyTray)).not.toContain("tray=work");
  });

  it("patchWorld: diff needs a locked page; station needs the approve dock", () => {
    const base = world({ context: "a", pageId: "p", query: { dock: "approve", station: 4, diff: true, reader: true } });
    // Releasing the page clears diff.
    expect(patchWorld(base, { pageId: null }).query.diff).toBe(false);
    // Leaving the approve dock clears the selected approval lane.
    expect(patchWorld(base, { dock: "gates" }).query.station).toBe(0);
  });

  it("retreat walks exactly one level up: page → group → context → galaxy", () => {
    const locked = world({ context: "a", group: "b", pageId: "c", query: { reader: true } });
    const atGroup = retreat(locked);
    expect(atGroup).toMatchObject({ context: "a", group: "b", pageId: undefined });
    const atContext = retreat(atGroup);
    expect(atContext).toMatchObject({ context: "a", group: undefined });
    const galaxy = retreat(atContext);
    expect(galaxy).toMatchObject({ context: undefined });
    expect(retreat(galaxy)).toEqual(galaxy);
  });
});
