import { describe, expect, it } from "vitest";
import {
  centerSignalBadges,
  groupChildOrbitClusterHoverNode,
  groupChildOrbitClusterPoses,
  groupChildOrbitClusterVisualProfile,
  groupChildOrbitEntries,
  groupChildOrbitEntryHitProfile,
  groupChildOrbitEntryScale,
  groupChildOrbitClusterSpread,
  groupChildOrbitDensityExpansion,
  groupChildOrbitIsDense,
  groupChildOrbitLaneSummaries,
  groupChildOrbitPoseMinimumDistance,
  groupCompositionArcs,
  groupContainmentFlows,
  groupDrillGrowthScale,
  groupLandmarkProfile,
  groupShellProfile,
  groupStatusBeacons,
  groupVisualPips,
  semanticDetailFamily,
  semanticDetailEligible,
  semanticDetailLimit,
  semanticDetailNodes,
  semanticDetailSignalScore,
  semanticObjectPrimitive,
  semanticRootBodyPrimitive,
  semanticZoomMarks
} from "./nodes";
import type { LayoutNode } from "../../../scene/layout";
import type { GroupChildOrbitLane } from "./nodes";

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

describe("semantic page details", () => {
  it("derives center visual signals from practical page data and primitive slots", () => {
    const signals = centerSignalBadges(
      layoutNode({
        id: "source-center",
        page_type: "source",
        isRoot: true,
        source_ref_count: 42,
        risk_flags: ["missing_manifest"],
        approved_state: "proposal",
        freshness_state: "stale",
        overdueRatio: 1.6
      }),
      {
        visual_grammar: {
          default_pack: "evidence_first",
          packs: {
            evidence_first: {
              slots: {
                "reader.badge": "source_badge"
              }
            }
          }
        }
      } as never
    );

    expect(signals).toHaveLength(4);
    expect(signals.map((signal) => signal.primitive)).toContain("source_badge");
    expect(signals.map((signal) => signal.primitive)).toContain("risk_notch");
    expect(signals.map((signal) => signal.primitive)).toContain("review_halo");
    expect(signals.map((signal) => signal.primitive)).toContain("attention_rail");
    expect(signals.every((signal) => signal.strength > 0)).toBe(true);
  });

  it("keeps center signals off group objects because groups already have shell grammar", () => {
    expect(
      centerSignalBadges(
        layoutNode({
          id: "region:source",
          page_type: "visual_group_source",
          isGroup: true,
          isRoot: true,
          source_ref_count: 12,
          risk_flags: ["group_attention"]
        })
      )
    ).toEqual([]);
  });

  it("marks action centers with an action primitive instead of a generic sphere cue", () => {
    expect(
      centerSignalBadges(
        layoutNode({
          id: "action-center",
          page_type: "action",
          isRoot: true,
          source_ref_count: 0
        })
      ).map((signal) => signal.primitive)
    ).toEqual(["action_lane", "center_badge"]);
  });

  it("decorates practical page families instead of leaving them as generic bodies", () => {
    expect(semanticDetailFamily("source")).toBe("source");
    expect(semanticDetailFamily("meeting")).toBe("event");
    expect(semanticDetailFamily("action")).toBe("action");
    expect(semanticDetailFamily("person")).toBe("person");
    expect(semanticDetailFamily("operational_rule")).toBe("rule");
    expect(semanticDetailFamily("claim")).toBe("decision");
    expect(semanticDetailFamily("artifact")).toBe("content");
  });

  it("keeps semantic detail density bounded by scene quality", () => {
    expect(semanticDetailLimit("compact")).toBeLessThan(semanticDetailLimit("balanced"));
    expect(semanticDetailLimit("balanced")).toBeLessThan(semanticDetailLimit("rich"));
  });

  it("prioritizes practical semantic signatures by operational salience, not layout order", () => {
    const quiet = Array.from({ length: 36 }, (_, index) =>
      layoutNode({
        id: `quiet-${index}`,
        page_type: "artifact",
        inbound_links: index % 2,
        position: [index, 0, 0]
      })
    );
    const root = layoutNode({
      id: "root-center",
      page_type: "root_entity",
      isRoot: true,
      inbound_links: 1
    });
    const dataSource = layoutNode({
      id: "late-source",
      page_type: "source",
      source_ref_count: 42,
      inbound_links: 8
    });
    const riskyAction = layoutNode({
      id: "late-risk-action",
      page_type: "action",
      risk_flags: ["blocked"],
      freshness_state: "stale"
    });
    const linkedContent = layoutNode({
      id: "linked-content",
      page_type: "artifact",
      source_ref_count: 3,
      inbound_links: 4
    });

    const picked = semanticDetailNodes([...quiet, dataSource, riskyAction, root, linkedContent], "compact");

    expect(picked).toHaveLength(3);
    expect(picked.map((node) => node.id)).toEqual(["late-risk-action", "late-source", "linked-content"]);
    expect(picked.some((node) => node.id === "root-center")).toBe(false);
    expect(picked.some((node) => node.id.startsWith("quiet-"))).toBe(false);
    expect(semanticDetailSignalScore(riskyAction)).toBeGreaterThan(semanticDetailSignalScore(dataSource));
  });

  it("keeps quiet content out of the rich 3D detail layer unless it carries operational signal", () => {
    expect(semanticDetailEligible(layoutNode({ id: "quiet-note", page_type: "artifact" }))).toBe(false);
    expect(semanticDetailEligible(layoutNode({ id: "evidenced-note", page_type: "artifact", source_ref_count: 1 }))).toBe(true);
    expect(semanticDetailEligible(layoutNode({ id: "linked-note", page_type: "context_note", inbound_links: 3 }))).toBe(true);
    expect(semanticDetailEligible(layoutNode({ id: "stale-note", page_type: "artifact", freshness_state: "stale" }))).toBe(true);
    expect(semanticDetailEligible(layoutNode({ id: "person", page_type: "person" }))).toBe(true);
    expect(semanticDetailEligible(layoutNode({ id: "group", page_type: "visual_group_source", isGroup: true }))).toBe(false);
  });

  it("makes an opened source read as the primary data object, not a generic sphere", () => {
    const source = semanticObjectPrimitive(
      layoutNode({
        id: "source-center",
        page_type: "source",
        isRoot: true,
        scale: 0.42,
        source_ref_count: 40,
        inbound_links: 18
      })
    );
    const satellite = semanticObjectPrimitive(
      layoutNode({
        id: "source-satellite",
        page_type: "source",
        scale: 0.42,
        source_ref_count: 2,
        inbound_links: 1
      })
    );

    expect(source).toMatchObject({ family: "source", isPrimary: true });
    expect(satellite).toMatchObject({ family: "source", isPrimary: false });
    expect(source?.primaryScale).toBeGreaterThan((satellite?.primaryScale ?? 0) * 1.6);
    expect(source?.streamCount).toBeGreaterThan(satellite?.streamCount ?? 0);
  });

  it("gives opened practical families distinct root body silhouettes", () => {
    expect(semanticRootBodyPrimitive("source")).toMatchObject({ family: "source", geometry: "source_slab" });
    expect(semanticRootBodyPrimitive("person")).toMatchObject({ family: "person", geometry: "person_totem" });
    expect(semanticRootBodyPrimitive("meeting")).toMatchObject({ family: "event", geometry: "event_ring" });
    expect(semanticRootBodyPrimitive("action")).toMatchObject({ family: "action", geometry: "action_beacon" });
    expect(semanticRootBodyPrimitive("operational_rule")).toMatchObject({ family: "rule", geometry: "rule_plinth" });
    expect(semanticRootBodyPrimitive("context_hub")).toMatchObject({ family: "hub", geometry: "hub_gate" });
    expect(semanticRootBodyPrimitive("claim")).toMatchObject({ family: "decision", geometry: "decision_crystal" });
    expect(semanticRootBodyPrimitive("artifact")).toMatchObject({ family: "content", geometry: "content_sheet" });
    expect(semanticRootBodyPrimitive("root_entity")).toMatchObject({ family: "root", geometry: "sphere" });
  });

  it("turns object state into bounded semantic zoom marks instead of more text", () => {
    const source = semanticZoomMarks(
      layoutNode({
        id: "source-center",
        page_type: "source",
        isRoot: true,
        source_ref_count: 42,
        inbound_links: 18,
        outbound_links: 9,
        risk_flags: ["missing_manifest"],
        approved_state: "proposal",
        freshness_state: "stale",
        overdueRatio: 1.4
      }),
      "balanced"
    );
    const quiet = semanticZoomMarks(
      layoutNode({
        id: "quiet-note",
        page_type: "context_note",
        source_ref_count: 0,
        inbound_links: 1,
        outbound_links: 1
      }),
      "rich"
    );

    expect(source).toHaveLength(5);
    expect(source.map((mark) => mark.key)).toEqual(["risk", "evidence", "stale", "review", "inbound"]);
    expect(source.find((mark) => mark.key === "risk")?.color).toBe("#ff7a8a");
    expect(source.every((mark) => mark.size > 0 && mark.strength > 0)).toBe(true);
    expect(quiet).toEqual([]);
  });
});

describe("group visual object grammar", () => {
  it("turns group composition into bounded mini objects instead of generic repeated dots", () => {
    const pips = groupVisualPips(
      [
        { family: "source", count: 72 },
        { family: "event", count: 18 },
        { family: "action", count: 6 }
      ],
      "content",
      96,
      true
    );

    expect(pips.length).toBeLessThanOrEqual(12);
    expect(pips.filter((pip) => pip.family === "source").length).toBeGreaterThan(pips.filter((pip) => pip.family === "action").length);
    expect(new Set(pips.map((pip) => pip.family))).toEqual(new Set(["source", "event", "action"]));
  });

  it("falls back to the group family when composition is unavailable", () => {
    expect(groupVisualPips(undefined, "hub", 9, false).map((pip) => pip.family)).toEqual(["hub", "hub", "hub"]);
  });

  it("encodes group state as visual beacons on the object shell", () => {
    const beacons = groupStatusBeacons({
      id: "region:pratica",
      path: "region:pratica",
      title: "Outputs & evidence",
      context: "system",
      page_type: "visual_group_region",
      freshness_state: "stale",
      approved_state: "proposal",
      risk_flags: ["group_attention"],
      source_ref_count: 12,
      inbound_links: 0,
      outbound_links: 0,
      ageDays: 0,
      overdueRatio: 1.4,
      isHub: true,
      isRoot: true,
      position: [0, 0, 0],
      scale: 0.4,
      isGroup: true
    });

    expect(beacons.map((beacon) => beacon.key)).toEqual(["risk", "stale", "proposal", "evidence"]);
    expect(beacons.find((beacon) => beacon.key === "stale")?.strength).toBeGreaterThan(1);
  });

  it("keeps the centered group structural while compressing dense drill satellites", () => {
    const center = groupShellProfile(
      {
        id: "region:pratica:family:source",
        path: "region:pratica:family:source",
        title: "data sources",
        context: "system",
        page_type: "visual_group_source",
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
        scale: 0.4,
        isGroup: true,
        groupKind: "region_family"
      },
      2
    );
    const satellite = groupShellProfile(
      {
        id: "region:sistema",
        path: "region:sistema",
        title: "Systems",
        context: "system",
        page_type: "visual_group_region",
        freshness_state: "fresh",
        approved_state: "approved",
        risk_flags: [],
        source_ref_count: 4,
        inbound_links: 0,
        outbound_links: 0,
        ageDays: 0,
        overdueRatio: 0,
        isHub: true,
        isRoot: false,
        position: [0, 0, 0],
        scale: 0.4,
        isGroup: true,
        groupKind: "quadrant"
      },
      2
    );

    expect(center).toMatchObject({ center: true, satellite: false, orbitParticles: false });
    expect(center.radiusScale).toBeLessThan(1);
    expect(center.detailScale).toBeLessThan(1);
    expect(satellite.satellite).toBe(true);
    expect(satellite.radiusScale).toBeLessThan(center.radiusScale);
    expect(satellite.ringOpacity).toBeLessThan(center.ringOpacity);
    expect(satellite.orbitParticles).toBe(false);
    expect(satellite.pipLimit).toBeLessThan(5);
  });

  it("restores a satellite shell when it is hovered or focused", () => {
    const node = {
      id: "region:pratica:family:event",
      path: "region:pratica:family:event",
      title: "events",
      context: "system",
      page_type: "visual_group_event",
      freshness_state: "fresh" as const,
      approved_state: "approved",
      risk_flags: [],
      source_ref_count: 0,
      inbound_links: 0,
      outbound_links: 0,
      ageDays: 0,
      overdueRatio: 0,
      isHub: true,
      isRoot: false,
      position: [0, 0, 0] as [number, number, number],
      scale: 0.4,
      isGroup: true,
      groupKind: "region_family"
    };

    expect(groupShellProfile(node, 2).satellite).toBe(true);
    expect(groupShellProfile(node, 2, "region:pratica:family:event")).toMatchObject({
      active: true,
      satellite: false,
      orbitParticles: true
    });
  });

  it("scales only the centered drill group during physical travel", () => {
    const center = layoutNode({
      id: "region:pratica",
      isRoot: true,
      isGroup: true,
      groupKind: "quadrant"
    });
    const satellite = layoutNode({
      id: "region:sistemas",
      isRoot: false,
      isGroup: true,
      groupKind: "quadrant"
    });

    expect(groupDrillGrowthScale(center, 1, true, 0)).toBeLessThan(0.4);
    expect(groupDrillGrowthScale(center, 1, true, 0.5)).toBeGreaterThan(0.85);
    expect(groupDrillGrowthScale(center, 1, true, 1)).toBe(1);
    expect(groupDrillGrowthScale(center, 2, true, 0)).toBeGreaterThan(groupDrillGrowthScale(center, 1, true, 0));
    expect(groupDrillGrowthScale(satellite, 1, true, 0)).toBe(1);
    expect(groupDrillGrowthScale(center, 1, false, 0)).toBe(1);
  });

  it("turns groups into typed physical landmarks, not generic shells", () => {
    const centerNode = layoutNode({
      id: "region:pratica:family:source",
      page_type: "visual_group_source",
      isRoot: true,
      isHub: true,
      isGroup: true,
      groupKind: "region_family",
      groupMemberIds: Array.from({ length: 24 }, (_, index) => `source-${index}`),
      groupComposition: [{ family: "source", count: 24 }],
      source_ref_count: 96,
      scale: 0.62
    });
    const satelliteNode = layoutNode({
      id: "region:sistemas",
      page_type: "visual_group_region",
      isHub: true,
      isGroup: true,
      groupKind: "quadrant",
      groupMemberIds: Array.from({ length: 24 }, (_, index) => `system-${index}`),
      groupComposition: [{ family: "hub", count: 24 }],
      freshness_state: "stale",
      risk_flags: ["group_attention"],
      scale: 0.42
    });

    const centerProfile = groupLandmarkProfile(centerNode, groupShellProfile(centerNode, 2), "source", 24);
    const satelliteProfile = groupLandmarkProfile(satelliteNode, groupShellProfile(satelliteNode, 2), "region", 24);

    expect(centerProfile).toMatchObject({ family: "source", crown: "stack", satellite: false });
    expect(satelliteProfile).toMatchObject({ family: "region", crown: "region", satellite: true, pulse: true });
    expect(centerProfile.height).toBeGreaterThan(satelliteProfile.height);
    expect(satelliteProfile.opacity).toBeGreaterThan(0.3);
  });

  it("maps action and event groups to distinct navigation landmarks", () => {
    const shell = groupShellProfile(
      layoutNode({
        id: "region:pratica:family:action",
        page_type: "visual_group_action",
        isGroup: true,
        groupKind: "region_family",
        groupComposition: [{ family: "action", count: 5 }]
      }),
      1,
      "region:pratica:family:action"
    );
    expect(
      groupLandmarkProfile(
        layoutNode({
          id: "region:pratica:family:action",
          page_type: "visual_group_action",
          isGroup: true,
          groupKind: "region_family",
          groupComposition: [{ family: "action", count: 5 }]
        }),
        shell,
        "action",
        5
      ).crown
    ).toBe("flag");
    expect(
      groupLandmarkProfile(
        layoutNode({
          id: "region:relacoes:family:event",
          page_type: "visual_group_event",
          isGroup: true,
          groupKind: "region_family",
          groupComposition: [{ family: "event", count: 5 }]
        }),
        shell,
        "event",
        5
      ).crown
    ).toBe("spire");
  });

  it("builds child orbits from real centered-group children without treating peer regions as children", () => {
    const entries = groupChildOrbitEntries(
      [
        layoutNode({
          id: "region:pratica",
          page_type: "visual_group_region",
          isRoot: true,
          isHub: true,
          isGroup: true,
          groupKind: "quadrant",
          groupMemberIds: ["source-a", "source-b", "event-a", "content-a"],
          groupPreviewIds: ["source-a"],
          scale: 0.22
        }),
        layoutNode({
          id: "region:pratica:family:source",
          page_type: "visual_group_source",
          isHub: true,
          isGroup: true,
          groupKind: "region_family",
          groupMemberIds: ["source-a", "source-b"],
          position: [1.4, 0, 0],
          scale: 0.34
        }),
        layoutNode({
          id: "source-a",
          page_type: "source",
          position: [1.7, 0, 0.3],
          scale: 0.2
        }),
        layoutNode({
          id: "event-a",
          page_type: "meeting",
          approved_state: "proposal",
          position: [-1.2, 0.35, 0.2],
          scale: 0.2
        }),
        layoutNode({
          id: "content-a",
          page_type: "artifact",
          source_ref_count: 0,
          position: [-0.6, 0, -1.2],
          scale: 0.2
        }),
        layoutNode({
          id: "region:sistema",
          page_type: "visual_group_region",
          isHub: true,
          isGroup: true,
          groupKind: "quadrant",
          groupMemberIds: ["other-a"],
          position: [3, 0, 0],
          scale: 0.3
        })
      ],
      1,
      "rich"
    );

    expect(entries[0]?.id).toBe("region:pratica:family:source");
    expect(new Set(entries.map((entry) => entry.id))).toEqual(new Set(["region:pratica:family:source", "event-a", "source-a", "content-a"]));
    expect(entries.find((entry) => entry.id === "event-a")?.attention).toBe(true);
    expect(entries.find((entry) => entry.id === "event-a")?.laneKind).toBe("attention");
    expect(entries.find((entry) => entry.id === "source-a")?.laneKind).toBe("evidence");
    expect(entries.find((entry) => entry.id === "content-a")?.laneKind).toBe("gap");
    expect(entries.some((entry) => entry.id === "region:sistema")).toBe(false);
  });

  it("does not create child orbits before drilling into a group", () => {
    expect(
      groupChildOrbitEntries(
        [
          layoutNode({
            id: "region:pratica",
            page_type: "visual_group_region",
            isRoot: true,
            isGroup: true,
            groupMemberIds: ["a"]
          }),
          layoutNode({ id: "a", page_type: "source", position: [1, 0, 0] })
        ],
        0,
        "rich"
      )
    ).toEqual([]);
  });

  it("uses a smaller visible-child budget in deep drills and leaves the rest aggregated", () => {
    const center = layoutNode({
      id: "region:pratica:family:source",
      page_type: "visual_group_source",
      isRoot: true,
      isHub: true,
      isGroup: true,
      groupKind: "region_family",
      groupMemberIds: Array.from({ length: 24 }, (_, index) => `source-${index}`),
      scale: 0.34
    });
    const children = Array.from({ length: 24 }, (_, index) =>
      layoutNode({
        id: `source-${index}`,
        page_type: "source",
        position: [Math.cos(index) * 2, 0, Math.sin(index) * 2],
        scale: 0.2
      })
    );

    expect(groupChildOrbitEntries([center, ...children], 1, "rich")).toHaveLength(24);
    expect(groupChildOrbitEntries([center, ...children], 2, "rich")).toHaveLength(16);
  });

  it("expands dense drill child orbits so the center reads as a district, not a pile", () => {
    expect(groupChildOrbitDensityExpansion(8, 1, "rich")).toBe(1);
    expect(groupChildOrbitDensityExpansion(24, 1, "rich")).toBeGreaterThan(1);
    expect(groupChildOrbitDensityExpansion(45, 2, "rich")).toBeGreaterThan(groupChildOrbitDensityExpansion(24, 1, "rich"));
    expect(groupChildOrbitDensityExpansion(45, 2, "compact")).toBeLessThan(groupChildOrbitDensityExpansion(45, 2, "rich"));

    const center = layoutNode({
      id: "region:pratica:family:source",
      page_type: "visual_group_source",
      isRoot: true,
      isHub: true,
      isGroup: true,
      groupKind: "region_family",
      groupMemberIds: Array.from({ length: 45 }, (_, index) => `source-${index}`),
      scale: 0.34
    });
    const children = Array.from({ length: 45 }, (_, index) =>
      layoutNode({
        id: `source-${index}`,
        page_type: "source",
        position: [Math.cos(index * 0.28) * 2, 0, Math.sin(index * 0.28) * 2],
        scale: 0.2
      })
    );
    const entries = groupChildOrbitEntries([center, ...children], 2, "rich");

    expect(entries).toHaveLength(16);
    expect(Math.min(...entries.map((entry) => entry.radius))).toBeGreaterThan(1.38);
  });

  it("summarizes state lanes into bounded moving motes by lane mass", () => {
    const summaries = groupChildOrbitLaneSummaries(
      [
        { id: "a", family: "source", lane: 1, laneKind: "evidence", laneColor: "#5be7a9", angle: 0, radius: 1.4, y: 0.1, color: "#5be7a9", mass: 1, attention: false, group: false },
        { id: "b", family: "source", lane: 1, laneKind: "evidence", laneColor: "#5be7a9", angle: 0.2, radius: 1.4, y: 0.1, color: "#5be7a9", mass: 1, attention: false, group: false },
        { id: "c", family: "content", lane: 2, laneKind: "gap", laneColor: "#8b93c9", angle: 0.4, radius: 1.6, y: 0.16, color: "#9fb6c6", mass: 1, attention: false, group: false },
        { id: "d", family: "event", lane: 3, laneKind: "attention", laneColor: "#ffca7a", angle: 0.8, radius: 1.8, y: 0.24, color: "#d989ff", mass: 1, attention: true, group: false }
      ],
      "rich"
    );

    expect(summaries.map((summary) => summary.laneKind)).toEqual(["evidence", "gap", "attention"]);
    expect(summaries.reduce((sum, summary) => sum + summary.moteCount, 0)).toBeLessThanOrEqual(30);
    expect(summaries.find((summary) => summary.laneKind === "evidence")?.count).toBe(2);
    expect(summaries.find((summary) => summary.laneKind === "evidence")?.moteCount).toBeGreaterThan(
      summaries.find((summary) => summary.laneKind === "gap")?.moteCount ?? 0
    );
    expect(summaries.find((summary) => summary.laneKind === "attention")?.speed).toBeGreaterThan(
      summaries.find((summary) => summary.laneKind === "gap")?.speed ?? 0
    );
  });

  it("turns child-orbit lanes into a composition crown around the centered group", () => {
    const arcs = groupCompositionArcs(
      [
        { id: "source-a", family: "source", lane: 1, laneKind: "evidence", laneColor: "#5be7a9", angle: 0, radius: 1.4, y: 0.1, color: "#5be7a9", mass: 1, attention: false, group: false },
        { id: "source-b", family: "source", lane: 1, laneKind: "evidence", laneColor: "#5be7a9", angle: 0.2, radius: 1.4, y: 0.1, color: "#5be7a9", mass: 1, attention: false, group: false },
        { id: "gap-a", family: "content", lane: 2, laneKind: "gap", laneColor: "#8b93c9", angle: 0.4, radius: 1.6, y: 0.16, color: "#9fb6c6", mass: 1, attention: false, group: false },
        { id: "event-a", family: "event", lane: 3, laneKind: "attention", laneColor: "#ffca7a", angle: 0.8, radius: 1.8, y: 0.24, color: "#d989ff", mass: 1, attention: true, group: false }
      ],
      "rich"
    );

    expect(arcs.map((arc) => arc.laneKind)).toEqual(["evidence", "gap", "attention"]);
    expect(arcs.find((arc) => arc.laneKind === "evidence")?.share).toBe(0.5);
    expect(arcs.find((arc) => arc.laneKind === "evidence")?.radius).toBeGreaterThan(1);
    expect(arcs[1]?.start).toBeGreaterThan(arcs[0]?.start ?? 0);
    expect(arcs[2]?.end).toBeGreaterThan(arcs[2]?.start ?? 0);
  });

  it("keeps composition crown empty when the group has no visible children", () => {
    expect(groupCompositionArcs([], "rich")).toEqual([]);
  });

  it("compresses dense child-orbit objects without making attention items disappear", () => {
    const normal = { id: "source-a", family: "source", lane: 1, laneKind: "evidence", laneColor: "#5be7a9", angle: 0, radius: 1.4, y: 0.1, color: "#5be7a9", mass: 1, attention: false, group: false } as const;
    const attention = { ...normal, id: "risk-a", laneKind: "attention", attention: true, mass: 1.1 } as const;
    const group = { ...normal, id: "source-group", group: true, mass: 1.35 } as const;

    expect(groupChildOrbitEntryScale(normal, 8)).toBe(0.82);
    expect(groupChildOrbitEntryScale(normal, 24)).toBeLessThan(groupChildOrbitEntryScale(normal, 8));
    expect(groupChildOrbitEntryScale(attention, 24)).toBeGreaterThan(groupChildOrbitEntryScale(normal, 24));
    expect(groupChildOrbitEntryScale(group, 24)).toBeGreaterThan(groupChildOrbitEntryScale(normal, 24));
  });

  it("keeps child-orbit mini-objects inspectable and navigable at dense scale", () => {
    const quiet = { id: "source-a", family: "source", lane: 1, laneKind: "evidence", laneColor: "#5be7a9", angle: 0, radius: 1.4, y: 0.1, color: "#5be7a9", mass: 0.72, attention: false, group: false } as const;
    const attention = { ...quiet, id: "event-a", family: "event", laneKind: "attention", attention: true, mass: 1.05 } as const;
    const grouped = { ...quiet, id: "source-family", group: true, mass: 1.24 } as const;

    const quietHit = groupChildOrbitEntryHitProfile(quiet, 30);
    const attentionHit = groupChildOrbitEntryHitProfile(attention, 30);
    const groupHit = groupChildOrbitEntryHitProfile(grouped, 30);

    expect(quietHit.navigable).toBe(true);
    expect(quietHit.localRadius * groupChildOrbitEntryScale(quiet, 30)).toBeGreaterThanOrEqual(0.2);
    expect(attentionHit.localRadius * groupChildOrbitEntryScale(attention, 30)).toBeGreaterThanOrEqual(0.24);
    expect(groupHit.localRadius * groupChildOrbitEntryScale(grouped, 30)).toBeGreaterThanOrEqual(0.28);
    expect(attentionHit.lift).toBeGreaterThan(quietHit.lift);
  });

  it("treats capped deep drills as dense enough for physical clustering", () => {
    const entries = Array.from({ length: 16 }, (_, index) => ({
      id: `source-${index}`,
      family: "source",
      lane: 1,
      laneKind: "evidence" as GroupChildOrbitLane,
      laneColor: "#5be7a9",
      angle: index * 0.38,
      radius: 1.4,
      y: 0.1,
      color: "#5be7a9",
      mass: 1,
      attention: false,
      group: false
    }));

    expect(groupChildOrbitIsDense(entries, "rich")).toBe(true);
    expect(groupChildOrbitIsDense(entries.slice(0, 8), "rich")).toBe(false);
  });

  it("clusters dense child orbits by practical type while preserving each real object", () => {
    const entries = [
      ...Array.from({ length: 8 }, (_, index) => ({
        id: `source-${index}`,
        family: "source",
        lane: 1,
        laneKind: "evidence" as GroupChildOrbitLane,
        laneColor: "#5be7a9",
        angle: index * 0.42,
        radius: 1.4,
        y: 0.1,
        color: "#5be7a9",
        mass: 1,
        attention: false,
        group: false
      })),
      ...Array.from({ length: 4 }, (_, index) => ({
        id: `event-${index}`,
        family: "event",
        lane: 3,
        laneKind: "attention" as GroupChildOrbitLane,
        laneColor: "#ffca7a",
        angle: 1 + index * 0.44,
        radius: 1.8,
        y: 0.24,
        color: "#d989ff",
        mass: 1.1,
        attention: true,
        group: false
      }))
    ];
    const poses = groupChildOrbitClusterPoses(entries, "rich");
    const sourcePoses = poses.filter((pose) => pose.clusterKey === "evidence:source");
    const eventPoses = poses.filter((pose) => pose.clusterKey === "attention:event");

    expect(poses.map((pose) => pose.id).sort()).toEqual(entries.map((entry) => entry.id).sort());
    expect(new Set(poses.map((pose) => pose.clusterKey))).toEqual(new Set(["evidence:source", "attention:event"]));
    expect(sourcePoses).toHaveLength(8);
    expect(eventPoses).toHaveLength(4);
    expect(sourcePoses[0]?.memberCount).toBe(8);
    expect(eventPoses[0]?.memberCount).toBe(4);
    expect(Math.abs((sourcePoses[0]?.clusterAngle ?? 0) - (eventPoses[0]?.clusterAngle ?? 0))).toBeGreaterThan(0.2);
  });

  it("adds collision relief inside dense clusters instead of stacking objects on the same marker", () => {
    const compactSpread = groupChildOrbitClusterSpread(12, "compact");
    const richSpread = groupChildOrbitClusterSpread(12, "rich");
    expect(richSpread).toBeGreaterThan(compactSpread);

    const entries = Array.from({ length: 16 }, (_, index) => ({
      id: `source-${index}`,
      family: "source",
      lane: 1,
      laneKind: "evidence" as GroupChildOrbitLane,
      laneColor: "#5be7a9",
      angle: 0.4 + index * 0.01,
      radius: 1.7,
      y: 0.1,
      color: "#5be7a9",
      mass: 1,
      attention: false,
      group: false
    }));
    const poses = groupChildOrbitClusterPoses(entries, "rich");

    expect(groupChildOrbitPoseMinimumDistance(poses)).toBeGreaterThan(0.1);
    expect(Math.max(...poses.map((pose) => pose.clusterRadius))).toBeGreaterThan(1.6);
  });

  it("builds hover-readable cluster objects without creating a fake page route", () => {
    const center = layoutNode({
      id: "region:pratica:family:source",
      path: "region:pratica:family:source",
      title: "fontes de dados",
      page_type: "visual_group_source",
      isGroup: true,
      isRoot: true,
      groupKind: "region_family",
      position: [0, 0, 0],
      scale: 0.4
    });
    const sourceCluster = groupChildOrbitClusterHoverNode(center, {
      key: "evidence:source",
      family: "source",
      laneKind: "evidence",
      color: "#5be7a9",
      angle: 0.5,
      radius: 1.4,
      y: 0.12,
      count: 8,
      representativeId: "source-a"
    });
    const attentionCluster = groupChildOrbitClusterHoverNode(center, {
      key: "attention:event",
      family: "event",
      laneKind: "attention",
      color: "#ffca7a",
      angle: 1.4,
      radius: 1.8,
      y: 0.24,
      count: 4,
      representativeId: "event-a"
    });

    expect(sourceCluster.id).toBe("cluster:region:pratica:family:source:evidence:source");
    expect(sourceCluster.title).toBe("data sources · 8");
    expect(sourceCluster.page_type).toBe("source");
    expect(sourceCluster.source_ref_count).toBe(8);
    expect(sourceCluster.inspection).toMatchObject({
      kind: "orbit_cluster",
      family: "source",
      laneKind: "evidence",
      count: 8,
      representativeId: "source-a",
      centerId: "region:pratica:family:source"
    });
    expect(sourceCluster.groupPreviewIds).toEqual(["source-a"]);
    expect(sourceCluster.isGroup).toBe(false);
    expect(attentionCluster.title).toBe("events and meetings · 4");
    expect(attentionCluster.page_type).toBe("meeting");
    expect(attentionCluster.risk_flags).toEqual(["cluster_attention"]);
    expect(attentionCluster.approved_state).toBe("proposal");
  });

  it("keeps dense child clusters visually typed instead of falling back to generic numeric rings", () => {
    const source = groupChildOrbitClusterVisualProfile(
      {
        family: "source",
        laneKind: "evidence",
        color: "#79e6ff",
        count: 12
      },
      "rich"
    );
    const action = groupChildOrbitClusterVisualProfile(
      {
        family: "action",
        laneKind: "attention",
        color: "#ff7a8a",
        count: 4
      },
      "compact"
    );

    expect(source).toMatchObject({
      family: "source",
      color: "#57d9a0",
      laneColor: "#79e6ff",
      labelVisible: true
    });
    expect(action).toMatchObject({
      family: "action",
      color: "#ff9c54",
      laneColor: "#ff7a8a",
      labelVisible: false
    });
    expect(groupChildOrbitClusterVisualProfile({ family: "source", laneKind: "evidence", color: "#57d9a0", count: 13 }, "compact").labelVisible).toBe(true);
    expect(source.glyphMass).toBeGreaterThan(action.glyphMass);
    expect(source.hitRadius).toBeGreaterThanOrEqual(source.ringRadius * 2);
  });

  it("builds bounded containment currents from child orbits so membership reads as flow", () => {
    const flows = groupContainmentFlows(
      [
        { id: "source-a", family: "source", lane: 1, laneKind: "evidence", laneColor: "#5be7a9", angle: 0, radius: 1.4, y: 0.1, color: "#5be7a9", mass: 1, attention: false, group: false },
        { id: "event-a", family: "event", lane: 3, laneKind: "attention", laneColor: "#ffca7a", angle: 0.8, radius: 1.8, y: 0.24, color: "#d989ff", mass: 1.1, attention: true, group: false },
        { id: "gap-a", family: "content", lane: 2, laneKind: "gap", laneColor: "#8b93c9", angle: 0.4, radius: 1.6, y: 0.16, color: "#9fb6c6", mass: 0.8, attention: false, group: false },
        { id: "source-group", family: "source", lane: 1, laneKind: "evidence", laneColor: "#5be7a9", angle: 1.2, radius: 1.5, y: 0.17, color: "#5be7a9", mass: 1.25, attention: false, group: true }
      ],
      "rich"
    );

    expect(flows.map((flow) => flow.id).slice(0, 2)).toEqual(["event-a", "source-group"]);
    expect(flows.find((flow) => flow.id === "gap-a")?.inbound).toBe(false);
    expect(flows.find((flow) => flow.id === "event-a")?.inbound).toBe(true);
    expect(flows.find((flow) => flow.id === "event-a")?.strength).toBeGreaterThan(
      flows.find((flow) => flow.id === "gap-a")?.strength ?? 0
    );
  });

  it("caps containment currents by performance tier", () => {
    const lanes: GroupChildOrbitLane[] = ["attention", "evidence", "gap", "context"];
    const entries = Array.from({ length: 20 }, (_, index) => ({
      id: `child-${index}`,
      family: index % 2 === 0 ? "source" : "content",
      lane: index % 4,
      laneKind: lanes[index % lanes.length],
      laneColor: "#5be7a9",
      angle: index * 0.2,
      radius: 1.2 + index * 0.01,
      y: 0.1,
      color: "#5be7a9",
      mass: 1,
      attention: index % 4 === 0,
      group: false
    }));

    expect(groupContainmentFlows(entries, "compact")).toHaveLength(4);
    expect(groupContainmentFlows(entries, "balanced")).toHaveLength(8);
    expect(groupContainmentFlows(entries, "rich")).toHaveLength(12);
  });
});
