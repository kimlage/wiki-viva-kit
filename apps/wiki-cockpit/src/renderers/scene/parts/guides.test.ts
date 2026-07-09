import { describe, expect, it } from "vitest";
import {
  trustColor,
} from "../../../data/presentation";
import {
  aggregateStateRimSpec,
  densityPressureSpec,
  densityReliefSpec,
  focusContextSpec,
  groupRelationBundleVisualSpec,
  hiddenDepthHaloSpec,
  inspectionBeamSpecs,
  drillContextTetherCurvePoints,
  drillContextTetherSpecs,
  drillOriginEchoSpec,
  drillWaypointSpecs,
  parentDrillGateSpec,
  parentDrillPathCurvePoints,
  travelWakeCurvePoints,
  travelWakeLevel
} from "./guides";
import type { WorldLayout } from "../../../scene/perspectives";

function layout(level: number): WorldLayout {
  return {
    perspective: "quadrants",
    level,
    group: level >= 2 ? "region:pratica:family:source" : level >= 1 ? "region:pratica" : undefined,
    radial: level >= 1 ? "orbit" : "shelf",
    nodes: [
      {
        id: level >= 1 ? "region:pratica" : "root",
        path: level >= 1 ? "region:pratica" : "root",
        title: level >= 1 ? "Outputs & evidence" : "Root",
        context: "system",
        page_type: level >= 1 ? "visual_group_region" : "root_entity",
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
        scale: 0.6,
        ...(level >= 1 ? { isGroup: true, groupKind: "quadrant", groupMemberIds: ["a"] } : {})
      }
    ],
    wedges: [],
    wedgeKind: "group",
    guides: [],
    groups: [],
    clusterStars: [],
    beacons: [],
    rInner: 1.7,
    rOuter: level >= 1 ? 3.6 : 5,
    deadlineF: 0.7,
    unknownR: null,
    totals: { total: 1, shown: 1, hidden: 0 },
    truncated: 0
  };
}

describe("travelWakeCurvePoints", () => {
  it("scales relation corridors by real bundle mass", () => {
    const weak = groupRelationBundleVisualSpec({ count: 1, share: 0.05 });
    const strong = groupRelationBundleVisualSpec({ count: 36, share: 0.75 });

    expect(strong.tubeRadius).toBeGreaterThan(weak.tubeRadius);
    expect(strong.haloRadius).toBeGreaterThan(weak.haloRadius);
    expect(strong.beadCount).toBeGreaterThan(weak.beadCount);
    expect(strong.opacity).toBeGreaterThan(weak.opacity);
  });

  it("keeps the clicked object and new center as the endpoints", () => {
    const points = travelWakeCurvePoints([3, 0, 0], [0, 0, 0], 1);

    expect(points[0].toArray()).toEqual([3, 0, 0]);
    expect(points[points.length - 1].toArray()).toEqual([0, 0, 0]);
    expect(Math.max(...points.map((point) => point.y))).toBeGreaterThan(0.26);
  });

  it("uses a taller arc for deeper drills", () => {
    const shallow = travelWakeCurvePoints([2, 0, 0], [0, 0, 0], 1);
    const deep = travelWakeCurvePoints([2, 0, 0], [0, 0, 0], 2);

    expect(Math.max(...deep.map((point) => point.y))).toBeGreaterThanOrEqual(
      Math.max(...shallow.map((point) => point.y))
    );
  });

  it("keeps page-focus travel wakes visible even from a level-zero overview", () => {
    expect(travelWakeLevel(0, false)).toBe(0);
    expect(travelWakeLevel(0, true)).toBe(1);
    expect(travelWakeLevel(2, true)).toBe(2);
  });

  it("does not render a parent gate before drilling into the quadrant world", () => {
    expect(parentDrillGateSpec(layout(0), [3, 0, 0])).toBeNull();
  });

  it("renders a typed echo of the object that became the centered group", () => {
    const region = drillOriginEchoSpec(layout(1), [2.3, -0.02, -2.3]);
    const source = drillOriginEchoSpec(
      {
        ...layout(2),
        nodes: [
          {
            ...layout(2).nodes[0],
            id: "region:pratica:family:source",
            path: "region:pratica:family:source",
            page_type: "visual_group_source",
            groupKind: "region_family",
            groupLabelKey: "source"
          }
        ]
      },
      [1.8, 0, -1.4]
    );

    expect(drillOriginEchoSpec(layout(0), [2.3, -0.02, -2.3])).toBeNull();
    expect(region).toMatchObject({ family: "region", position: [2.3, 0.08, -2.3] });
    expect(source).toMatchObject({ family: "source", position: [1.8, 0.08, -1.4] });
    expect(source!.radius).toBeGreaterThan(0.2);
  });

  it("places the parent gate on the incoming drill vector", () => {
    const spec = parentDrillGateSpec(layout(1), [3, 0, 0]);

    expect(spec).not.toBeNull();
    expect(spec!.position[0]).toBeGreaterThan(4);
    expect(Math.abs(spec!.position[2])).toBeLessThan(0.01);
    expect(spec!.radius).toBeCloseTo(0.36);
  });

  it("falls back to a stable rear gate when the entry vector is unavailable", () => {
    const spec = parentDrillGateSpec(layout(2), null);

    expect(spec).not.toBeNull();
    expect(spec!.position[2]).toBeLessThan(-4);
    expect(spec!.radius).toBeCloseTo(0.42);
  });

  it("renders density pressure only for materially dense grouped drills", () => {
    expect(densityPressureSpec(layout(0))).toBeNull();
    expect(densityPressureSpec(layout(1))).toBeNull();

    const dense = {
      ...layout(2),
      nodes: [
        {
          ...layout(2).nodes[0],
          groupKind: "region_family",
          groupLabelKey: "source",
          groupMemberIds: Array.from({ length: 46 }, (_, index) => `source-${index}`)
        }
      ],
      clusterStars: [
        {
          key: "hidden-sources",
          kind: "region_family" as const,
          labelKey: "source",
          count: 34,
          position: [0, 0, 3] as [number, number, number],
          scale: 0.4,
          histogram: { fresh: 12, stale: 4, unknown: 18, proposal: 0, risk: 1 },
          drill: null
        }
      ]
    };
    const spec = densityPressureSpec(dense);

    expect(spec).not.toBeNull();
    expect(spec!.memberCount).toBe(46);
    expect(spec!.hiddenCount).toBe(34);
    expect(spec!.intensity).toBeGreaterThan(0.7);
    expect(spec!.markerCount).toBeGreaterThan(20);
    expect(spec!.color).toBe("#5ee6b7");
  });

  it("adds an occlusion-relief lens only when dense grouped drills need contrast", () => {
    expect(densityReliefSpec(layout(0))).toBeNull();
    expect(densityReliefSpec(layout(1))).toBeNull();

    const dense = {
      ...layout(2),
      nodes: [
        {
          ...layout(2).nodes[0],
          id: "region:pratica:family:source",
          path: "region:pratica:family:source",
          page_type: "visual_group_source",
          groupKind: "region_family",
          groupLabelKey: "source",
          groupMemberIds: Array.from({ length: 52 }, (_, index) => `source-${index}`)
        }
      ],
      clusterStars: [
        {
          key: "hidden-sources",
          kind: "region_family" as const,
          labelKey: "source",
          count: 28,
          position: [0, 0, 3] as [number, number, number],
          scale: 0.4,
          histogram: { fresh: 10, stale: 6, unknown: 10, proposal: 1, risk: 1 },
          drill: null
        }
      ]
    };
    const pressure = densityPressureSpec(dense)!;
    const relief = densityReliefSpec(dense);

    expect(relief).not.toBeNull();
    expect(relief!.color).toBe(pressure.color);
    expect(relief!.radius).toBeGreaterThan(pressure.radius);
    expect(relief!.opacity).toBeGreaterThan(0.12);
    expect(relief!.gridCount).toBeGreaterThan(12);
  });

  it("turns hidden aggregate state into an attention-first visual rim", () => {
    expect(aggregateStateRimSpec(layout(2))).toBeNull();

    const dense = {
      ...layout(2),
      nodes: [
        {
          ...layout(2).nodes[0],
          id: "region:pratica:family:source",
          path: "region:pratica:family:source",
          page_type: "visual_group_source",
          groupKind: "region_family",
          groupLabelKey: "source",
          groupMemberIds: Array.from({ length: 42 }, (_, index) => `source-${index}`)
        }
      ],
      clusterStars: [
        {
          key: "hidden-sources",
          kind: "region_family" as const,
          labelKey: "source",
          count: 33,
          position: [0, 0, 3] as [number, number, number],
          scale: 0.4,
          histogram: { fresh: 16, stale: 7, unknown: 6, proposal: 2, risk: 2 },
          drill: null
        }
      ]
    };
    const rim = aggregateStateRimSpec(dense);

    expect(rim).not.toBeNull();
    expect(rim!.total).toBe(33);
    expect(rim!.slices.map((slice) => slice.key)).toEqual(["risk", "stale", "proposal", "unknown", "fresh"]);
    expect(rim!.slices[0]).toMatchObject({ key: "risk", color: trustColor("risk"), count: 2 });
    expect(rim!.slices.find((slice) => slice.key === "fresh")!.share).toBeGreaterThan(0.45);
  });

  it("turns hidden grouped mass into a subtle depth halo instead of more labels", () => {
    expect(hiddenDepthHaloSpec(layout(0))).toBeNull();
    expect(hiddenDepthHaloSpec(layout(2))).toBeNull();

    const dense = {
      ...layout(2),
      nodes: [
        {
          ...layout(2).nodes[0],
          id: "region:pratica:family:source",
          path: "region:pratica:family:source",
          page_type: "visual_group_source",
          groupKind: "region_family",
          groupLabelKey: "source",
          groupMemberIds: Array.from({ length: 36 }, (_, index) => `source-${index}`)
        }
      ],
      clusterStars: [
        {
          key: "hidden-sources",
          kind: "region_family" as const,
          labelKey: "source",
          count: 49,
          position: [0, 0, 3] as [number, number, number],
          scale: 0.4,
          histogram: { fresh: 24, stale: 8, unknown: 12, proposal: 3, risk: 2 },
          drill: null
        }
      ],
      truncated: 9
    };
    const halo = hiddenDepthHaloSpec(dense);

    expect(halo).not.toBeNull();
    expect(halo!.hiddenCount).toBe(58);
    expect(halo!.compression).toBeGreaterThan(0.6);
    expect(halo!.layerCount).toBeGreaterThanOrEqual(4);
    expect(halo!.spokeCount).toBeGreaterThanOrEqual(15);
    expect(halo!.color).toBe("#5ee6b7");
    expect(halo!.radius).toBeLessThan(densityPressureSpec(dense)!.radius);
  });

  it("turns hover/lock focus into a compact visual summary of object mass", () => {
    const quiet = {
      ...layout(1).nodes[0],
      id: "quiet-note",
      page_type: "context_note",
      isGroup: false,
      isRoot: false,
      inbound_links: 1,
      outbound_links: 1,
      groupMemberIds: undefined
    };
    const sourced = {
      ...quiet,
      id: "source-record",
      page_type: "source",
      source_ref_count: 42,
      inbound_links: 18,
      risk_flags: ["missing_manifest"]
    };

    const quietSpec = focusContextSpec(quiet, "hover");
    const sourceSpec = focusContextSpec(sourced, "lock");

    expect(focusContextSpec(null, "hover")).toBeNull();
    expect(quietSpec).toMatchObject({ mode: "hover", ringCount: 1 });
    expect(sourceSpec).toMatchObject({ mode: "lock", ringCount: 3, color: trustColor("risk") });
    expect(sourceSpec!.tickCount).toBeGreaterThan(quietSpec!.tickCount);
    expect(sourceSpec!.radius).toBeGreaterThan(quietSpec!.radius);
  });

  it("turns hover inspection into practical evidence/risk/link beams", () => {
    const quiet = {
      ...layout(1).nodes[0],
      id: "quiet-note",
      page_type: "context_note",
      isGroup: false,
      isRoot: false,
      inbound_links: 0,
      outbound_links: 0,
      source_ref_count: 0,
      risk_flags: []
    };
    const noisy = {
      ...quiet,
      id: "source-with-risk",
      page_type: "source",
      inbound_links: 9,
      outbound_links: 5,
      source_ref_count: 25,
      risk_flags: ["missing_manifest", "stale_source"],
      freshness_state: "stale" as const
    };
    const group = {
      ...layout(2).nodes[0],
      id: "region:pratica:family:source",
      page_type: "visual_group_source",
      isGroup: true,
      groupMemberIds: Array.from({ length: 36 }, (_, index) => `source-${index}`)
    };

    expect(inspectionBeamSpecs(null)).toEqual([]);
    expect(inspectionBeamSpecs(quiet)).toEqual([]);
    expect(inspectionBeamSpecs(noisy).map((spec) => spec.key)).toEqual(["evidence", "links", "risk", "freshness"]);
    expect(inspectionBeamSpecs(noisy).find((spec) => spec.key === "evidence")!.spokeCount).toBeGreaterThan(10);
    expect(inspectionBeamSpecs(noisy).find((spec) => spec.key === "risk")!.color).toBe(trustColor("risk"));
    expect(inspectionBeamSpecs(group).map((spec) => spec.key)).toContain("group");
    expect(inspectionBeamSpecs(group).find((spec) => spec.key === "group")!.spokeCount).toBeGreaterThan(15);
  });

  it("does not draw a persistent parent path at the quadrant root", () => {
    expect(parentDrillPathCurvePoints(layout(0), [3, 0, 0])).toEqual([]);
  });

  it("keeps the parent gate and current center as persistent path endpoints", () => {
    const gate = parentDrillGateSpec(layout(1), [3, 0, 0]);
    const points = parentDrillPathCurvePoints(layout(1), [3, 0, 0]);

    expect(gate).not.toBeNull();
    expect(points[0].x).toBeCloseTo(gate!.position[0]);
    expect(points[0].z).toBeCloseTo(gate!.position[2]);
    expect(points[points.length - 1].x).toBeCloseTo(0);
    expect(points[points.length - 1].z).toBeCloseTo(0);
  });

  it("raises the persistent parent path above both endpoints", () => {
    const points = parentDrillPathCurvePoints(layout(2), null);
    const endpointY = Math.max(points[0].y, points[points.length - 1].y);

    expect(Math.max(...points.map((point) => point.y))).toBeGreaterThan(endpointY);
  });

  it("draws context tethers from the centered drill group to real surrounding groups", () => {
    const drillLayout: WorldLayout = {
      ...layout(2),
      nodes: [
        {
          ...layout(2).nodes[0],
          id: "region:pratica:family:source",
          path: "region:pratica:family:source",
          title: "Sources",
          page_type: "visual_group_source",
          groupKind: "region_family",
          groupLabelKey: "source",
          groupMemberIds: Array.from({ length: 32 }, (_, index) => `source-${index}`)
        },
        {
          ...layout(2).nodes[0],
          id: "region:pratica:family:event",
          path: "region:pratica:family:event",
          title: "Events",
          isRoot: false,
          page_type: "visual_group_event",
          groupKind: "region_family",
          groupLabelKey: "event",
          groupMemberIds: Array.from({ length: 9 }, (_, index) => `event-${index}`),
          position: [2.2, 0, 0.6],
          ring: 1
        },
        {
          ...layout(2).nodes[0],
          id: "region:sistemas",
          path: "region:sistemas",
          title: "Systems",
          isRoot: false,
          page_type: "visual_group_region",
          groupKind: "quadrant",
          groupLabelKey: "sistemas",
          groupMemberIds: Array.from({ length: 18 }, (_, index) => `system-${index}`),
          position: [-2.6, -0.08, 1.8],
          ring: 3
        }
      ]
    };

    const specs = drillContextTetherSpecs(drillLayout);

    expect(drillContextTetherSpecs(layout(0))).toEqual([]);
    expect(specs.map((spec) => spec.targetId)).toEqual(["region:pratica:family:event", "region:sistemas"]);
    expect(specs[0]).toMatchObject({ satelliteKind: "family", from: [0, 0, 0], to: [2.2, 0, 0.6] });
    expect(specs[0].beadCount).toBeGreaterThanOrEqual(specs[1].beadCount);
    expect(specs[0].opacity).toBeGreaterThan(specs[1].opacity);
  });

  it("marks only real drillable satellite groups as low-obstruction navigation waypoints", () => {
    const drillLayout: WorldLayout = {
      ...layout(2),
      nodes: [
        {
          ...layout(2).nodes[0],
          id: "region:pratica:family:source",
          path: "region:pratica:family:source",
          title: "Sources",
          page_type: "visual_group_source",
          groupKind: "region_family",
          groupLabelKey: "source",
          groupMemberIds: Array.from({ length: 32 }, (_, index) => `source-${index}`)
        },
        {
          ...layout(2).nodes[0],
          id: "region:pratica:family:event",
          path: "region:pratica:family:event",
          title: "Events",
          isRoot: false,
          page_type: "visual_group_event",
          groupKind: "region_family",
          groupLabelKey: "event",
          groupMemberIds: Array.from({ length: 16 }, (_, index) => `event-${index}`),
          groupDrill: { group: "region:pratica:family:event" },
          position: [2.2, 0, 0.6],
          scale: 0.4,
          ring: 1
        },
        {
          ...layout(2).nodes[0],
          id: "region:pratica:family:rule",
          path: "region:pratica:family:rule",
          title: "Rules",
          isRoot: false,
          page_type: "visual_group_rule",
          groupKind: "region_family",
          groupLabelKey: "rule",
          groupMemberIds: Array.from({ length: 4 }, (_, index) => `rule-${index}`),
          position: [0.8, 0, -2.1],
          scale: 0.32,
          ring: 2
        },
        {
          ...layout(2).nodes[0],
          id: "region:sistemas",
          path: "region:sistemas",
          title: "Systems",
          isRoot: false,
          page_type: "visual_group_region",
          groupKind: "quadrant",
          groupLabelKey: "sistemas",
          groupMemberIds: Array.from({ length: 18 }, (_, index) => `system-${index}`),
          groupDrill: { group: "region:sistemas" },
          position: [-2.6, -0.08, 1.8],
          scale: 0.36,
          ring: 3
        }
      ]
    };

    const specs = drillWaypointSpecs(drillLayout);

    expect(drillWaypointSpecs(layout(0))).toEqual([]);
    expect(specs.map((spec) => spec.targetId)).toEqual(["region:pratica:family:event", "region:sistemas"]);
    expect(specs[0]).toMatchObject({ satelliteKind: "family", position: [2.2, 0.288, 0.6] });
    expect(specs[0].radius).toBeGreaterThan(specs[1].radius);
    expect(specs[0].tickCount).toBeGreaterThanOrEqual(specs[1].tickCount);
    expect(specs[0].strength).toBeGreaterThan(0.4);
  });

  it("raises context tether curves so surrounding objects remain physically connected", () => {
    const points = drillContextTetherCurvePoints({
      from: [0, 0, 0],
      to: [2, -0.08, 1],
      satelliteKind: "family"
    });
    const endpointY = Math.max(points[0].y, points[points.length - 1].y);

    expect(points[0].toArray()).toEqual([0, 0, 0]);
    expect(points[points.length - 1].toArray()).toEqual([2, -0.08, 1]);
    expect(Math.max(...points.map((point) => point.y))).toBeGreaterThan(endpointY);
  });
});
