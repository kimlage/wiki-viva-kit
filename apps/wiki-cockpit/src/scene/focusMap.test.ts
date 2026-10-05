import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it } from "vitest";
import type { GraphEdge, GraphNode } from "../types";
import { configurePresentation, contextStyle, registerContextPalette } from "../data/presentation";
import { SEMANTIC_VISUAL_TOKENS } from "../data/visualEncoding";
import {
  buildFocusMap,
  DEFAULT_FOCUS_NODE_BUDGET,
  focusColorToken,
  MAX_FOCUS_NODE_BUDGET,
  type FocusGraph,
  type FocusMapEdge,
  type FocusMapNode
} from "./focusMap";

const walkingGraph = JSON.parse(readFileSync(
  new URL("../../public/sample-snapshot/scenarios/walking_skeleton/graph.json", import.meta.url),
  "utf8"
)) as FocusGraph;

function node(id: string, pageType = "claim", context = "example"): GraphNode {
  return {
    id, path: `memories/${id}.md`, title: `Page ${id}`, page_type: pageType, context,
    freshness_state: "fresh", approved_state: "approved", risk_flags: [], updated_at: "2026-10-05",
    metrics: { inbound_links: 0, outbound_links: 0, source_ref_count: 0 }
  };
}

function edge(source: string, target: string, extra: Partial<GraphEdge> = {}): GraphEdge {
  return { source, target, type: "source_ref", status: "valid", weight: 1, ...extra };
}

function freeze<T>(value: T): T {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

function coordinates(item: FocusMapEdge): number[] {
  return (item.path.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number);
}

function endpointOnBoundary(point: number[], item: FocusMapNode): boolean {
  const dx = Math.abs(point[0] - item.x);
  const dy = Math.abs(point[1] - item.y);
  return dx <= item.width / 2 + 5.001 && dy <= item.height / 2 + 5.001 && (
    Math.abs(dx - item.width / 2 - 5) < 0.002 || Math.abs(dy - item.height / 2 - 5) < 0.002
  );
}

afterEach(() => {
  configurePresentation(undefined);
  registerContextPalette([]);
});

describe("focused read-only 2D graph", () => {
  it("uses the committed walking skeleton's direct incoming and outgoing neighbors", () => {
    const model = buildFocusMap(walkingGraph, { selectedId: "source-banco-export" });
    expect(model.nodes.map((item) => item.id)).toEqual([
      "source-banco-export", "artifact-relatorio-recon", "claim-custos-sobem",
      "event-ingest-banco-2026-05", "hub-financeiro"
    ]);
    expect(model.counts).toMatchObject({ totalNodes: 8, shownNodes: 5, hiddenNodes: 3, totalEdges: 12, shownEdges: 10, hiddenEdges: 2 });
    const eventPair = model.edges.filter(({ edge: relation }) => (
      [relation.source, relation.target].includes("source-banco-export") &&
      [relation.source, relation.target].includes("event-ingest-banco-2026-05")
    ));
    expect(eventPair.map(({ edge: relation }) => `${relation.source}→${relation.target}:${relation.type}`).sort()).toEqual([
      "event-ingest-banco-2026-05→source-banco-export:moc_parent",
      "event-ingest-banco-2026-05→source-banco-export:source_ref",
      "source-banco-export→event-ingest-banco-2026-05:source_emission"
    ]);
    expect(new Set(eventPair.map((item) => item.key)).size).toBe(3);
    expect(new Set(eventPair.map((item) => item.path)).size).toBe(3);
    expect(eventPair.every((item) => item.directed === true)).toBe(true);
    expect(model.bounds).toEqual({ x: 0, y: 0, width: 1000, height: 680 });
  });

  it("expands only explicitly requested reachable pages, retaining earlier card positions", () => {
    const initial = buildFocusMap(walkingGraph, { selectedId: "source-banco-export" });
    const expanded = buildFocusMap(walkingGraph, {
      selectedId: "source-banco-export",
      expandedIds: ["root-alex-rivera", "hub-financeiro", "action-enviar-proposta", "missing"]
    });
    expect(expanded.nodes.map((item) => item.id)).toEqual([
      ...initial.nodes.map((item) => item.id), "root-alex-rivera", "person-marina-costa"
    ]);
    expect(expanded.expandedIds).toEqual(["hub-financeiro", "root-alex-rivera"]);
    expect(expanded.ignoredExpansionIds).toEqual(["action-enviar-proposta", "missing"]);
    expect(expanded.nodes.find((item) => item.id === "root-alex-rivera")?.depth).toBe(2);
    expect(expanded.nodes.find((item) => item.id === "person-marina-costa")?.depth).toBe(3);
    expect(expanded.counts).toMatchObject({ shownNodes: 7, hiddenNodes: 1, shownEdges: 12, hiddenEdges: 0 });
    initial.nodes.forEach((before) => {
      const after = expanded.nodes.find((item) => item.id === before.id)!;
      expect([after.x, after.y, after.width, after.height]).toEqual([before.x, before.y, before.width, before.height]);
    });
    const skippedBridge = buildFocusMap(walkingGraph, { selectedId: "source-banco-export", expandedIds: ["root-alex-rivera"] });
    expect(skippedBridge.nodes.map((item) => item.id)).toEqual(initial.nodes.map((item) => item.id));
    expect(skippedBridge.ignoredExpansionIds).toEqual(["root-alex-rivera"]);
  });

  it("leaves the frozen snapshot and options untouched, including nested provenance", () => {
    const graph = freeze(structuredClone(walkingGraph));
    const options = freeze({ selectedId: "source-banco-export", expandedIds: ["hub-financeiro"], maxNodes: 4 });
    const before = JSON.stringify({ graph, options });
    const model = buildFocusMap(graph, options);
    expect(JSON.stringify({ graph, options })).toBe(before);
    model.nodes.forEach((item) => expect(item.node).toBe(graph.nodes.find((source) => source.id === item.id)));
    model.edges.forEach((item) => expect(graph.edges).toContain(item.edge));
  });

  it("produces the same graph, keys, geometry and counts after input permutations", () => {
    const options = { selectedId: "source-banco-export", expandedIds: ["root-alex-rivera", "hub-financeiro"], maxNodes: 6 };
    const first = buildFocusMap(walkingGraph, options);
    const reordered = {
      nodes: [...walkingGraph.nodes].reverse(),
      edges: [...walkingGraph.edges].reverse().map((relation) => ({
        ...relation,
        provenance: relation.provenance ? Object.fromEntries(Object.entries(relation.provenance).reverse()) : undefined
      }))
    };
    const second = buildFocusMap(reordered, { ...options, expandedIds: [...options.expandedIds].reverse() });
    expect(second).toEqual(first);
  });

  it("bounds displayed topology and accounts separately for budget, scope and missing endpoints", () => {
    const neighbors = Array.from({ length: 8 }, (_, index) => `n${index}`);
    const children = Array.from({ length: 8 }, (_, index) => `c${index}`);
    const graph: FocusGraph = {
      nodes: [node("root"), ...neighbors.map((id) => node(id)), ...children.map((id) => node(id)), node("outside-a"), node("outside-b")],
      edges: [
        ...neighbors.map((id) => edge("root", id)),
        ...neighbors.map((id, index) => edge(id, children[index])),
        edge("outside-a", "outside-b"), edge("root", "missing")
      ]
    };
    const model = buildFocusMap(graph, { selectedId: "root", expandedIds: ["n0", "n1"], maxNodes: 4 });
    expect(model.nodes.map((item) => item.id)).toEqual(["root", "n0", "n1", "n2"]);
    expect(model.counts).toEqual({
      totalNodes: 19, shownNodes: 4, hiddenNodes: 15,
      candidateNodes: 11, hiddenCandidateNodes: 7, outsideFocusNodes: 8,
      totalEdges: 18, shownEdges: 3, hiddenEdges: 15,
      candidateEdges: 10, hiddenCandidateEdges: 7, outsideFocusEdges: 7, unresolvedEdges: 1
    });
    expect(model.nodes.find((item) => item.id === "root")?.hiddenNeighborCount).toBe(5);
    expect(model.nodes.find((item) => item.id === "n0")).toMatchObject({ isExpanded: true, hiddenNeighborCount: 1 });
    const displayed = new Set(model.nodes.map((item) => item.id));
    expect(model.edges.every(({ edge: relation }) => displayed.has(relation.source) && displayed.has(relation.target))).toBe(true);
    expect(model.edges.map(({ edge: relation }) => relation.target).sort()).toEqual(["n0", "n1", "n2"]);
  });

  it("keeps selection visible under pathological budgets and enforces the hard cap", () => {
    const neighbors = Array.from({ length: 90 }, (_, index) => node(`n${String(index).padStart(2, "0")}`));
    const graph = { nodes: [node("root"), ...neighbors], edges: neighbors.map((item) => edge("root", item.id)) };
    expect(buildFocusMap(graph, { selectedId: "root" }).nodes).toHaveLength(DEFAULT_FOCUS_NODE_BUDGET);
    expect(buildFocusMap(graph, { selectedId: "root", maxNodes: NaN }).nodes).toHaveLength(DEFAULT_FOCUS_NODE_BUDGET);
    expect(buildFocusMap(graph, { selectedId: "root", maxNodes: 10000 }).nodes).toHaveLength(MAX_FOCUS_NODE_BUDGET);
    expect(buildFocusMap(graph, { selectedId: "root", maxNodes: 0 }).nodes.map((item) => item.id)).toEqual(["root"]);
  });

  it("preserves every parallel, reciprocal and duplicate legacy record with its own path", () => {
    const duplicate = edge("a", "b");
    const graph = {
      nodes: [node("a"), node("b")],
      edges: [
        edge("a", "b", { id: "declared-edge", direction: "directed", observed_at: "2026-05", provenance: { path: "memories/a.md", field: "source_refs" } }),
        duplicate, { ...duplicate }, edge("a", "b", { type: "moc_parent" }),
        edge("b", "a", { id: "reciprocal", direction: "directed" }),
        edge("a", "a", { id: "loop-a", direction: "directed" }),
        edge("a", "a", { id: "loop-b", direction: "undirected" })
      ]
    };
    const model = buildFocusMap(graph, { selectedId: "a" });
    expect(model.edges).toHaveLength(7);
    expect(new Set(model.edges.map((item) => item.key)).size).toBe(7);
    expect(new Set(model.edges.map((item) => item.path)).size).toBe(7);
    const duplicates = model.edges.filter((item) => !item.edge.id && item.edge.type === "source_ref");
    expect(duplicates).toHaveLength(2);
    expect(duplicates.map((item) => item.key).sort()).toEqual(expect.arrayContaining([
      expect.stringMatching(/^legacy:.*#1$/), expect.stringMatching(/^legacy:.*#2$/)
    ]));
    model.edges.filter((item) => item.edge.source !== item.edge.target).forEach((item) => {
      const points = coordinates(item);
      expect(endpointOnBoundary(points.slice(0, 2), model.nodes.find((entry) => entry.id === item.edge.source)!)).toBe(true);
      expect(endpointOnBoundary(points.slice(-2), model.nodes.find((entry) => entry.id === item.edge.target)!)).toBe(true);
    });
    expect(model.edges.filter((item) => item.edge.source === item.edge.target).every((item) => item.path.includes(" C "))).toBe(true);
    expect(buildFocusMap({ nodes: [...graph.nodes].reverse(), edges: [...graph.edges].reverse() }, { selectedId: "a" })).toEqual(model);
  });

  it("honors an explicit edge ID across metadata updates without inventing legacy direction or dates", () => {
    const declared = edge("a", "b", { id: "stable-id", direction: "directed", observed_at: "month-as-recorded", basis: "frontmatter" });
    const legacy = edge("b", "a");
    const graph = { nodes: [node("a"), node("b")], edges: [declared, legacy] };
    const model = buildFocusMap(graph, { selectedId: "a" });
    const original = model.edges.find((item) => item.edge === declared)!;
    expect(original.key).toBe("id:stable-id");
    expect(original.edge.observed_at).toBe("month-as-recorded");
    const updated = buildFocusMap({ ...graph, edges: [{ ...declared, weight: 7, status: "changed" }, legacy] }, { selectedId: "a" });
    expect(updated.edges.find((item) => item.edge.id === declared.id)?.key).toBe(original.key);
    const projectedLegacy = model.edges.find((item) => item.edge === legacy)!;
    expect(projectedLegacy.directed).toBeNull();
    expect(projectedLegacy.edge).toBe(legacy);
    expect(projectedLegacy.edge).not.toHaveProperty("direction");
    expect(projectedLegacy.edge).not.toHaveProperty("provenance");
    expect(projectedLegacy.edge).not.toHaveProperty("observed_at");
  });

  it("disambiguates malformed duplicate explicit IDs without dropping their records", () => {
    const graph = { nodes: [node("a"), node("b")], edges: [
      edge("a", "b", { id: "repeated", type: "moc_parent" }),
      edge("a", "b", { id: "repeated", type: "source_ref" }),
      edge("a", "b", { id: "repeated", type: "source_ref" })
    ] };
    const first = buildFocusMap(graph, { selectedId: "a" });
    expect(new Set(first.edges.map((item) => item.key)).size).toBe(3);
    expect(first.edges.every((item) => item.key.startsWith("id:repeated:"))).toBe(true);
    expect(buildFocusMap({ ...graph, edges: [...graph.edges].reverse() }, { selectedId: "a" })).toEqual(first);
  });

  it("provides finite, bounded, non-overlapping label cards at the maximum displayed size", () => {
    const neighbors = Array.from({ length: 90 }, (_, index) => node(`n${String(index).padStart(2, "0")}`));
    const graph = { nodes: [node("root"), ...neighbors], edges: neighbors.map((item) => edge("root", item.id)) };
    const model = buildFocusMap(graph, { selectedId: "root", maxNodes: MAX_FOCUS_NODE_BUDGET });
    for (const [index, item] of model.nodes.entries()) {
      expect([item.x, item.y, item.width, item.height].every(Number.isFinite)).toBe(true);
      expect(item.x - item.width / 2).toBeGreaterThanOrEqual(model.bounds.x);
      expect(item.x + item.width / 2).toBeLessThanOrEqual(model.bounds.x + model.bounds.width);
      expect(item.y - item.height / 2).toBeGreaterThanOrEqual(model.bounds.y);
      expect(item.y + item.height / 2).toBeLessThanOrEqual(model.bounds.y + model.bounds.height);
      model.nodes.slice(index + 1).forEach((other) => {
        const overlaps = Math.abs(item.x - other.x) < (item.width + other.width) / 2 && Math.abs(item.y - other.y) < (item.height + other.height) / 2;
        expect(overlaps, `${item.id} overlaps ${other.id}`).toBe(false);
      });
    }
    expect(model.edges.every((item) => coordinates(item).every(Number.isFinite))).toBe(true);
    expect(model.counts.hiddenNodes).toBe(27);
    expect(model.bounds.width).toBe(1000);
  });

  it("keeps full readable titles and makes empty or missing selections explicit", () => {
    const longTitle = "A meaningful long title ".repeat(14).trim();
    const graph = { nodes: [{ ...node("a"), title: longTitle }, { ...node("b"), title: " \n\t " }], edges: [edge("a", "b")] };
    const model = buildFocusMap(graph, { selectedId: "a" });
    expect(model.nodes[0].label).toBe(longTitle);
    expect(model.nodes[1].label).toBe("b");
    expect(graph.nodes[1].title).toBe(" \n\t ");
    for (const selectedId of [null, "missing"]) {
      const empty = buildFocusMap(graph, { selectedId });
      expect(empty.selectedId).toBeNull();
      expect(empty.nodes).toEqual([]);
      expect(empty.edges).toEqual([]);
      expect(empty.counts).toMatchObject({ totalNodes: 2, shownNodes: 0, hiddenNodes: 2, totalEdges: 1, shownEdges: 0, hiddenEdges: 1 });
    }
  });
});

describe("focused graph identity color modes", () => {
  it("keeps context identity separate from page category and independent of input order", () => {
    const source = node("s", "source", "financeiro");
    const task = node("t", "action", "financeiro");
    const secondSource = node("s2", "source", "clientes");
    registerContextPalette([source.context, task.context, secondSource.context]);
    const before = [source, task, secondSource].map((item) => focusColorToken(item, "topic"));
    expect(focusColorToken(source, "topic")).toEqual(focusColorToken(task, "topic"));
    expect(focusColorToken(source, "category")).toEqual(focusColorToken(secondSource, "category"));
    expect(focusColorToken(source, "category").key).not.toBe(focusColorToken(task, "category").key);
    expect(focusColorToken(source, "category").color).not.toBe(focusColorToken(task, "category").color);
    expect(focusColorToken(source, "category").label).not.toBe(focusColorToken(source, "topic").label);
    registerContextPalette([secondSource.context, task.context, source.context]);
    expect([source, task, secondSource].map((item) => focusColorToken(item, "topic"))).toEqual(before);
    expect(focusColorToken(source, "topic").color).toBe(contextStyle(source.context).accent);
  });

  it("honors presentation context labels and accents while category tokens avoid reserved state colors", () => {
    configurePresentation({ contexts: { financeiro: { label: "Finanças", accent: "#123456" } } });
    expect(focusColorToken(node("s", "source", "financeiro"), "topic")).toEqual({ key: "topic:financeiro", label: "Finanças", color: "#123456" });
    const stateColors = new Set(Object.values(SEMANTIC_VISUAL_TOKENS).flatMap((scale) => Object.values(scale.states).map((token) => token.color)));
    ["root_entity", "context_hub", "source", "person", "action", "claim", "decision", "artifact", "ingestion_event", "custom_type"].forEach((pageType) => {
      const token = focusColorToken(node(pageType, pageType), "category");
      expect(stateColors.has(token.color)).toBe(false);
      expect(token.label.trim().length).toBeGreaterThan(0);
      expect(token.key).toBe(`category:${pageType}`);
    });
  });
});
