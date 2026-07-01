import type { LayoutNode } from "./layout";

// Particle systems are data, not decoration: every emitter is tied to a real
// operational signal. Positions are analytic functions of elapsed time, so
// the simulation is deterministic, stateless and cheap to evaluate.

export type AuraParticle = {
  kind: "aura";
  radius: number;
  yBase: number;
  wobble: number;
  phase: number;
  speed: number;
};

export type FlowParticle = {
  kind: "flow";
  from: [number, number, number];
  control: [number, number, number];
  to: [number, number, number];
  color: string;
  phase: number;
  speed: number;
};

export type EmberParticle = {
  kind: "ember";
  origin: [number, number, number];
  direction: [number, number, number];
  reach: number;
  phase: number;
  speed: number;
};

export type StemParticle = {
  kind: "stem";
  base: [number, number, number];
  top: [number, number, number];
  phase: number;
  speed: number;
};

export function seededRandom(seed: number): () => number {
  let state = seed || 1;
  return () => {
    state = (state * 16807) % 2147483647;
    return (state - 1) / 2147483646;
  };
}

// Core aura: orbiting sparks around the root; density tracks recent activity.
// Zero activity = zero sparks (a dead wiki must not buzz), and the sqrt scale
// keeps busy weeks distinguishable instead of clamping early.
export function buildAuraParticles(activityLevel: number, maxCount = 120): AuraParticle[] {
  if (activityLevel <= 0) return [];
  const count = Math.min(Math.max(Math.round(10 * Math.sqrt(activityLevel)), 4), maxCount);
  const random = seededRandom(4241);
  return Array.from({ length: count }, () => ({
    kind: "aura" as const,
    radius: 0.55 + random() * 0.38,
    yBase: (random() - 0.5) * 0.26,
    wobble: 0.04 + random() * 0.07,
    phase: random(),
    speed: 0.05 + random() * 0.09
  }));
}

export type FlowEdgeInput = {
  from: [number, number, number];
  control: [number, number, number];
  to: [number, number, number];
  color: string;
  key: string;
};

// Flow sparks: provenance moving along evidence/ingestion/review arcs.
// When the budget is tight every edge keeps at least one spark (thinning is
// uniform, never an arbitrary subset of equally real relations).
export function buildFlowParticles(edges: FlowEdgeInput[], perEdge = 2, maxParticles = 72): FlowParticle[] {
  const particles: FlowParticle[] = [];
  const sorted = [...edges].sort((a, b) => a.key.localeCompare(b.key));
  const budgetPerEdge = sorted.length > 0 ? Math.max(1, Math.min(perEdge, Math.floor(maxParticles / sorted.length))) : perEdge;
  for (const edge of sorted) {
    if (particles.length >= maxParticles) break;
    const random = seededRandom(edge.key.split("").reduce((total, char) => (total * 31 + char.charCodeAt(0)) % 2147483000, 7) + 13);
    for (let index = 0; index < budgetPerEdge && particles.length < maxParticles; index += 1) {
      particles.push({
        kind: "flow",
        from: edge.from,
        control: edge.control,
        to: edge.to,
        color: edge.color,
        phase: random(),
        speed: 0.14 + random() * 0.1
      });
    }
  }
  return particles;
}

// Embers: overdue content sheds heat; more overdue burns brighter and longer.
export function buildEmberParticles(staleNodes: LayoutNode[], perNode = 5, maxParticles = 60): EmberParticle[] {
  const particles: EmberParticle[] = [];
  const sorted = [...staleNodes].sort((a, b) => b.overdueRatio - a.overdueRatio || a.id.localeCompare(b.id));
  for (const node of sorted) {
    if (particles.length >= maxParticles) break;
    const random = seededRandom(node.id.split("").reduce((total, char) => (total * 33 + char.charCodeAt(0)) % 2147483000, 3) + 29);
    const outward = Math.hypot(node.position[0], node.position[2]) || 1;
    const radialX = node.position[0] / outward;
    const radialZ = node.position[2] / outward;
    for (let index = 0; index < perNode && particles.length < maxParticles; index += 1) {
      const jitterAngle = (random() - 0.5) * 1.1;
      const cos = Math.cos(jitterAngle);
      const sin = Math.sin(jitterAngle);
      particles.push({
        kind: "ember",
        origin: node.position,
        direction: [
          (radialX * cos - radialZ * sin) * 0.7,
          0.45 + random() * 0.4,
          (radialX * sin + radialZ * cos) * 0.7
        ],
        // Data term dominates the jitter so a badly overdue page visibly
        // burns farther than a barely overdue one.
        reach: 0.35 + Math.min(node.overdueRatio, 3) * 0.3 + random() * 0.08,
        phase: random(),
        speed: 0.11 + random() * 0.08
      });
    }
  }
  return particles;
}

// Stem sparks: draft changes waiting on the human gate rise along their stems.
export function buildStemParticles(proposalNodes: LayoutNode[], perNode = 2, maxParticles = 30): StemParticle[] {
  const particles: StemParticle[] = [];
  const sorted = [...proposalNodes].sort((a, b) => a.id.localeCompare(b.id));
  for (const node of sorted) {
    if (particles.length >= maxParticles) break;
    const random = seededRandom(node.id.split("").reduce((total, char) => (total * 37 + char.charCodeAt(0)) % 2147483000, 5) + 47);
    for (let index = 0; index < perNode && particles.length < maxParticles; index += 1) {
      particles.push({
        kind: "stem",
        base: [node.position[0], 0, node.position[2]],
        top: node.position,
        phase: random(),
        speed: 0.22 + random() * 0.14
      });
    }
  }
  return particles;
}

// Analytic evaluation: position + alpha as pure functions of time.

export function auraPoint(particle: AuraParticle, t: number): [number, number, number, number] {
  const angle = particle.phase * Math.PI * 2 + t * particle.speed * Math.PI * 2;
  const radius = particle.radius + Math.sin(angle * 2 + particle.phase * 9) * particle.wobble;
  const y = particle.yBase + Math.sin(angle * 3 + particle.phase * 5) * 0.06;
  return [Math.cos(angle) * radius, y, Math.sin(angle) * radius, 0.55 + Math.sin(angle * 2) * 0.25];
}

export function flowPoint(particle: FlowParticle, t: number): [number, number, number, number] {
  const u = (particle.phase + t * particle.speed) % 1;
  const inverse = 1 - u;
  const x = inverse * inverse * particle.from[0] + 2 * inverse * u * particle.control[0] + u * u * particle.to[0];
  const y = inverse * inverse * particle.from[1] + 2 * inverse * u * particle.control[1] + u * u * particle.to[1];
  const z = inverse * inverse * particle.from[2] + 2 * inverse * u * particle.control[2] + u * u * particle.to[2];
  return [x, y, z, Math.sin(u * Math.PI)];
}

export function emberPoint(particle: EmberParticle, t: number): [number, number, number, number] {
  const u = (particle.phase + t * particle.speed) % 1;
  const drift = u * particle.reach;
  return [
    particle.origin[0] + particle.direction[0] * drift,
    particle.origin[1] + particle.direction[1] * drift,
    particle.origin[2] + particle.direction[2] * drift,
    (1 - u) * (1 - u) * 0.9
  ];
}

export function stemPoint(particle: StemParticle, t: number): [number, number, number, number] {
  const u = (particle.phase + t * particle.speed) % 1;
  return [
    particle.base[0] + (particle.top[0] - particle.base[0]) * u,
    particle.base[1] + (particle.top[1] - particle.base[1]) * u,
    particle.base[2] + (particle.top[2] - particle.base[2]) * u,
    Math.sin(u * Math.PI) * 0.85
  ];
}
