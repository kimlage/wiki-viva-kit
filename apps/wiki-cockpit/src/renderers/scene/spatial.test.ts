import { describe, expect, it } from "vitest";
import { worldPlatePose } from "./spatial";
import type { LayoutNode } from "../../scene/layout";

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
    scale: overrides.scale ?? 0.4,
    ...rest
  };
}

describe("world plate pose", () => {
  it("moves page-center plates to the side so the object body stays visible", () => {
    const pose = worldPlatePose(
      layoutNode({
        id: "source-center",
        page_type: "source",
        isRoot: true,
        inbound_links: 16,
        outbound_links: 1,
        source_ref_count: 8
      })
    );

    expect(pose.tether).toBe(true);
    expect(pose.className).toContain("worldPlateSide");
    expect(Math.abs(pose.anchor[0] - pose.subject[0])).toBeGreaterThan(0.8);
    expect(pose.anchor[1]).toBeLessThan(pose.subject[1]);
  });

  it("keeps non-center and group plates anchored above their subject", () => {
    const satellite = worldPlatePose(layoutNode({ id: "satellite", isRoot: false, position: [1, 0, 0] }));
    const group = worldPlatePose(layoutNode({ id: "region:source", isRoot: true, isGroup: true }));

    expect(satellite).toMatchObject({ tether: false, className: "anchoredAbove" });
    expect(group).toMatchObject({ tether: false, className: "anchoredAbove" });
    expect(satellite.anchor).toEqual(satellite.subject);
    expect(group.anchor).toEqual(group.subject);
  });

  it("gives highly connected page centers a little more lateral room", () => {
    const quiet = worldPlatePose(layoutNode({ id: "quiet", isRoot: true, inbound_links: 1, outbound_links: 1, source_ref_count: 0 }));
    const dense = worldPlatePose(layoutNode({ id: "dense", isRoot: true, inbound_links: 80, outbound_links: 24, source_ref_count: 12 }));

    expect(Math.abs(dense.anchor[0] - dense.subject[0])).toBeGreaterThan(Math.abs(quiet.anchor[0] - quiet.subject[0]));
  });
});
