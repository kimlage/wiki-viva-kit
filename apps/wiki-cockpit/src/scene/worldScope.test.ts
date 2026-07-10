import { describe, expect, it } from "vitest";
import type { GraphEdge, GraphNode } from "../types";
import { quadrantHomesFromAssignments } from "./facets";
import { computeWorldLayout } from "./perspectives";
import { scopeGraphToCompiledAnchor } from "./worldScope";

function node(id: string, pageType = "claim"): GraphNode {
  return {
    id,
    path: `memories/${id}.md`,
    title: id,
    page_type: pageType,
    context: "system",
    freshness_state: "fresh",
    approved_state: "approved",
    risk_flags: [],
    metrics: { inbound_links: 0, outbound_links: 0, source_ref_count: 0 }
  };
}

const nodes = [
  node("root", "root_entity"),
  node("claims-index", "ontology_index"),
  node("claim-a"),
  node("claim-b"),
  node("unrelated-source", "source")
];
const edges: GraphEdge[] = [
  { source: "claims-index", target: "root", type: "moc_parent", status: "valid", weight: 2 },
  { source: "claim-a", target: "claims-index", type: "collection_member", status: "valid", weight: 1 },
  { source: "claim-b", target: "claim-a", type: "source_ref", status: "valid", weight: 1 },
  { source: "unrelated-source", target: "claim-a", type: "source_ref", status: "valid", weight: 1 }
];
const graph = { nodes, edges };

describe("compiled anchor world scope", () => {
  it("preserves the canonical graph for a legacy snapshot without compiled assignments", () => {
    expect(scopeGraphToCompiledAnchor(graph, "claims-index", undefined)).toBe(graph);
  });

  it("renders an explicitly empty compiled anchor as its center alone", () => {
    const assignments = {
      q0_core: [],
      q1: [],
      q2: [],
      q3: [],
      q4: []
    };
    const scoped = scopeGraphToCompiledAnchor(graph, "claims-index", assignments);

    expect(scoped.nodes.map((item) => item.id)).toEqual(["claims-index"]);
    expect(scoped.edges).toEqual([]);

    const layout = computeWorldLayout({
      perspective: "quadrants",
      nodes: scoped.nodes,
      edges: scoped.edges,
      centerId: "claims-index",
      centerHasQuadrants: true,
      quadrantHomes: quadrantHomesFromAssignments(assignments),
      maxNodes: 120
    });
    expect(layout.nodes.filter((item) => item.isRoot).map((item) => item.id)).toEqual(["claims-index"]);
    expect(layout.groups.map((group) => [group.key, group.count])).toEqual([
      ["intencao", 0],
      ["pratica", 0],
      ["relacoes", 0],
      ["sistemas", 0]
    ]);
    expect(layout.totals).toEqual({ total: 1, shown: 1, hidden: 0 });
  });

  it("keeps exact compiled members and only relations internal to the subworld", () => {
    const scoped = scopeGraphToCompiledAnchor(graph, "claims-index", {
      q0_core: [],
      q1: ["claim-a"],
      q2: [],
      q3: ["claim-b"],
      q4: []
    });

    expect(scoped.nodes.map((item) => item.id)).toEqual(["claims-index", "claim-a", "claim-b"]);
    expect(scoped.edges).toEqual([
      { source: "claim-a", target: "claims-index", type: "collection_member", status: "valid", weight: 1 },
      { source: "claim-b", target: "claim-a", type: "source_ref", status: "valid", weight: 1 }
    ]);
  });

  it("matches assignments by canonical node id, never by a coincidental path", () => {
    const scoped = scopeGraphToCompiledAnchor(graph, "claims-index", {
      q1: ["memories/claim-a.md"]
    });

    expect(scoped.nodes.map((item) => item.id)).toEqual(["claims-index"]);
  });
});
