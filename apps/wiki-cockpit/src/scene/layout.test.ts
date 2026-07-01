import { describe, expect, it } from "vitest";
import type { GraphNode } from "../types";
import { computeGalaxyLayout, scenePerformanceProfile } from "./layout";

function node(id: string, context: string, overrides: Partial<GraphNode> = {}): GraphNode {
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
    ...overrides
  };
}

describe("galaxy layout", () => {
  it("groups nodes by context and keeps output deterministic", () => {
    const nodes = [
      node("root", "system", { page_type: "root_index" }),
      node("alpha", "example"),
      node("beta", "finance", { freshness_state: "stale" }),
      node("gamma", "example")
    ];

    const first = computeGalaxyLayout(nodes, 10);
    const second = computeGalaxyLayout([...nodes].reverse(), 10);

    expect(first.contextAnchors.map((anchor) => anchor.context)).toEqual(["example", "finance", "system"]);
    expect(first.nodes.map((item) => [item.id, item.position])).toEqual(second.nodes.map((item) => [item.id, item.position]));
    expect(first.nodes.find((item) => item.id === "root")?.position).toEqual([0, 0, 0]);
  });

  it("caps visible nodes and reports truncation", () => {
    const nodes = Array.from({ length: 80 }, (_, index) => node(`n-${index}`, index % 2 ? "a" : "b"));

    const layout = computeGalaxyLayout(nodes, 36);

    expect(layout.nodes).toHaveLength(36);
    expect(layout.truncated).toBe(44);
  });
});

describe("scene performance profile", () => {
  it("uses compact settings for constrained devices", () => {
    const profile = scenePerformanceProfile(160, { width: 390, pixelRatio: 3, hardwareConcurrency: 4 });

    expect(profile.quality).toBe("compact");
    expect(profile.maxNodes).toBe(36);
    expect(profile.enableIntro).toBe(false);
  });

  it("uses richer settings for medium local repos on desktop", () => {
    const profile = scenePerformanceProfile(48, { width: 1440, pixelRatio: 2, hardwareConcurrency: 10 });

    expect(profile.quality).toBe("rich");
    expect(profile.maxNodes).toBe(96);
    expect(profile.dpr[1]).toBeLessThanOrEqual(1.6);
  });
});
