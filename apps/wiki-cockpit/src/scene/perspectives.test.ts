import { describe, expect, it } from "vitest";
import type { GraphEdge, GraphNode } from "../types";
import { computeWorldLayout, groupKeyForPage, worldLevel } from "./perspectives";
import type { WorldRequest } from "./perspectives";
import { homeQuadrant, nodeQuadrant, quadrantHomesFromAssignments, QUADRANT_CENTER_ANGLE } from "./facets";

const SNAPSHOT = "2026-07-01T00:00:00Z";

function node(id: string, context: string, overrides: Partial<GraphNode> & { stale_after_days?: string } = {}): GraphNode {
  return {
    id,
    path: `memories/${context}/${id}.md`,
    title: id,
    page_type: "context_note",
    context,
    freshness_state: "fresh",
    approved_state: "approved",
    risk_flags: [],
    metrics: { inbound_links: 0, outbound_links: 1, source_ref_count: 0 },
    updated_at: "2026-06-20",
    stale_after_days: "30",
    ...overrides
  } as GraphNode;
}

// A synthetic 3-context wiki: hubs, hierarchies, sources and a large body of
// pages so the per-level cap and cluster stars are exercised for real.
function fixture(): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes: GraphNode[] = [node("root", "system", { page_type: "root_index", path: "memories/index.md" })];
  const edges: GraphEdge[] = [];
  const contexts = ["financeiro", "casa", "projetos"];
  contexts.forEach((context, contextIndex) => {
    const hub = node(`${context}-hub`, context, { page_type: "context_hub", path: `memories/${context}/index.md` });
    nodes.push(hub);
    edges.push({ source: hub.id, target: "root", type: "moc_parent", status: "valid", weight: 2 });
    for (let index = 0; index < 40 + contextIndex * 10; index += 1) {
      const id = `${context}-p${index}`;
      const page = node(id, context, {
        page_type: index % 7 === 0 ? "decision" : index % 5 === 0 ? "source" : "context_note",
        freshness_state: index % 6 === 0 ? "stale" : index % 11 === 0 ? "unknown" : "fresh",
        updated_at: index % 11 === 0 ? "" : index % 6 === 0 ? "2026-03-01" : "2026-06-20"
      });
      nodes.push(page);
      edges.push({ source: id, target: hub.id, type: "moc_parent", status: "valid", weight: 2 });
      if (index % 5 === 0 && index > 0) {
        edges.push({ source: `${context}-p${index - 1}`, target: id, type: "source_ref", status: "valid", weight: 1 });
      }
      if (index % 3 === 0 && index > 0) {
        edges.push({ source: id, target: `${context}-p${index - 1}`, type: "markdown_link", status: "valid", weight: 1 });
      }
    }
  });
  return { nodes, edges };
}

function request(over: Partial<WorldRequest> = {}): WorldRequest {
  const { nodes, edges } = fixture();
  return { perspective: "radar", nodes, edges, maxNodes: 60, snapshotAt: SNAPSHOT, ...over };
}

describe("perspective engine", () => {
  it("is deterministic: same snapshot input, same positions, every perspective", () => {
    (["radar", "atlas", "districts", "trails", "focus"] as const).forEach((perspective) => {
      const base = request({
        perspective,
        pageId: perspective === "trails" || perspective === "focus" ? "financeiro-p1" : undefined
      });
      const first = computeWorldLayout(base);
      const reversed = computeWorldLayout({ ...base, nodes: [...base.nodes].reverse(), edges: [...base.edges].reverse() });
      expect(JSON.stringify(first)).toEqual(JSON.stringify(reversed));
    });
  });

  it("honors the per-level cap and never hides pages silently: shown + hidden = total", () => {
    const layout = computeWorldLayout(request());
    expect(layout.nodes.length).toBeLessThanOrEqual(60);
    expect(layout.totals.shown + layout.totals.hidden).toBe(layout.totals.total);
    // Hidden pages appear as cluster stars whose counts sum to the hidden total.
    const starSum = layout.clusterStars.reduce((sum, star) => sum + star.count, 0);
    expect(starSum).toBe(layout.totals.hidden);
    expect(starSum).toBeGreaterThan(0);
    layout.clusterStars.forEach((star) => {
      expect(star.drill?.context).toBeTruthy();
      const histogramSum = star.histogram.fresh + star.histogram.stale + star.histogram.unknown;
      expect(histogramSum).toBe(star.count);
    });
  });

  it("radar wedges report TRUE totals with shown counts, not the visible slice", () => {
    const layout = computeWorldLayout(request());
    const financeiro = layout.wedges.find((wedge) => wedge.context === "financeiro");
    expect(financeiro?.count).toBe(41); // 40 pages + hub
    expect(financeiro && financeiro.shown <= financeiro.count).toBe(true);
  });

  it("places unknown freshness on the discrete sem-dados band, outside rOuter", () => {
    const layout = computeWorldLayout(request({ maxNodes: 200 }));
    expect(layout.unknownR).not.toBeNull();
    const unknowns = layout.nodes.filter((item) => item.freshness_state === "unknown" && !item.isHub);
    expect(unknowns.length).toBeGreaterThan(0);
    unknowns.forEach((item) => {
      const radius = Math.hypot(item.position[0], item.position[2]);
      expect(radius).toBeGreaterThan(layout.rOuter);
      expect(radius).toBeCloseTo(layout.unknownR!, 1);
    });
  });

  it("drills radar to a full-context immersion with horizon beacons", () => {
    const layout = computeWorldLayout(request({ context: "financeiro", maxNodes: 160 }));
    expect(layout.level).toBe(1);
    expect(layout.totals.total).toBe(41);
    expect(layout.totals.shown).toBe(41); // full context fits the cap
    expect(layout.beacons.map((beacon) => beacon.context).sort()).toEqual(["casa", "projetos", "system"]);
    // Attention cluster group exists and drills to L2.
    const attention = layout.groups.find((group) => group.key === "atencao");
    expect(attention?.drill).toMatchObject({ context: "financeiro", group: "atencao" });
  });

  it("atlas orbits the hierarchy and buckets orphans visibly", () => {
    const { nodes, edges } = fixture();
    nodes.push(node("orfao", "financeiro"));
    const layout = computeWorldLayout({ perspective: "atlas", context: "financeiro", nodes, edges, maxNodes: 80, snapshotAt: SNAPSHOT });
    expect(layout.level).toBe(1);
    const root = layout.nodes.find((item) => item.isRoot);
    expect(root?.id).toBe("financeiro-hub");
    expect(root?.position).toEqual([0, 0, 0]);
    const orphanGroup = layout.groups.find((group) => group.key === "sem-pai");
    expect(orphanGroup).toBeTruthy();
    expect(orphanGroup!.count).toBeGreaterThan(0);
  });

  it("districts shelves sort the world by family and scope by context via the URL", () => {
    const layout = computeWorldLayout(request({ perspective: "districts", maxNodes: 200 }));
    expect(layout.radial).toBe("shelf");
    const decisions = layout.nodes.filter((item) => item.page_type === "decision");
    const notes = layout.nodes.filter((item) => item.page_type === "context_note");
    expect(decisions.length).toBeGreaterThan(0);
    // All members of one family sit on the same shelf radius.
    const radii = new Set(decisions.map((item) => Math.hypot(item.position[0], item.position[2]).toFixed(1)));
    expect(radii.size).toBe(1);
    // Different families sit on different shelves.
    expect(Math.hypot(notes[0].position[0], notes[0].position[2])).not.toBeCloseTo(
      Math.hypot(decisions[0].position[0], decisions[0].position[2]),
      1
    );
    const scoped = computeWorldLayout(request({ perspective: "districts", context: "financeiro", group: "decision" }));
    expect(scoped.level).toBe(2);
    expect(scoped.nodes.every((item) => item.page_type === "decision")).toBe(true);
  });

  it("trails builds the ego-graph in typed sectors with true counts", () => {
    const layout = computeWorldLayout(request({ perspective: "trails", context: "financeiro", pageId: "financeiro-p5", maxNodes: 80 }));
    const center = layout.nodes.find((item) => item.isRoot);
    expect(center?.id).toBe("financeiro-p5");
    expect(center?.position).toEqual([0, 0, 0]);
    const sectorKeys = layout.groups.map((group) => group.key);
    expect(sectorKeys).toEqual(["hierarquia", "evidencia", "links", "citado-por"]);
    // financeiro-p5 has a moc_parent (hub) → hierarchy sector counts it.
    const hierarchy = layout.groups.find((group) => group.key === "hierarquia");
    expect(hierarchy!.count).toBeGreaterThan(0);
  });

  it("quadrants: the four regions always emit, core only when populated, honest counts", () => {
    const layout = computeWorldLayout(request({ perspective: "quadrants", maxNodes: 120 }));
    expect(layout.perspective).toBe("quadrants");
    expect(layout.radial).toBe("shelf"); // radius = shelf depth, NOT freshness
    // Exactly the four quadrant groups, always, in canonical order — even empty.
    const quadrantGroups = layout.groups.filter((g) => g.kind === "quadrant");
    expect(quadrantGroups.map((g) => g.key)).toEqual(["intencao", "pratica", "relacoes", "sistemas"]);
    // decision→intencao and source→sistemas are populated in the fixture.
    expect(quadrantGroups.find((g) => g.key === "intencao")!.count).toBeGreaterThan(0);
    expect(quadrantGroups.find((g) => g.key === "sistemas")!.count).toBeGreaterThan(0);
    // The fixture has structural pages (root_index/context_hub/context_note) → a
    // core group is emitted (only because it is populated; it is not a 5th quadrant).
    const core = layout.groups.filter((g) => g.kind === "core");
    expect(core).toHaveLength(1);
    expect(core[0].count).toBeGreaterThan(0);
    // Four boundary rays (the axes between quadrants).
    expect(layout.guides.filter((g) => g.kind === "ray")).toHaveLength(4);
    // Honest counting invariant.
    expect(layout.totals.shown + layout.totals.hidden).toBe(layout.totals.total);
  });

  it("quadrants: every node sits in ITS facet's sector, the root alone holds the center, structure wraps outside", () => {
    // The regression this pins: a hand-written floor-square table once put
    // Culture/relations' square over Identity/intent nodes, and a structural swarm at the
    // origin buried the root. Sector membership is now a geometric CONTRACT.
    const layout = computeWorldLayout(request({ perspective: "quadrants", maxNodes: 200 }));
    const root = layout.nodes.find((item) => item.isRoot);
    expect(root?.position).toEqual([0, 0, 0]);
    for (const item of layout.nodes) {
      if (item.isRoot) continue;
      const radius = Math.hypot(item.position[0], item.position[2]);
      const home = homeQuadrant(item.page_type);
      if (!home) {
        // Structural pages live OUTSIDE the quadrants, never at the center.
        expect(radius).toBeGreaterThan(layout.rOuter);
        continue;
      }
      const angle = QUADRANT_CENTER_ANGLE[home];
      expect(Math.sign(item.position[0])).toBe(Math.sign(Math.cos(angle)));
      expect(Math.sign(item.position[2])).toBe(Math.sign(Math.sin(angle)));
      expect(radius).toBeLessThanOrEqual(layout.rOuter + 0.01);
    }
  });

  it("quadrants: group anchors use canonical Wilber screen positions", () => {
    const layout = computeWorldLayout(request({ perspective: "quadrants", maxNodes: 200 }));
    const anchors = new Map(layout.groups.filter((group) => group.kind === "quadrant").map((group) => [group.key, group.anchor]));

    expect(anchors.get("intencao")![0]).toBeLessThan(0);
    expect(anchors.get("intencao")![2]).toBeLessThan(0);
    expect(anchors.get("pratica")![0]).toBeGreaterThan(0);
    expect(anchors.get("pratica")![2]).toBeLessThan(0);
    expect(anchors.get("relacoes")![0]).toBeLessThan(0);
    expect(anchors.get("relacoes")![2]).toBeGreaterThan(0);
    expect(anchors.get("sistemas")![0]).toBeGreaterThan(0);
    expect(anchors.get("sistemas")![2]).toBeGreaterThan(0);
  });

  it("quadrants: compiled homes are anchor-relative, not global page homes", () => {
    const rootHomes = quadrantHomesFromAssignments({
      q1: [],
      q2: [],
      q3: [],
      q4: ["company-intent"],
      q0_core: []
    });
    const companyHomes = quadrantHomesFromAssignments({
      q1: ["company-intent"],
      q2: [],
      q3: [],
      q4: [],
      q0_core: []
    });
    expect(rootHomes?.["company-intent"]).toBe("sistemas");
    expect(companyHomes?.["company-intent"]).toBe("intencao");
    expect(nodeQuadrant("company-intent", "claim", rootHomes)).toBe("sistemas");
    expect(nodeQuadrant("company-intent", "claim", companyHomes)).toBe("intencao");
  });

  it("quadrants is deterministic and never emits a core group when there are no structural pages", () => {
    const { nodes, edges } = fixture();
    const onlyTyped = nodes.filter((n) => ["decision", "source", "action", "person"].includes(n.page_type));
    const layout = computeWorldLayout({ perspective: "quadrants", nodes: onlyTyped, edges, maxNodes: 120, snapshotAt: SNAPSHOT });
    expect(layout.groups.filter((g) => g.kind === "quadrant")).toHaveLength(4); // still four, always
    expect(layout.groups.filter((g) => g.kind === "core")).toHaveLength(0); // no structural → no core
    const reversed = computeWorldLayout({ perspective: "quadrants", nodes: [...onlyTyped].reverse(), edges: [...edges].reverse(), maxNodes: 120, snapshotAt: SNAPSHOT });
    expect(JSON.stringify(layout)).toEqual(JSON.stringify(reversed));
  });

  it("focus centers the page and buckets neighbors into the four facet lenses", () => {
    const layout = computeWorldLayout(request({ perspective: "focus", context: "financeiro", pageId: "financeiro-p5", maxNodes: 80 }));
    const center = layout.nodes.find((item) => item.isRoot);
    expect(center?.id).toBe("financeiro-p5");
    expect(center?.position).toEqual([0, 0, 0]);
    // Exactly the four lenses, in quadrant order q1..q4, always present (even empty).
    expect(layout.groups.map((group) => group.key)).toEqual(["intencao", "pratica", "relacoes", "sistemas"]);
    expect(layout.groups.every((group) => group.kind === "facet")).toBe(true);
    // financeiro-p4 is source_ref evidence of p5 -> the Systems/governance (q4) lens counts it.
    const sistemas = layout.groups.find((group) => group.key === "sistemas");
    expect(sistemas!.count).toBeGreaterThan(0);
    // Lenses with no neighbor stay present with a true zero — honest absence.
    expect(layout.groups.some((group) => group.count === 0)).toBe(true);
    // The honest-counting invariant holds for focus too.
    expect(layout.totals.shown + layout.totals.hidden).toBe(layout.totals.total);
  });

  it("keeps every page reachable in ≤4 interactions: galaxy → context → group → page", () => {
    const { nodes, edges } = fixture();
    const targets = nodes.filter((item) => item.page_type !== "root_index");
    targets.forEach((page) => {
      // Interaction 1: galaxy shows the page's context (wedge or star drill).
      const galaxy = computeWorldLayout({ perspective: "radar", nodes, edges, maxNodes: 60, snapshotAt: SNAPSHOT });
      const wedge = galaxy.wedges.find((item) => item.context === (page.context || "system"));
      expect(wedge).toBeTruthy();
      // Interaction 2: context immersion; the page is visible or in a group/star.
      const immersion = computeWorldLayout({
        perspective: "radar",
        context: page.context || "system",
        nodes,
        edges,
        maxNodes: 60,
        snapshotAt: SNAPSHOT
      });
      const visible = immersion.nodes.some((item) => item.id === page.id);
      const groupKey = groupKeyForPage("radar", page);
      if (!visible) {
        // Interaction 3: the page's group level must show it.
        const groupLayout = computeWorldLayout({
          perspective: "radar",
          context: page.context || "system",
          group: groupKey,
          nodes,
          edges,
          maxNodes: 160,
          snapshotAt: SNAPSHOT
        });
        expect(groupLayout.nodes.some((item) => item.id === page.id)).toBe(true);
      }
      // Interaction 4 is the lock/read itself.
    });
  });

  it("derives group keys from the page record alone (auto-drill contract)", () => {
    const page = { moc_parent: "memories/financeiro/faturas.md", page_type: "decision", freshness_state: "fresh", approved_state: "approved", risk_flags: [] };
    // Atlas keys are hierarchical so sibling folder/index.md hubs never collide.
    expect(groupKeyForPage("atlas", page)).toBe("memories~financeiro~faturas");
    expect(groupKeyForPage("atlas", { ...page, moc_parent: "memories/financeiro/faturas/index.md" })).toBe(
      "memories~financeiro~faturas"
    );
    expect(groupKeyForPage("atlas", { ...page, moc_parent: "memories/system/index.md" })).not.toBe(
      groupKeyForPage("atlas", { ...page, moc_parent: "memories/casa/index.md" })
    );
    expect(groupKeyForPage("districts", page)).toBe("decision");
    expect(groupKeyForPage("radar", page)).toBe("decision");
    expect(groupKeyForPage("radar", { ...page, freshness_state: "stale" })).toBe("atencao");
    expect(groupKeyForPage("trails", page)).toBeUndefined();
    expect(worldLevel({ context: "a", group: "b", pageId: "c" })).toBe(3);
  });

  it("atlas group drills round-trip: the group key a hub emits resolves back to that hub", () => {
    const { nodes, edges } = fixture();
    // Nested sibling index.md hubs — the classic collision case.
    const subHubA = node("wiki-hub", "financeiro", { page_type: "context_hub", path: "memories/financeiro/wiki/index.md" });
    const subHubB = node("banco-hub", "financeiro", { page_type: "context_hub", path: "memories/financeiro/banco/index.md" });
    nodes.push(subHubA, subHubB);
    edges.push(
      { source: "wiki-hub", target: "financeiro-hub", type: "moc_parent", status: "valid", weight: 2 },
      { source: "banco-hub", target: "financeiro-hub", type: "moc_parent", status: "valid", weight: 2 }
    );
    const level1 = computeWorldLayout({ perspective: "atlas", context: "financeiro", nodes, edges, maxNodes: 120, snapshotAt: SNAPSHOT });
    const hubGroups = level1.groups.filter((group) => group.kind === "hub");
    const keys = hubGroups.map((group) => group.key);
    expect(new Set(keys).size).toBe(keys.length); // no duplicate group keys
    hubGroups.forEach((group) => {
      expect(group.drill?.group).toBe(group.key);
      const level2 = computeWorldLayout({
        perspective: "atlas",
        context: "financeiro",
        group: group.key,
        nodes,
        edges,
        maxNodes: 120,
        snapshotAt: SNAPSHOT
      });
      const root = level2.nodes.find((item) => item.isRoot);
      expect(group.memberIds[0]).toBe(root?.id); // drill lands on THAT hub
    });
  });
});
