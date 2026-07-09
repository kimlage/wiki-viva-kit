import { describe, expect, it } from "vitest";
import type { LayoutNode } from "./layout";
import {
  auraPoint,
  buildAuraParticles,
  buildEmberParticles,
  buildFlowParticles,
  buildGapParticles,
  buildGroupPullParticles,
  buildStemParticles,
  emberPoint,
  flowPoint,
  gapPoint,
  groupPullPoint,
  particleLodBudget,
  stemPoint
} from "./particles";

function layoutNode(id: string, overrides: Partial<LayoutNode> = {}): LayoutNode {
  return {
    id,
    path: `memories/${id}.md`,
    title: id,
    context: "ctx",
    page_type: "note",
    freshness_state: "stale",
    approved_state: "approved",
    risk_flags: [],
    source_ref_count: 0,
    inbound_links: 0,
    outbound_links: 0,
    ageDays: 40,
    overdueRatio: 1.4,
    isHub: false,
    isRoot: false,
    position: [2.5, 0, 1.2],
    scale: 0.14,
    ...overrides
  };
}

describe("particle builders", () => {
  it("scales the core aura with recent activity and goes dark when idle", () => {
    expect(buildAuraParticles(0)).toHaveLength(0);
    const calm = buildAuraParticles(2);
    const busy = buildAuraParticles(40);
    expect(calm.length).toBeGreaterThan(0);
    expect(calm.length).toBeLessThan(busy.length);
    expect(busy.length).toBeLessThanOrEqual(120);
    expect(JSON.stringify(buildAuraParticles(5))).toEqual(JSON.stringify(buildAuraParticles(5)));
  });

  it("thins flow particles uniformly so every edge keeps at least one spark", () => {
    const edges = Array.from({ length: 50 }, (_, index) => ({
      from: [0, 0, 0] as [number, number, number],
      control: [1, 1, 0] as [number, number, number],
      to: [2, 0, 0] as [number, number, number],
      color: "#57d9a0",
      key: `edge-${index}`
    }));
    const particles = buildFlowParticles(edges, 2, 72);
    // Budget forces one spark per edge instead of dropping whole edges.
    expect(particles.length).toBe(50);
    const fewEdges = buildFlowParticles(edges.slice(0, 10), 2, 72);
    expect(fewEdges.length).toBe(20);
    expect(JSON.stringify(buildFlowParticles(edges, 2, 72))).toEqual(JSON.stringify(particles));
  });

  it("builds deterministic child-to-group pull sparks", () => {
    const inputs = Array.from({ length: 40 }, (_, index) => ({
      from: [index * 0.1, 0, 1] as [number, number, number],
      to: [0, 0, 0] as [number, number, number],
      color: "#57d9a0",
      key: `child-${index}`
    }));
    const particles = buildGroupPullParticles(inputs, 2, 32);
    expect(particles).toHaveLength(32);
    expect(particles[0].kind).toBe("group_pull");
    expect(particles[0].to).toEqual([0, 0, 0]);
    expect(JSON.stringify(buildGroupPullParticles(inputs, 2, 32))).toEqual(JSON.stringify(particles));
  });

  it("uses a quieter particle budget inside dense quadrant family drills", () => {
    const rootBudget = particleLodBudget({ perspective: "quadrants", level: 0 }, true);
    const familyBudget = particleLodBudget({ perspective: "quadrants", level: 2 }, true);

    expect(familyBudget.flowMax).toBeLessThan(rootBudget.flowMax);
    expect(familyBudget.groupInputLimit).toBeLessThan(rootBudget.groupInputLimit);
    expect(familyBudget.groupPullMax).toBeLessThan(rootBudget.groupPullMax);
    expect(familyBudget.auraMax).toBe(rootBudget.auraMax);
  });

  it("prioritizes the most overdue nodes for embers", () => {
    const nodes = [
      layoutNode("mild", { overdueRatio: 1.1 }),
      layoutNode("severe", { overdueRatio: 2.4 })
    ];
    const particles = buildEmberParticles(nodes, 5, 5);
    expect(particles).toHaveLength(5);
    // Severe overdue reaches farther out.
    expect(Math.max(...particles.map((p) => p.reach))).toBeGreaterThan(0.7);
  });

  it("builds stem particles only for floating drafts", () => {
    const particles = buildStemParticles([layoutNode("draft", { position: [1, 0.5, 1] })]);
    expect(particles.length).toBeGreaterThan(0);
    expect(particles[0].base[1]).toBe(0);
    expect(particles[0].top[1]).toBeCloseTo(0.5);
  });

  it("caps gap motes and is deterministic per node", () => {
    const nodes = Array.from({ length: 90 }, (_, index) => layoutNode(`gap-${index}`));
    const particles = buildGapParticles(nodes, 60);
    expect(particles).toHaveLength(60);
    expect(particles.every((p) => p.drop > 0 && p.speed > 0)).toBe(true);
    expect(JSON.stringify(buildGapParticles(nodes, 60))).toEqual(JSON.stringify(particles));
  });
});

describe("analytic evaluation", () => {
  it("is a pure function of time", () => {
    const aura = buildAuraParticles(3)[0];
    expect(auraPoint(aura, 2.5)).toEqual(auraPoint(aura, 2.5));
    const flow = buildFlowParticles(
      [{ from: [0, 0, 0], control: [1, 1, 0], to: [2, 0, 0], color: "#fff", key: "k" }],
      1
    )[0];
    const [, , , alphaMid] = flowPoint({ ...flow, phase: 0.5, speed: 0 }, 0);
    expect(alphaMid).toBeCloseTo(1, 1);
    const ember = buildEmberParticles([layoutNode("n")], 1)[0];
    const [, y0] = emberPoint({ ...ember, phase: 0, speed: 0 }, 0);
    expect(y0).toBeCloseTo(ember.origin[1], 5);
    const stem = buildStemParticles([layoutNode("d", { position: [1, 0.5, 1] })], 1)[0];
    const [, yTop, , alphaEnd] = stemPoint({ ...stem, phase: 0.999, speed: 0 }, 0);
    expect(yTop).toBeGreaterThan(0.45);
    expect(alphaEnd).toBeLessThan(0.05);
    // Gap motes SINK below their node and fade — the inverse read of a stem.
    const gap = buildGapParticles([layoutNode("g", { position: [1, 2, 1] })])[0];
    const [, yStart, , alphaStart] = gapPoint({ ...gap, phase: 0, speed: 0 }, 0);
    const [, ySunk] = gapPoint({ ...gap, phase: 0.999, speed: 0 }, 0);
    expect(yStart).toBeCloseTo(2, 5);
    expect(ySunk).toBeLessThan(yStart);
    expect(alphaStart).toBeCloseTo(0.45, 2);
    const pull = buildGroupPullParticles([{ from: [2, 0, 0], to: [0, 0, 0], color: "#fff", key: "pull" }], 1)[0];
    const [pullX0] = groupPullPoint({ ...pull, phase: 0, speed: 0 }, 0);
    const [pullXEnd, , , pullAlphaEnd] = groupPullPoint({ ...pull, phase: 0.999, speed: 0 }, 0);
    expect(pullX0).toBeCloseTo(2, 5);
    expect(pullXEnd).toBeLessThan(0.01);
    expect(pullAlphaEnd).toBeLessThan(0.05);
  });
});
