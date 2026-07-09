import { describe, expect, it } from "vitest";
import type { LayoutNode } from "../../../scene/layout";
import type { WorldGroup } from "../../../scene/perspectives";
import { groupCompositionForTooltip, groupForHoverNode, orbitClusterSignalsForTooltip, pageSignalsForTooltip } from "./hud";

function groupNode(patch: Partial<LayoutNode> = {}): LayoutNode {
  return {
    id: "region:pratica",
    path: "region:pratica",
    title: "Outputs & evidence",
    context: "system",
    page_type: "visual_group_region",
    freshness_state: "fresh",
    approved_state: "approved",
    risk_flags: [],
    source_ref_count: 0,
    inbound_links: 0,
    outbound_links: 0,
    ageDays: 0,
    overdueRatio: 0,
    isHub: true,
    isRoot: false,
    position: [0, 0, 0],
    scale: 0.42,
    isGroup: true,
    groupKey: "region:pratica",
    groupKind: "quadrant",
    groupLabelKey: "pratica",
    groupMemberIds: ["a", "b", "c"],
    groupComposition: [
      { family: "source", count: 2 },
      { family: "event", count: 1 }
    ],
    ...patch
  };
}

describe("group hover tooltip helpers", () => {
  it("resolves a root quadrant node through its drill group", () => {
    const node = groupNode();
    const groups: WorldGroup[] = [
      {
        key: "pratica",
        kind: "quadrant",
        labelKey: "pratica",
        count: 3,
        shown: 3,
        anchor: [0, 0, 0],
        drill: { group: "region:pratica" },
        memberIds: ["a", "b", "c"]
      }
    ];

    expect(groupForHoverNode(node, groups)?.key).toBe("pratica");
  });

  it("uses deterministic region type mix before node fallback composition", () => {
    const node = groupNode();
    const groups: WorldGroup[] = [
      {
        key: "pratica",
        kind: "quadrant",
        labelKey: "pratica",
        count: 9,
        shown: 4,
        anchor: [0, 0, 0],
        drill: { group: "region:pratica" },
        memberIds: [],
        region: {
          id: "pratica",
          kind: "quadrant",
          label_key: "pratica",
          purpose: "region",
          visual_role: "region.card",
          member_ids: [],
          summary: {
            total: 9,
            shown: 4,
            hidden: 5,
            stale: 1,
            proposal: 0,
            risk: 0,
            raw: 2,
            unsourced: 0,
            open_actions: 1,
            source_backed: 3
          },
          type_mix: [{ page_type: "source", family: "source", count: 9 }],
          attention_hints: [{ kind: "raw", count: 2 }],
          action_hints: [{ kind: "inspect_sources", label_key: "region.action.inspectSources", count: 2 }],
          visual: { grammar_id: "wiki.visual", pack_id: "default", slots: {}, emphasis: [] }
        }
      }
    ];

    expect(groupCompositionForTooltip(node, groupForHoverNode(node, groups))).toMatchObject([
      { key: "source", count: 9 }
    ]);
  });

  it("turns real page hover facts into compact visual signal chips", () => {
    const node = groupNode({
      id: "source-folio",
      title: "Source folio",
      page_type: "source",
      isGroup: false,
      groupKey: undefined,
      groupKind: undefined,
      groupLabelKey: undefined,
      groupMemberIds: undefined,
      groupComposition: undefined,
      source_ref_count: 7,
      inbound_links: 5,
      outbound_links: 3,
      risk_flags: ["missing_recipe"],
      freshness_state: "stale"
    });

    expect(pageSignalsForTooltip(node).map((chip) => chip.key)).toEqual(["type", "state", "evidence", "links", "risk"]);
    expect(pageSignalsForTooltip(node).find((chip) => chip.key === "evidence")).toMatchObject({ value: 7 });
    expect(pageSignalsForTooltip(node).find((chip) => chip.key === "links")).toMatchObject({ value: 8 });
  });

  it("describes orbital clusters as grouped real children, not fake pages", () => {
    const node = groupNode({
      id: "cluster:region:pratica:family:source:evidence:source",
      title: "data sources · 8",
      page_type: "source",
      isGroup: false,
      groupKey: undefined,
      groupKind: undefined,
      groupLabelKey: undefined,
      groupMemberIds: undefined,
      groupComposition: undefined,
      source_ref_count: 8,
      inbound_links: 8,
      inspection: {
        kind: "orbit_cluster",
        family: "source",
        laneKind: "evidence",
        count: 8,
        representativeId: "source-a",
        centerId: "region:pratica:family:source"
      }
    });

    expect(orbitClusterSignalsForTooltip(node).map((chip) => chip.key)).toEqual(["family", "count", "lane"]);
    expect(orbitClusterSignalsForTooltip(node).find((chip) => chip.key === "lane")).toMatchObject({ value: "evidence" });
    expect(pageSignalsForTooltip(node).find((chip) => chip.key === "evidence")).toMatchObject({ value: 8 });
  });
});
