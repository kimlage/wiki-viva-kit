import { describe, expect, it } from "vitest";
import type { GraphEdge } from "../../../types";
import type { LayoutNode, ScenePerformanceProfile } from "../../../scene/layout";
import type { WorldLayout } from "../../../scene/perspectives";
import {
  edgeControlPointForLayout,
  groupRelationBundlesForLayout,
  relationLanesForLayout,
  selectEvidenceFlowEdges,
  selectSceneEdges,
  superShape
} from "./materials";

describe("superShape", () => {
  it("renders source pages as source records, not generic crystals", () => {
    expect(superShape("source")).toBe("source");
    expect(superShape("source_registry")).toBe("source");
  });

  it("keeps practical page families visually distinct in the base instanced mesh", () => {
    expect(superShape("person")).toBe("totem");
    expect(superShape("meeting")).toBe("spark");
    expect(superShape("action")).toBe("comet");
    expect(superShape("operational_rule")).toBe("slab");
    expect(superShape("claim")).toBe("crystal");
    expect(superShape("context_hub")).toBe("hub");
    expect(superShape("artifact")).toBe("sphere");
  });
});

function node(id: string, patch: Partial<LayoutNode> = {}): LayoutNode {
  return {
    id,
    path: id,
    title: id,
    context: "system",
    page_type: "content",
    freshness_state: "fresh",
    approved_state: "approved",
    risk_flags: [],
    source_ref_count: 0,
    inbound_links: Number(id.replace(/\D/g, "")) || 0,
    outbound_links: 1,
    ageDays: 0,
    overdueRatio: 0,
    isHub: false,
    isRoot: false,
    position: [0, 0, 0],
    scale: 0.2,
    ...patch
  };
}

function layout(nodes: LayoutNode[], patch: Partial<WorldLayout> = {}): WorldLayout {
  return {
    perspective: "quadrants",
    level: 0,
    radial: "shelf",
    nodes,
    wedges: [],
    wedgeKind: "group",
    guides: [],
    groups: [],
    clusterStars: [],
    beacons: [],
    rInner: 1,
    rOuter: 4,
    deadlineF: 0.7,
    unknownR: null,
    totals: { total: nodes.length, shown: nodes.length, hidden: 0 },
    truncated: 0,
    ...patch
  };
}

const profile: ScenePerformanceProfile = {
  quality: "rich",
  maxNodes: 160,
  maxEdges: 120,
  dpr: [1, 1],
  geometrySegments: 16,
  enableIntro: true,
  label: "test"
};

describe("selectSceneEdges", () => {
  it("summarizes ambient root quadrant edges instead of drawing the full hairball", () => {
    const nodes = Array.from({ length: 80 }, (_, index) => node(`n${index}`, { position: [index % 8, 0, Math.floor(index / 8)], isRoot: index === 0 }));
    const edges: GraphEdge[] = nodes.slice(1).flatMap((item, index) => [
      { source: nodes[0].id, target: item.id, type: "source_ref", status: "valid", weight: 1 },
      { source: item.id, target: nodes[index % nodes.length].id, type: "moc_parent", status: "valid", weight: 1 },
      { source: item.id, target: nodes[(index + 5) % nodes.length].id, type: "markdown_link", status: "valid", weight: 1 }
    ]);

    const picked = selectSceneEdges(edges, layout(nodes), new Set(), new Set(), profile, null, new Set());

    expect(picked.length).toBeLessThanOrEqual(8);
    expect(picked.filter((edge) => edge.from.isRoot || edge.to.isRoot)).toHaveLength(1);
    expect(picked.filter((edge) => edge.type === "source_ref")).toHaveLength(1);
    expect(picked.filter((edge) => edge.type === "moc_parent")).toHaveLength(2);
    expect(picked.some((edge) => edge.type === "markdown_link")).toBe(false);
    expect(Math.max(...picked.map((edge) => edge.emphasis))).toBeLessThan(0.5);
  });

  it("routes ambient root quadrant edges around the center instead of through it", () => {
    const from = node("top-left", { position: [-3.2, 0, -3.2] });
    const to = node("bottom-right", { position: [3.2, 0, 3.2] });
    const control = edgeControlPointForLayout({ from, to, type: "source_ref" }, layout([from, to], { rInner: 1.7, rOuter: 7.64 }));

    expect(Math.hypot(control[0], control[2])).toBeGreaterThan(3.1);
    expect(control[1]).toBeGreaterThan(1.2);
  });

  it("keeps focused edges fully readable when the operator hovers or selects a node", () => {
    const nodes = Array.from({ length: 12 }, (_, index) => node(`n${index}`, { position: [index, 0, index % 2] }));
    const edges: GraphEdge[] = nodes.slice(1).map((item) => ({
      source: nodes[0].id,
      target: item.id,
      type: "source_ref",
      status: "valid",
      weight: 1
    }));

    const picked = selectSceneEdges(edges, layout(nodes), new Set(["n0"]), new Set(), profile, null, new Set());

    expect(picked).toHaveLength(edges.length);
    expect(picked.every((edge) => edge.emphasis === 1)).toBe(true);
  });

  it("bundles ambient family drill relations so source groups do not become a line hairball", () => {
    const center = node("region:pratica:family:source", {
      isGroup: true,
      isRoot: true,
      groupKind: "region_family",
      groupLabelKey: "source",
      position: [0, 0, 0],
      scale: 1
    });
    const children = Array.from({ length: 90 }, (_, index) =>
      node(`source-${index}`, { page_type: "source", position: [Math.cos(index) * 4, 0, Math.sin(index) * 4] })
    );
    const nodes = [center, ...children];
    const edges: GraphEdge[] = children.flatMap((item, index) => [
      { source: item.id, target: children[(index + 1) % children.length].id, type: "source_ref", status: "valid", weight: 1 },
      { source: item.id, target: children[(index + 7) % children.length].id, type: "ingestion_chain", status: "valid", weight: 1 },
      { source: item.id, target: children[(index + 13) % children.length].id, type: "markdown_link", status: "valid", weight: 1 },
      { source: item.id, target: children[(index + 19) % children.length].id, type: "moc_parent", status: "valid", weight: 1 }
    ]);

    const picked = selectSceneEdges(
      edges,
      layout(nodes, { level: 2, group: "region:pratica:family:source" }),
      new Set(),
      new Set(),
      profile,
      null,
      new Set()
    );

    expect(picked.length).toBeLessThanOrEqual(10);
    expect(picked.filter((edge) => edge.type === "source_ref")).toHaveLength(4);
    expect(picked.filter((edge) => edge.type === "ingestion_chain")).toHaveLength(3);
    expect(picked.some((edge) => edge.type === "markdown_link")).toBe(false);
    expect(Math.max(...picked.map((edge) => edge.emphasis))).toBeLessThan(0.38);
  });

  it("summarizes visible quadrant drill relations as semantic lanes", () => {
    const center = node("region:pratica", {
      isGroup: true,
      isRoot: true,
      groupKind: "quadrant",
      groupLabelKey: "pratica",
      position: [0, 0, 0],
      scale: 1
    });
    const children = Array.from({ length: 12 }, (_, index) =>
      node(`source-${index}`, { page_type: index % 2 === 0 ? "source" : "event", position: [Math.cos(index), 0, Math.sin(index)] })
    );
    const edges: GraphEdge[] = [
      ...children.slice(0, 8).map((item, index) => ({
        source: item.id,
        target: children[(index + 1) % children.length].id,
        type: "source_ref",
        status: "valid",
        weight: 1
      })),
      ...children.slice(0, 4).map((item, index) => ({
        source: item.id,
        target: children[(index + 3) % children.length].id,
        type: "ingestion_chain",
        status: "valid",
        weight: 1
      })),
      ...children.slice(0, 10).map((item, index) => ({
        source: item.id,
        target: children[(index + 5) % children.length].id,
        type: "markdown_link",
        status: "valid",
        weight: 1
      }))
    ];

    const lanes = relationLanesForLayout(edges, layout([center, ...children], { level: 1, group: "region:pratica" }));

    expect(lanes.map((lane) => lane.type)).toEqual(["source_ref", "ingestion_chain"]);
    expect(lanes[0]).toMatchObject({ count: 8 });
    expect(lanes[0].share).toBeCloseTo(8 / 12);
  });

  it("bundles root overview relations between visible family groups", () => {
    const root = node("root", { isRoot: true, page_type: "root_entity", position: [0, 0, 0] });
    const sourceGroup = node("region:pratica:family:source", {
      isGroup: true,
      groupKind: "region_family",
      groupLabelKey: "source",
      groupMemberIds: ["source-a", "source-b"],
      position: [3, 0, -3],
      scale: 0.6
    });
    const eventGroup = node("region:pratica:family:event", {
      isGroup: true,
      groupKind: "region_family",
      groupLabelKey: "event",
      groupMemberIds: ["event-a", "event-b"],
      position: [4, 0, -2],
      scale: 0.6
    });
    const actionGroup = node("region:sistemas:family:action", {
      isGroup: true,
      groupKind: "region_family",
      groupLabelKey: "action",
      groupMemberIds: ["action-a"],
      position: [4, 0, 3],
      scale: 0.6
    });
    const edges: GraphEdge[] = [
      { source: "source-a", target: "event-a", type: "source_ref", status: "valid", weight: 1 },
      { source: "source-b", target: "event-b", type: "source_ref", status: "valid", weight: 1 },
      { source: "event-a", target: "source-a", type: "ingestion_chain", status: "valid", weight: 1 },
      { source: "source-a", target: "action-a", type: "pr_impact", status: "valid", weight: 1 },
      { source: "source-a", target: "source-b", type: "source_ref", status: "valid", weight: 1 },
      { source: "source-b", target: "outside", type: "source_ref", status: "valid", weight: 1 },
      { source: "source-a", target: "event-a", type: "markdown_link", status: "valid", weight: 1 }
    ];

    const bundles = groupRelationBundlesForLayout(edges, layout([root, sourceGroup, eventGroup, actionGroup], { level: 0 }), 4);

    expect(bundles.map((bundle) => bundle.key)).toEqual([
      "region:pratica:family:source->region:pratica:family:event:source_ref",
      "region:pratica:family:source->region:sistemas:family:action:pr_impact"
    ]);
    expect(bundles[0]).toMatchObject({ type: "source_ref", count: 3, incoming: 1, outgoing: 2, flow: "mixed" });
    expect(bundles[0].share).toBeCloseTo(3 / 4);
    expect(bundles[0].from).toEqual(sourceGroup.position);
    expect(bundles[0].to).toEqual(eventGroup.position);
  });

  it("draws group-to-group relation bundles from hidden member relationships", () => {
    const centerMembers = ["source-a", "source-b", "event-a", "event-b", "action-a"];
    const center = node("region:pratica", {
      isGroup: true,
      isRoot: true,
      groupKind: "quadrant",
      groupLabelKey: "pratica",
      groupMemberIds: centerMembers,
      position: [0, 0, 0],
      scale: 1
    });
    const sourceGroup = node("region:pratica:family:source", {
      isGroup: true,
      groupKind: "region_family",
      groupLabelKey: "source",
      groupMemberIds: ["source-a", "source-b"],
      position: [1.6, 0, 0.4],
      scale: 0.6
    });
    const eventGroup = node("region:pratica:family:event", {
      isGroup: true,
      groupKind: "region_family",
      groupLabelKey: "event",
      groupMemberIds: ["event-a", "event-b"],
      position: [-1.3, 0, 0.8],
      scale: 0.6
    });
    const edges: GraphEdge[] = [
      { source: "source-a", target: "event-a", type: "source_ref", status: "valid", weight: 1 },
      { source: "source-b", target: "event-b", type: "source_ref", status: "valid", weight: 1 },
      { source: "source-a", target: "action-a", type: "ingestion_chain", status: "valid", weight: 1 },
      { source: "source-a", target: "source-b", type: "source_ref", status: "valid", weight: 1 },
      { source: "event-a", target: "event-b", type: "moc_parent", status: "valid", weight: 1 },
      { source: "source-b", target: "outside", type: "pr_impact", status: "valid", weight: 1 }
    ];

    const bundles = groupRelationBundlesForLayout(
      edges,
      layout([center, sourceGroup, eventGroup], { level: 1, group: "region:pratica" })
    );

    expect(bundles.map((bundle) => bundle.targetId)).toEqual(["region:pratica:family:source", "region:pratica:family:event"]);
    expect(bundles[0]).toMatchObject({ type: "source_ref", count: 4, incoming: 3, outgoing: 0, flow: "in" });
    expect(bundles[1]).toMatchObject({ type: "source_ref", count: 2, incoming: 0, outgoing: 2, flow: "out" });
    expect(bundles[0].share).toBeCloseTo(4 / 6);
    expect(bundles[0].from).toEqual([0, 0, 0]);
    expect(bundles[0].to).toEqual([1.6, 0, 0.4]);
  });

  it("does not render relation lanes in the root overview", () => {
    const nodes = [node("a"), node("b")];
    const edges: GraphEdge[] = [{ source: "a", target: "b", type: "source_ref", status: "valid", weight: 1 }];

    expect(relationLanesForLayout(edges, layout(nodes, { level: 0 }))).toEqual([]);
  });

  it("keeps page drill sparse even when the center page has quadrant children", () => {
    const center = node("hub-custos", {
      isRoot: true,
      page_type: "context_hub",
      position: [0, 0, 0],
      inbound_links: 26,
      outbound_links: 21
    });
    const groups = ["intencao", "pratica", "relacoes", "sistemas"].map((facet, index) =>
      node(`region:${facet}`, {
        isGroup: true,
        groupKind: "quadrant",
        groupLabelKey: facet,
        position: [Math.cos(index) * 3, 0, Math.sin(index) * 3],
        groupMemberIds: [`p-${index}`]
      })
    );
    const pages = Array.from({ length: 28 }, (_, index) =>
      node(`p-${index}`, { position: [Math.cos(index) * 2, 0, Math.sin(index) * 2] })
    );
    const nodes = [center, ...groups, ...pages];
    const edges: GraphEdge[] = pages.flatMap((item, index) => [
      { source: center.id, target: item.id, type: index % 2 === 0 ? "source_ref" : "moc_parent", status: "valid", weight: 1 },
      { source: item.id, target: pages[(index + 1) % pages.length].id, type: "markdown_link", status: "valid", weight: 1 }
    ]);
    const pageLayout = layout(nodes, { level: 3, group: "region:pratica" });

    const picked = selectSceneEdges(edges, pageLayout, new Set(), new Set(), profile, null, new Set());

    expect(picked.length).toBeLessThanOrEqual(6);
    expect(picked.some((edge) => edge.type === "markdown_link")).toBe(false);
    expect(relationLanesForLayout(edges, pageLayout)).toEqual([]);
    expect(groupRelationBundlesForLayout(edges, pageLayout)).toEqual([]);
  });

  it("keeps focused family drill relations readable for inspection", () => {
    const nodes = Array.from({ length: 18 }, (_, index) => node(`source-${index}`, { page_type: "source", position: [index, 0, 0] }));
    const edges: GraphEdge[] = nodes.slice(1).map((item) => ({
      source: nodes[0].id,
      target: item.id,
      type: "source_ref",
      status: "valid",
      weight: 1
    }));

    const picked = selectSceneEdges(
      edges,
      layout(nodes, { level: 2, group: "region:pratica:family:source" }),
      new Set(["source-0"]),
      new Set(),
      profile,
      null,
      new Set()
    );

    expect(picked).toHaveLength(edges.length);
    expect(picked.every((edge) => edge.emphasis === 1)).toBe(true);
  });

  it("promotes ambient evidence relations into sparse visual flow pulses", () => {
    const nodes = Array.from({ length: 18 }, (_, index) =>
      node(`n${index}`, {
        position: [Math.cos(index) * 3, 0, Math.sin(index) * 3],
        page_type: index % 3 === 0 ? "source" : "content",
        source_ref_count: index % 3 === 0 ? 4 : 0
      })
    );
    const edges: GraphEdge[] = nodes.slice(1).flatMap((item, index) => [
      { source: nodes[0].id, target: item.id, type: "source_ref", status: "valid", weight: 1 },
      { source: item.id, target: nodes[(index + 2) % nodes.length].id, type: "ingestion_chain", status: "valid", weight: 1 },
      { source: item.id, target: nodes[(index + 5) % nodes.length].id, type: "markdown_link", status: "valid", weight: 1 }
    ]);
    const rootLayout = layout(nodes, { level: 0 });
    const picked = selectSceneEdges(edges, rootLayout, new Set(), new Set(), profile, null, new Set());
    const flows = selectEvidenceFlowEdges(picked, rootLayout, "rich");

    expect(flows.length).toBeGreaterThan(0);
    expect(flows.length).toBeLessThanOrEqual(10);
    expect(flows.every((edge) => edge.type === "source_ref" || edge.type === "ingestion_chain")).toBe(true);
    expect(flows.some((edge) => edge.type === "ingestion_chain")).toBe(true);
  });

  it("keeps evidence flow pulses capped in dense family drill views", () => {
    const center = node("region:pratica:family:source", {
      isGroup: true,
      isRoot: true,
      groupKind: "region_family",
      groupLabelKey: "source",
      position: [0, 0, 0],
      scale: 1
    });
    const children = Array.from({ length: 60 }, (_, index) =>
      node(`source-${index}`, {
        page_type: "source",
        position: [Math.cos(index) * 4, 0, Math.sin(index) * 4],
        source_ref_count: 3
      })
    );
    const nodes = [center, ...children];
    const edges: GraphEdge[] = children.flatMap((item, index) => [
      { source: item.id, target: children[(index + 1) % children.length].id, type: "source_ref", status: "valid", weight: 1 },
      { source: item.id, target: children[(index + 9) % children.length].id, type: "ingestion_chain", status: "valid", weight: 1 },
      { source: item.id, target: children[(index + 13) % children.length].id, type: "markdown_link", status: "valid", weight: 1 }
    ]);
    const familyLayout = layout(nodes, { level: 2, group: "region:pratica:family:source" });
    const picked = selectSceneEdges(edges, familyLayout, new Set(), new Set(), profile, null, new Set());
    const flows = selectEvidenceFlowEdges(picked, familyLayout, "rich");

    expect(flows.length).toBeLessThanOrEqual(6);
    expect(flows.every((edge) => edge.type !== "markdown_link")).toBe(true);
    expect(flows.map((edge) => `${edge.from.id}->${edge.to.id}:${edge.type}`)).toEqual(
      [...flows].map((edge) => `${edge.from.id}->${edge.to.id}:${edge.type}`)
    );
  });

  it("does not invent evidence flow pulses from hierarchy or regular links", () => {
    const nodes = [node("a"), node("b"), node("c")];
    const edges: GraphEdge[] = [
      { source: "a", target: "b", type: "moc_parent", status: "valid", weight: 1 },
      { source: "b", target: "c", type: "markdown_link", status: "valid", weight: 1 }
    ];
    const picked = selectSceneEdges(edges, layout(nodes), new Set(), new Set(), profile, null, new Set());

    expect(selectEvidenceFlowEdges(picked, layout(nodes), "rich")).toEqual([]);
  });
});
