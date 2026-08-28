import { describe, expect, it } from "vitest";
import type { GraphNode } from "../types";
import { computeGalaxyLayout, layoutNodeInstanceKeys, scenePerformanceProfile } from "./layout";
import type { LayoutNode } from "./layout";

function node(id: string, context: string, overrides: Partial<GraphNode> & { stale_after_days?: string } = {}): GraphNode {
  return {
    id,
    path: `memories/${context}/${id}.md`,
    title: id,
    page_type: "note",
    context,
    freshness_state: "fresh",
    approved_state: "approved",
    risk_flags: [],
    metrics: { inbound_links: 0, outbound_links: 1, source_ref_count: 0 },
    updated_at: "2026-07-01",
    stale_after_days: "30",
    ...overrides
  } as GraphNode;
}

const SNAPSHOT = "2026-07-01T00:00:00Z";

function layoutNode(id: string, position: [number, number, number]): LayoutNode {
  return {
    id,
    path: id,
    title: id,
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
    isRoot: false,
    isGroup: true,
    position,
    scale: 0.3
  };
}

describe("layout node render identity", () => {
  it("keeps semantic ids for unique nodes and disambiguates repeated v1 family projections", () => {
    const nodes = [
      layoutNode("root", [0, 0, 0]),
      layoutNode("family:source", [-2, 0, 1]),
      layoutNode("family:source", [2, 0, -1])
    ];

    const keys = layoutNodeInstanceKeys(nodes);

    expect(keys[0]).toBe("root");
    expect(keys.slice(1)).toEqual(["family:source@-2,0,1", "family:source@2,0,-1"]);
    expect(new Set(keys).size).toBe(nodes.length);
    expect(nodes.map((item) => item.id)).toEqual(["root", "family:source", "family:source"]);
  });

  it("uses an occurrence suffix for exact duplicate physical instances", () => {
    const duplicate = layoutNode("family:content", [1.25, 0, -0.5]);
    expect(layoutNodeInstanceKeys([duplicate, { ...duplicate }])).toEqual([
      "family:content@1.25,0,-0.5",
      "family:content@1.25,0,-0.5#2"
    ]);
  });
});

describe("radar layout", () => {
  it("keeps the root at the origin and pins hubs at the wedge mouth", () => {
    const layout = computeGalaxyLayout(
      [
        node("root", "system", { page_type: "root_index" }),
        node("hub", "example", { page_type: "context_hub" }),
        node("alpha", "example")
      ],
      64,
      SNAPSHOT
    );
    const root = layout.nodes.find((item) => item.id === "root");
    const hub = layout.nodes.find((item) => item.id === "hub");
    expect(root?.position).toEqual([0, 0, 0]);
    expect(root?.isHub).toBe(true);
    const hubRadius = Math.hypot(hub!.position[0], hub!.position[2]);
    expect(hubRadius).toBeCloseTo(layout.rInner - 0.25, 3);
  });

  it("allocates one wedge per context with status counts", () => {
    const layout = computeGalaxyLayout(
      [
        node("a1", "alpha"),
        node("a2", "alpha", { freshness_state: "stale", updated_at: "2026-05-01" }),
        node("b1", "beta", { approved_state: "proposal", risk_flags: ["public_boundary"] })
      ],
      64,
      SNAPSHOT
    );
    expect(layout.wedges.map((wedge) => wedge.context)).toEqual(["alpha", "beta"]);
    const alpha = layout.wedges[0];
    expect(alpha.count).toBe(2);
    expect(alpha.staleCount).toBe(1);
    const beta = layout.wedges[1];
    expect(beta.proposalCount).toBe(1);
    expect(beta.riskCount).toBe(1);
    const spanSum = layout.wedges.reduce((total, wedge) => total + (wedge.endAngle - wedge.startAngle), 0);
    expect(spanSum).toBeLessThan(Math.PI * 2);
    expect(spanSum).toBeGreaterThan(Math.PI * 2 - 0.5);
  });

  it("encodes freshness as radius: stale sits past the deadline arc, recent stays inside", () => {
    const layout = computeGalaxyLayout(
      [
        node("recent", "ctx", { updated_at: "2026-06-30" }),
        node("old", "ctx", { freshness_state: "stale", updated_at: "2026-04-01" })
      ],
      64,
      SNAPSHOT
    );
    const band = layout.rOuter - layout.rInner;
    const deadlineRadius = layout.rInner + band * layout.deadlineF;
    const recent = layout.nodes.find((item) => item.id === "recent")!;
    const old = layout.nodes.find((item) => item.id === "old")!;
    expect(Math.hypot(recent.position[0], recent.position[2])).toBeLessThan(deadlineRadius);
    expect(Math.hypot(old.position[0], old.position[2])).toBeGreaterThan(deadlineRadius);
    expect(old.overdueRatio).toBeGreaterThan(1);
  });

  it("floats proposals above the plane and keeps approved content flat", () => {
    const layout = computeGalaxyLayout(
      [node("draft", "ctx", { approved_state: "proposal" }), node("live", "ctx")],
      64,
      SNAPSHOT
    );
    expect(layout.nodes.find((item) => item.id === "draft")?.position[1]).toBeCloseTo(0.5, 4);
    expect(layout.nodes.find((item) => item.id === "live")?.position[1]).toBe(0);
  });

  it("is deterministic regardless of input order", () => {
    const nodes = [
      node("root", "system", { page_type: "root_index" }),
      node("alpha", "example"),
      node("beta", "finance", { freshness_state: "stale", updated_at: "2026-05-20" }),
      node("gamma", "example", { approved_state: "proposal" })
    ];
    const first = computeGalaxyLayout(nodes, 64, SNAPSHOT);
    const second = computeGalaxyLayout([...nodes].reverse(), 64, SNAPSHOT);
    expect(JSON.stringify(first)).toEqual(JSON.stringify(second));
  });

  it("caps visible nodes, keeps attention items and reports truncation", () => {
    const nodes = [
      ...Array.from({ length: 80 }, (_, index) => node(`n-${index}`, index % 2 ? "a" : "b")),
      node("urgent", "a", { freshness_state: "stale", updated_at: "2026-01-01" })
    ];
    const layout = computeGalaxyLayout(nodes, 36, SNAPSHOT);
    expect(layout.nodes).toHaveLength(36);
    expect(layout.truncated).toBe(45);
    expect(layout.nodes.some((item) => item.id === "urgent")).toBe(true);
  });
});

describe("scene performance profile", () => {
  it("uses compact settings for constrained devices", () => {
    const profile = scenePerformanceProfile(200, { width: 390, pixelRatio: 3, hardwareConcurrency: 4 });
    expect(profile.quality).toBe("compact");
    expect(profile.enableIntro).toBe(false);
  });

  it("uses richer settings for medium local repos on desktop", () => {
    const profile = scenePerformanceProfile(48, { width: 1440, pixelRatio: 2, hardwareConcurrency: 10 });
    expect(profile.quality).toBe("rich");
    expect(profile.maxNodes).toBeGreaterThanOrEqual(96);
    expect(profile.dpr[1]).toBeLessThanOrEqual(1.6);
    expect(profile.antialias).toBe(true);
  });

  it("keeps the rich tier while applying dense geometry and MSAA LOD to the 107-node reference universe", () => {
    const profile = scenePerformanceProfile(107, { width: 1440, pixelRatio: 2, hardwareConcurrency: 10 });
    expect(profile).toMatchObject({
      quality: "rich",
      maxNodes: 160,
      geometrySegments: 18,
      antialias: false,
      enableIntro: true,
      label: "rich·dense"
    });
  });

  it("keeps the rich tier for large repos on strong machines", () => {
    // Repo size caps visible nodes/edges but must not kill particles/curves.
    const profile = scenePerformanceProfile(532, { width: 1440, pixelRatio: 2, hardwareConcurrency: 14 });
    expect(profile.quality).toBe("rich");
    expect(profile.maxNodes).toBe(160);
    expect(profile.antialias).toBe(false);
    // Dense repos trade geometry detail, not effects.
    expect(profile.geometrySegments).toBeLessThanOrEqual(18);
  });
});
