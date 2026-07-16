import { afterEach, describe, expect, it } from "vitest";
import { configureLanguage } from "../../../data/i18n";
import type { LayoutNode } from "../../../scene/layout";
import type { WorldGroup, WorldLayout } from "../../../scene/perspectives";
import { buildLabelSet, compactGroupMetric, groupCompositionChipsForLabel, groupHandleForLabel, groupStateChipsForLabel, labelLiftForNode, labelsForActivePlate, labelTitleForNode } from "./labels";

afterEach(() => configureLanguage("en"));

function layoutNode(id: string, patch: Partial<LayoutNode> = {}): LayoutNode {
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
    inbound_links: 0,
    outbound_links: 0,
    ageDays: 0,
    overdueRatio: 0,
    isHub: false,
    isRoot: false,
    position: [0, 0, 0],
    scale: 0.24,
    ...patch
  };
}

function world(nodes: LayoutNode[], patch: Partial<WorldLayout> = {}): WorldLayout {
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

describe("scene labels", () => {
  it("removes the active plate node label because the plate already names it", () => {
    const center = layoutNode("source-center", { title: "Source center", isRoot: true, page_type: "source" });
    const neighbor = layoutNode("neighbor", { title: "Neighbor", isHub: true, position: [1, 0, 0] });
    const labels = buildLabelSet(world([center, neighbor]), new Set(), center.id, 8);

    expect(labels.map((label) => label.node.id)).toContain(center.id);
    expect(labelsForActivePlate(labels, center).map((label) => label.node.id)).not.toContain(center.id);
    expect(labelsForActivePlate(labels, center).map((label) => label.node.id)).toContain(neighbor.id);
    expect(labelsForActivePlate(labels, null)).toEqual(labels);
  });

  it("keeps root quadrant overview labels scoped to region objects", () => {
    const sourceGroup = layoutNode("region:pratica:family:source", {
      title: "data sources",
      page_type: "visual_group_source",
      isHub: true,
      isGroup: true,
      groupKind: "region_family",
      groupLabelKey: "source",
      groupMemberIds: Array.from({ length: 44 }, (_, index) => `source-${index}`),
      visualGlyph: "▣",
      position: [1, 0, 1]
    });
    const labels = buildLabelSet(
      world([
        layoutNode("root", { title: "Root", isRoot: true, isHub: true }),
        layoutNode("stale-a", { title: "Stale A", freshness_state: "stale", ageDays: 30, overdueRatio: 1.5 }),
        layoutNode("stale-b", { title: "Stale B", freshness_state: "stale", ageDays: 28, overdueRatio: 1.4 }),
        layoutNode("stale-c", { title: "Stale C", freshness_state: "stale", ageDays: 26, overdueRatio: 1.3 }),
        sourceGroup
      ]),
      new Set(),
      "",
      8
    );

    expect(labels.find((label) => label.node.id === sourceGroup.id)).toBeUndefined();
    expect(labels.filter((label) => label.node.freshness_state === "stale")).toHaveLength(2);
  });

  it("keeps quadrant drill group labels compact instead of repeating long captions", () => {
    const familyGroup = layoutNode("region:pratica:family:source", {
      title: "fontes de dados",
      page_type: "visual_group_source",
      isHub: true,
      isGroup: true,
      groupKind: "region_family",
      groupLabelKey: "source",
      groupCaption: "45 · Fonte - Wiki demonstrativa · Registro de fontes canonicas",
      groupMemberIds: Array.from({ length: 45 }, (_, index) => `source-${index}`),
      visualGlyph: "▣",
      position: [1, 0, 1]
    });
    const labels = buildLabelSet(
      world(
        [
          layoutNode("region:pratica", {
            title: "Saídas e evidências",
            isRoot: true,
            isHub: true,
            isGroup: true,
            groupKind: "quadrant",
            groupLabelKey: "pratica",
            groupMemberIds: Array.from({ length: 231 }, (_, index) => `page-${index}`)
          }),
          familyGroup
        ],
        { level: 1, group: "region:pratica" }
      ),
      new Set(),
      "",
      8
    );

    const familyLabel = labels.find((label) => label.node.id === familyGroup.id);
    expect(familyLabel).toMatchObject({ compact: true, annotation: "45" });
  });

  it("keeps group annotations metric-first instead of pinning long preview captions", () => {
    const familyGroup = layoutNode("region:pratica:family:source", {
      title: "fontes de dados",
      page_type: "visual_group_source",
      isHub: true,
      isGroup: true,
      groupKind: "region_family",
      groupLabelKey: "source",
      groupCaption: "45 · Fonte - Wiki demonstrativa · Registro de fontes canonicas",
      groupMemberIds: Array.from({ length: 45 }, (_, index) => `source-${index}`),
      groupComposition: [
        { family: "source", count: 32 },
        { family: "event", count: 13 }
      ],
      visualGlyph: "▣",
      position: [1, 0, 1]
    });

    expect(compactGroupMetric(familyGroup)).toBe("45 · 32");
    const labels = buildLabelSet(
      world(
        [
          layoutNode("region:pratica", {
            title: "Saídas e evidências",
            isRoot: true,
            isHub: true,
            isGroup: true,
            groupKind: "quadrant",
            groupLabelKey: "pratica",
            groupMemberIds: Array.from({ length: 231 }, (_, index) => `page-${index}`)
          }),
          familyGroup
        ],
        { level: 1, group: "region:pratica" }
      ),
      new Set(),
      "",
      8
    );

    expect(labels.find((label) => label.node.id === familyGroup.id)?.annotation).toBe("45 · 32");
  });

  it("turns real group composition into compact visual chips for labels", () => {
    const familyGroup = layoutNode("region:pratica:family:mixed", {
      title: "mixed evidence",
      page_type: "visual_group_source",
      isHub: true,
      isGroup: true,
      groupKind: "region_family",
      groupLabelKey: "mixed",
      groupMemberIds: ["source-a", "source-b", "event-a", "action-a", "rule-a"],
      groupComposition: [
        { family: "event", count: 1 },
        { family: "source", count: 2 },
        { family: "action", count: 1 },
        { family: "rule", count: 1 }
      ]
    });

    expect(groupCompositionChipsForLabel(layoutNode("plain-page"))).toEqual([]);
    expect(groupCompositionChipsForLabel(familyGroup, 3)).toMatchObject([
      { family: "source", count: 2, share: 0.4 },
      { family: "action", count: 1, share: 0.2 },
      { family: "event", count: 1, share: 0.2 }
    ]);
  });

  it("turns real group state and action into compact visual chips for labels", () => {
    const familyGroup = layoutNode("region:pratica:family:source", {
      title: "source records",
      page_type: "visual_group_source",
      isHub: true,
      isGroup: true,
      groupKind: "region_family",
      groupLabelKey: "source",
      groupMemberIds: ["source-a", "source-b", "source-c", "source-d", "source-e"],
      freshness_state: "stale",
      approved_state: "proposal",
      risk_flags: ["group_attention"],
      source_ref_count: 7
    });
    const group: WorldGroup = {
      key: familyGroup.id,
      kind: "region_family",
      labelKey: "source",
      count: 5,
      shown: 5,
      anchor: [0, 0, 0],
      drill: { group: familyGroup.id },
      memberIds: familyGroup.groupMemberIds ?? [],
      region: {
        id: "region:pratica",
        kind: "quadrant",
        label_key: "pratica",
        purpose: "Evidence work",
        visual_role: "lens",
        member_ids: familyGroup.groupMemberIds ?? [],
        summary: {
          total: 5,
          shown: 5,
          hidden: 0,
          stale: 2,
          proposal: 1,
          risk: 1,
          raw: 2,
          unsourced: 1,
          open_actions: 3,
          source_backed: 4
        },
        type_mix: [{ page_type: "source", family: "source", count: 5 }],
        attention_hints: [{ kind: "stale", count: 2 }],
        action_hints: [{ kind: "inspect_sources", label_key: "region.action.inspectSources", count: 3 }],
        visual: { grammar_id: "wiki.visual.v1", pack_id: "default", slots: {}, emphasis: ["attention"] }
      }
    };

    expect(groupStateChipsForLabel(layoutNode("plain-page"))).toEqual([]);
    expect(groupStateChipsForLabel(familyGroup, group, 4).map((chip) => [chip.kind, chip.count])).toEqual([
      ["action", 3],
      ["risk", 1],
      ["stale", 2],
      ["proposal", 1]
    ]);
    expect(groupStateChipsForLabel(familyGroup, group, 6).map((chip) => chip.kind)).toEqual([
      "action",
      "risk",
      "stale",
      "proposal",
      "gap",
      "evidence"
    ]);
  });

  it("prioritizes family handles and turns deep-drill satellite text into metric badges", () => {
    const root = layoutNode("region:pratica:family:source", {
      title: "fontes de dados",
      isRoot: true,
      isHub: true,
      isGroup: true,
      groupKind: "region_family",
      groupLabelKey: "source",
      groupMemberIds: Array.from({ length: 45 }, (_, index) => `source-${index}`)
    });
    const family = (name: string, count: number) =>
      layoutNode(`region:pratica:family:${name}`, {
        title: name,
        isHub: true,
        isGroup: true,
        groupKind: "region_family",
        groupLabelKey: name,
        groupMemberIds: Array.from({ length: count }, (_, index) => `${name}-${index}`),
        visualGlyph: "▤"
      });
    const quadrant = (name: string, count: number) =>
      layoutNode(`region:${name}`, {
        title: name,
        isHub: true,
        isGroup: true,
        groupKind: "quadrant",
        groupLabelKey: name,
        groupMemberIds: Array.from({ length: count }, (_, index) => `${name}-${index}`),
        visualGlyph: "◈"
      });

    const labels = buildLabelSet(
      world(
        [
          root,
          quadrant("sistema", 70),
          quadrant("identidade", 40),
          family("hub", 153),
          family("event", 15),
          family("content", 10),
          family("rule", 5),
          family("action", 3)
        ],
        { level: 2, group: "region:pratica:family:source" }
      ),
      new Set(),
      "",
      10
    );

    expect(labels.map((label) => label.node.id).slice(0, 4)).toEqual([
      "region:pratica:family:source",
      "region:pratica:family:hub",
      "region:pratica:family:event",
      "region:pratica:family:content"
    ]);
    expect(labels.find((label) => label.node.id === "region:pratica:family:hub")).toMatchObject({ mode: "metric", annotation: "153" });
    expect(labels.find((label) => label.node.id === "region:pratica:family:event")).toMatchObject({ mode: "metric", annotation: "15" });
    expect(labels.find((label) => label.node.id === "region:pratica:family:content")).toMatchObject({ mode: "metric", annotation: "10" });
    expect(labels.find((label) => label.node.id === "region:pratica:family:rule")).toMatchObject({ mode: "glyph", annotation: null });
    expect(labels.find((label) => label.node.id === "region:pratica:family:action")).toMatchObject({ mode: "glyph", annotation: null });
    expect(labels.find((label) => label.node.id === "region:sistema")).toMatchObject({ mode: "glyph", annotation: null });
    expect(compactGroupMetric(quadrant("sistema", 70))).toBeNull();
  });

  it("keeps dominant center-group labels near the object instead of pushing them off screen", () => {
    const center = layoutNode("region:pratica:family:source", {
      isRoot: true,
      isHub: true,
      isGroup: true,
      groupKind: "region_family",
      groupLabelKey: "source",
      scale: 0.72
    });
    const satellite = layoutNode("region:pratica:family:event", {
      isHub: true,
      isGroup: true,
      groupKind: "region_family",
      groupLabelKey: "event",
      scale: 0.42
    });

    expect(labelLiftForNode(center)).toBeLessThan(2);
    expect(labelLiftForNode(center)).toBeGreaterThan(1.7);
    expect(labelLiftForNode(satellite)).toBeLessThan(labelLiftForNode(center));
    expect(labelLiftForNode(satellite)).toBeGreaterThan(1.4);
  });

  it("localizes group labels at render time instead of trusting worker titles", () => {
    configureLanguage("pt-BR");
    expect(
      labelTitleForNode(
        layoutNode("region:pratica:family:source", {
          title: "data sources",
          page_type: "visual_group_source",
          isGroup: true,
          groupKind: "region_family",
          groupLabelKey: "source"
        })
      )
    ).toBe("fontes & evidências");
  });

  it("replaces repeated root hub labels with quadrant-specific semantic names", () => {
    configureLanguage("pt-BR");
    const titles = (["intencao", "pratica", "relacoes", "sistemas"] as const).map((quadrant) =>
      labelTitleForNode(
        layoutNode(`region:${quadrant}:family:hub`, {
          title: "areas and workspaces",
          page_type: "visual_group_hub",
          isGroup: true,
          groupKind: "family",
          groupLabelKey: "hub",
          quadrant
        }),
        true
      )
    );

    expect(titles).toEqual([
      "Q1 · Identidade e intenção",
      "Q2 · Saídas e evidências",
      "Q3 · Cultura e relações",
      "Q4 · Sistemas e governança"
    ]);
    expect(new Set(titles)).toHaveLength(4);
    expect(titles.every((title) => !title.includes("áreas & espaços de trabalho"))).toBe(true);
    expect(
      labelTitleForNode(
        layoutNode("region:pratica:family:hub", {
          isGroup: true,
          groupKind: "family",
          groupLabelKey: "hub",
          quadrant: "pratica"
        })
      )
    ).toBe("áreas & espaços de trabalho");
    expect(
      labelTitleForNode(
        layoutNode("family:hub", {
          isGroup: true,
          groupKind: "family",
          groupLabelKey: "hub",
          quadrant: "intencao"
        })
      )
    ).toBe("áreas & espaços de trabalho");
  });

  it("scopes quadrant prefixes to the unfiltered root overview", () => {
    configureLanguage("pt-BR");
    const root = layoutNode("root", { title: "Root", isRoot: true, isHub: true });
    const family = layoutNode("region:pratica:family:source", {
      title: "data sources",
      page_type: "visual_group_source",
      isHub: true,
      isGroup: true,
      groupKind: "family",
      groupLabelKey: "source",
      groupMemberIds: ["source-a", "source-b"],
      quadrant: "pratica",
      position: [1, 0, 1]
    });

    const overviewLabel = buildLabelSet(world([root, family]), new Set(), "", 8)
      .find((label) => label.node.id === family.id);
    expect(overviewLabel).toMatchObject({ disambiguateQuadrant: true });
    expect(labelTitleForNode(overviewLabel!.node, overviewLabel!.disambiguateQuadrant)).toBe("Q2 · fontes & evidências");

    const focusedLabel = buildLabelSet(world([root, family]), new Set(), "", 8, "pratica")
      .find((label) => label.node.id === family.id);
    expect(focusedLabel?.disambiguateQuadrant).toBeUndefined();
    expect(labelTitleForNode(focusedLabel!.node, focusedLabel!.disambiguateQuadrant)).toBe("fontes & evidências");
  });

  it("connects visible group labels to their drill-down group object", () => {
    const drill = { context: undefined, group: "region:pratica:family:source" };
    const group: WorldGroup = {
      key: "region:pratica:family:source",
      kind: "region_family",
      labelKey: "source",
      count: 72,
      shown: 24,
      anchor: [1, 0, 1],
      drill,
      memberIds: []
    };
    const node = layoutNode("group-node", {
      isGroup: true,
      groupKey: "region:pratica:family:source",
      groupDrill: drill
    });

    expect(groupHandleForLabel(node, [group])).toBe(group);
    expect(groupHandleForLabel(layoutNode("plain-page"), [group])).toBeUndefined();
  });

  it("makes satellite group labels navigable even when they are not rim groups", () => {
    const drill = { group: "region:pratica:family:event" };
    const node = layoutNode("region:pratica:family:event", {
      isGroup: true,
      groupKey: "region:pratica:family:event",
      groupKind: "region_family",
      groupLabelKey: "event",
      groupDrill: drill,
      groupMemberIds: ["event-a", "event-b", "event-c"],
      groupPreviewIds: ["event-a"],
      position: [2, -0.06, -1]
    });

    expect(groupHandleForLabel(node, [])).toMatchObject({
      key: "region:pratica:family:event",
      kind: "region_family",
      labelKey: "event",
      count: 3,
      shown: 1,
      anchor: [2, -0.06, -1],
      drill
    });
  });

  it("connects root quadrant object labels even when the rim group uses the facet key", () => {
    const group: WorldGroup = {
      key: "pratica",
      kind: "quadrant",
      labelKey: "pratica",
      count: 12,
      shown: 6,
      anchor: [2, 0, -2],
      drill: { group: "region:pratica" },
      memberIds: []
    };
    const node = layoutNode("region:pratica", {
      isGroup: true,
      groupKey: "region:pratica",
      groupKind: "quadrant",
      groupLabelKey: "pratica",
      groupDrill: { group: "region:pratica" }
    });

    expect(groupHandleForLabel(node, [group])).toBe(group);
  });
});
