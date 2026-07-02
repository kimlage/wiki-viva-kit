import { describe, expect, it } from "vitest";
import { buildUrl, parseRoute, patchWorld, retreat } from "./router";
import type { WorldRoute } from "./router";

const world = (over: Partial<WorldRoute> = {}): WorldRoute => ({
  kind: "world",
  demo: false,
  perspective: "radar",
  query: { q: "", filter: "", packet: [], reader: false, visual: false },
  ...over
});

describe("router grammar", () => {
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

  it("round-trips URLs through buildUrl", () => {
    const route = world({
      perspective: "districts",
      context: "financeiro",
      group: "decision",
      pageId: "abc",
      query: { q: "", filter: "stale", packet: ["a", "b"], reader: true, visual: false }
    });
    const url = buildUrl(route);
    expect(url).toBe("/w/districts/financeiro/decision/abc?filter=stale&packet=a%2Cb&reader=1");
    const [pathname, search] = url.split("?");
    expect(parseRoute(pathname, `?${search}`)).toMatchObject({
      perspective: "districts",
      context: "financeiro",
      group: "decision",
      pageId: "abc",
      query: { filter: "stale", packet: ["a", "b"], reader: true }
    });
  });

  it("treats trails as ego-centric: two segments mean context + page", () => {
    const route = parseRoute("/w/trails/financeiro/custo-starlink");
    expect(route).toMatchObject({ perspective: "trails", context: "financeiro", pageId: "custo-starlink" });
    expect(route.kind === "world" && route.group).toBeFalsy();
  });

  it("aliases /ops to the radar world and keeps /pages/:id as a redirectable alias", () => {
    expect(parseRoute("/ops")).toMatchObject({ kind: "world", perspective: "radar" });
    expect(parseRoute("/pages/some%2Fpage.md")).toMatchObject({ kind: "pageAlias", pageId: "some/page.md" });
    expect(parseRoute("/pages")).toMatchObject({ kind: "pageAlias" });
    expect(parseRoute("/review")).toMatchObject({ kind: "review", demo: false });
  });

  it("seals the demo universe: /demo prefixes parse and generate demo URLs", () => {
    const route = parseRoute("/demo/w/radar/financeiro");
    expect(route).toMatchObject({ kind: "world", demo: true, context: "financeiro" });
    expect(buildUrl(world({ demo: true, context: "financeiro" }))).toBe("/demo/w/radar/financeiro");
    expect(parseRoute("/demo/review")).toMatchObject({ kind: "review", demo: true });
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

  it("retreat walks exactly one level up: page → group → context → galaxy", () => {
    const locked = world({ context: "a", group: "b", pageId: "c", query: { q: "", filter: "", packet: [], reader: true, visual: false } });
    const atGroup = retreat(locked);
    expect(atGroup).toMatchObject({ context: "a", group: "b", pageId: undefined });
    const atContext = retreat(atGroup);
    expect(atContext).toMatchObject({ context: "a", group: undefined });
    const galaxy = retreat(atContext);
    expect(galaxy).toMatchObject({ context: undefined });
    expect(retreat(galaxy)).toEqual(galaxy);
  });
});
