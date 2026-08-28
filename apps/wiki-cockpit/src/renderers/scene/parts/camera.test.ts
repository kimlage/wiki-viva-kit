import { describe, expect, it } from "vitest";
import {
  centeredCollectionCameraTheta,
  centeredGroupCameraDistance,
  centeredGroupCameraLift,
  centeredGroupCameraPhi,
  centeredGroupSafeAreaDistanceMultiplier,
  hoverInspectionCameraTarget,
  hoverInspectionCameraWeight,
  hoverInspectionDistanceMultiplier,
  travelThetaFromWorldPoint
} from "./camera";
import type { LayoutNode } from "../../../scene/layout";
import type { WorldLayout } from "../../../scene/perspectives";

function quadrantLayout(scale: number, level: 1 | 2, memberCount = 1): WorldLayout {
  return {
    perspective: "quadrants",
    level,
    group: level === 1 ? "region:pratica" : "region:pratica:family:source",
    radial: "orbit",
    nodes: [
      {
        id: level === 1 ? "region:pratica" : "region:pratica:family:source",
        path: level === 1 ? "region:pratica" : "region:pratica:family:source",
        title: "Outputs & evidence",
        context: "system",
        page_type: level === 1 ? "visual_group_region" : "visual_group_source",
        freshness_state: "fresh",
        approved_state: "approved",
        risk_flags: [],
        source_ref_count: 0,
        inbound_links: 0,
        outbound_links: 0,
        ageDays: 0,
        overdueRatio: 0,
        isHub: true,
        isRoot: true,
        position: [0, 0, 0],
        scale,
        isGroup: true,
        groupKind: level === 1 ? "quadrant" : "region_family",
        groupMemberIds: Array.from({ length: memberCount }, (_, index) => `member-${index}`)
      }
    ],
    wedges: [],
    wedgeKind: "group",
    guides: [],
    groups: [],
    clusterStars: [],
    beacons: [],
    rInner: 1.7,
    rOuter: 3.6,
    deadlineF: 0.7,
    unknownR: null,
    totals: { total: 1, shown: 1, hidden: 0 },
    truncated: 0
  };
}

function layoutNode(overrides: Partial<LayoutNode> & Pick<LayoutNode, "id">): LayoutNode {
  const { id, ...rest } = overrides;
  return {
    id,
    path: overrides.path ?? id,
    title: overrides.title ?? id,
    context: overrides.context ?? "system",
    page_type: overrides.page_type ?? "artifact",
    freshness_state: overrides.freshness_state ?? "fresh",
    approved_state: overrides.approved_state ?? "approved",
    risk_flags: overrides.risk_flags ?? [],
    source_ref_count: overrides.source_ref_count ?? 0,
    inbound_links: overrides.inbound_links ?? 0,
    outbound_links: overrides.outbound_links ?? 0,
    ageDays: overrides.ageDays ?? 0,
    overdueRatio: overrides.overdueRatio ?? 0,
    isHub: overrides.isHub ?? false,
    isRoot: overrides.isRoot ?? false,
    position: overrides.position ?? [0, 0, 0],
    scale: overrides.scale ?? 0.2,
    ...rest
  };
}

describe("quadrant camera travel", () => {
  it("aims drill travel from the selected object's previous world position", () => {
    expect(travelThetaFromWorldPoint([0, 0, -3])).toBeCloseTo(0);
    expect(travelThetaFromWorldPoint([3, 0, 0])).toBeCloseTo(-Math.PI / 2);
    expect(travelThetaFromWorldPoint([0, 0, 0])).toBeNull();
  });

  it("lifts the camera target onto the centered group body during quadrant drill", () => {
    expect(centeredGroupCameraLift(quadrantLayout(0.62, 1))).toBeGreaterThan(0.36);
    expect(centeredGroupCameraLift({ ...quadrantLayout(0.62, 1), perspective: "radar", level: 0 })).toBe(0);
  });

  it("keeps enough distance to see the central group and its surrounding drill context", () => {
    const shallow = centeredGroupCameraDistance(quadrantLayout(0.62, 1), 8);
    const deep = centeredGroupCameraDistance(quadrantLayout(0.7, 2), 8);

    expect(shallow).toBeGreaterThan(5.2);
    expect(deep).toBeGreaterThan(5.5);
    expect(deep).toBeGreaterThan(0.7 * 3.25 * 3.4);
  });

  it("centers a real-page family collection after travelling from its quadrant", () => {
    const layout = quadrantLayout(0.46, 2, 13);
    layout.group = "family:source";
    layout.nodes = [
      layoutNode({ id: "root-alex-rivera", isRoot: true, isHub: true, scale: 0.46 }),
      ...Array.from({ length: 13 }, (_, index) => layoutNode({ id: `source-${index}`, page_type: "source" }))
    ];

    expect(centeredCollectionCameraTheta(layout, -Math.PI / 2)).toBe(0);
    expect(centeredGroupCameraLift(layout)).toBeGreaterThan(0);
    expect(centeredGroupCameraDistance(layout, 9)).toBeGreaterThanOrEqual(5.8);
    expect(centeredGroupCameraDistance(layout, 9)).toBeLessThan(9);
  });

  it("adds bounded safe-area breathing room for dense grouped drills", () => {
    const sparse = quadrantLayout(0.7, 2, 8);
    const dense = quadrantLayout(0.7, 2, 45);
    const nonQuadrant: WorldLayout = { ...dense, perspective: "radar", level: 0 };

    expect(centeredGroupSafeAreaDistanceMultiplier(sparse)).toBe(1);
    expect(centeredGroupSafeAreaDistanceMultiplier(dense)).toBeGreaterThan(1);
    expect(centeredGroupSafeAreaDistanceMultiplier(dense)).toBeGreaterThan(1.2);
    expect(centeredGroupSafeAreaDistanceMultiplier(dense)).toBeLessThanOrEqual(1.34);
    expect(centeredGroupSafeAreaDistanceMultiplier(nonQuadrant)).toBe(1);
    expect(centeredGroupCameraDistance(dense, 8)).toBeGreaterThan(centeredGroupCameraDistance(sparse, 8));
    expect(centeredGroupCameraPhi(dense)).toBeLessThan(centeredGroupCameraPhi(sparse));
    expect(centeredGroupCameraPhi(dense)).toBeLessThan(0.7);
  });

  it("keeps hover as inspection only and never biases the camera", () => {
    const center = quadrantLayout(0.7, 2, 42);
    const navigable = layoutNode({
      id: "region:pratica:family:event",
      page_type: "visual_group_event",
      isGroup: true,
      groupDrill: { group: "region:pratica:family:event" },
      position: [3, 0.2, -1],
      scale: 0.36
    });
    const conceptual = layoutNode({
      id: "region:sistemas",
      page_type: "visual_group_region",
      isGroup: true,
      position: [-2, 0, 1],
      scale: 0.32
    });
    const practicalPage = layoutNode({
      id: "source-a",
      page_type: "source",
      source_ref_count: 12,
      position: [1.5, 0, 2],
      scale: 0.22
    });
    const root = layoutNode({
      id: "region:pratica:family:source",
      isRoot: true,
      isGroup: true
    });

    expect(hoverInspectionCameraWeight(center, navigable)).toBe(0);
    expect(hoverInspectionCameraWeight(center, conceptual)).toBe(0);
    expect(hoverInspectionCameraWeight(center, practicalPage)).toBe(0);
    expect(hoverInspectionCameraWeight(quadrantLayout(0.7, 1, 42), practicalPage)).toBe(0);
    expect(hoverInspectionCameraWeight({ ...center, perspective: "radar", level: 0 }, navigable)).toBe(0);
    expect(hoverInspectionCameraWeight(center, root)).toBe(0);

    expect(hoverInspectionCameraTarget(center, navigable)).toBeNull();
    expect(hoverInspectionDistanceMultiplier(center, navigable)).toBe(1);
    expect(hoverInspectionDistanceMultiplier(center, conceptual)).toBe(1);
    expect(hoverInspectionDistanceMultiplier(center, root)).toBe(1);
  });
});
