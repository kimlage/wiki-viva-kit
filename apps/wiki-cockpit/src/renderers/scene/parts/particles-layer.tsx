// Particle layers + ambient driver: the generic ParticleCloud renderer, the
// composed SceneParticles group (aura, flows, stale embers, proposal stems,
// opt-in evidence-gap motes), the isEvidenceGap rule they share with the
// census, and the AmbientDriver pulsing the attention materials each frame.

import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { contextStyle, edgeStyle, isRawData, trustColor } from "../../../data/presentation";
import { glowTexture } from "../glow";
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
} from "../../../scene/particles";
import type { FlowEdgeInput, GroupPullInput } from "../../../scene/particles";
import type { WorldLayout } from "../../../scene/perspectives";
import { edgeControlPoint } from "./materials";
import type { SceneEdge } from "./materials";

function ParticleCloud<P>({
  particles,
  evaluate,
  size,
  glow,
  motionScale,
  baseColor,
  colorFor
}: {
  particles: P[];
  evaluate: (particle: P, t: number) => [number, number, number, number];
  size: number;
  glow: number;
  motionScale: number;
  baseColor?: string;
  colorFor?: (particle: P) => string;
}) {
  const geometryRef = useRef<THREE.BufferGeometry>(null);
  const texture = glowTexture();
  const buffers = useMemo(
    () => ({
      positions: new Float32Array(particles.length * 3),
      colors: new Float32Array(particles.length * 3),
      tints: particles.map((particle) => new THREE.Color(colorFor ? colorFor(particle) : baseColor || "#6bd7ff"))
    }),
    [baseColor, colorFor, particles]
  );
  useFrame((state) => {
    const geometry = geometryRef.current;
    if (!geometry || particles.length === 0) return;
    const t = state.clock.elapsedTime * motionScale;
    for (let index = 0; index < particles.length; index += 1) {
      const [x, y, z, alpha] = evaluate(particles[index], t);
      buffers.positions[index * 3] = x;
      buffers.positions[index * 3 + 1] = y;
      buffers.positions[index * 3 + 2] = z;
      const tint = buffers.tints[index];
      buffers.colors[index * 3] = tint.r * alpha;
      buffers.colors[index * 3 + 1] = tint.g * alpha;
      buffers.colors[index * 3 + 2] = tint.b * alpha;
    }
    geometry.attributes.position.needsUpdate = true;
    geometry.attributes.color.needsUpdate = true;
  });
  if (particles.length === 0 || !texture) return null;
  return (
    <points frustumCulled={false}>
      <bufferGeometry ref={geometryRef}>
        <bufferAttribute attach="attributes-position" args={[buffers.positions, 3]} />
        <bufferAttribute attach="attributes-color" args={[buffers.colors, 3]} />
      </bufferGeometry>
      <pointsMaterial
        map={texture}
        size={size * glow}
        sizeAttenuation
        vertexColors
        transparent
        // Clip the near-invisible glow fringe: crisper motes, less overdraw in
        // dense clouds, without hardening the soft additive core.
        alphaTest={0.02}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        toneMapped={false}
      />
    </points>
  );
}

// Hoisted so its identity is stable across renders — an inline arrow here would
// bust ParticleCloud's buffer memo (keyed on colorFor) and rebuild the typed
// arrays every frame the parent re-renders.
function flowParticleColor(particle: { color: string }): string {
  return particle.color;
}

// An evidence gap: a content page that cites NO source. Structural nodes (root
// index, context hubs) and the raw/source layer itself are exempt — they are not
// expected to carry citations. On the real wiki this is the single biggest
// variance (212/532 pages) and it was invisible until the gap cloud.
export function isEvidenceGap(pageType: string, sourceRefCount: number): boolean {
  if (pageType === "root_index" || pageType === "context_hub") return false;
  if (isRawData(pageType)) return false;
  return sourceRefCount === 0;
}

export function SceneParticles({
  layout,
  flowEdges,
  activityLevel,
  quality,
  motion,
  showGaps,
  density = 1,
  glow = 1,
  motionScale = 1,
  enabled = true,
  onCount
}: {
  layout: WorldLayout;
  flowEdges: SceneEdge[];
  activityLevel: number;
  quality: string;
  motion: boolean;
  showGaps: boolean;
  density?: number;
  glow?: number;
  motionScale?: number;
  enabled?: boolean;
  onCount?: (count: number) => void;
}) {
  const rich = quality === "rich";
  const budget = useMemo(() => particleLodBudget(layout, rich), [layout, rich]);
  const scaledBudget = useMemo(
    () => ({
      auraMax: Math.max(0, Math.round(budget.auraMax * density)),
      flowMax: Math.max(0, Math.round(budget.flowMax * density)),
      groupInputLimit: Math.max(1, Math.round(budget.groupInputLimit * density)),
      groupPullMax: Math.max(0, Math.round(budget.groupPullMax * density)),
      emberMax: Math.max(0, Math.round(budget.emberMax * density)),
      gapMax: Math.max(0, Math.round(budget.gapMax * density))
    }),
    [budget, density]
  );
  const aura = useMemo(() => buildAuraParticles(activityLevel * density, scaledBudget.auraMax), [activityLevel, density, scaledBudget.auraMax]);
  const flowInputs = useMemo<FlowEdgeInput[]>(
    () =>
      flowEdges.map((edge) => ({
        from: edge.from.position,
        control: edgeControlPoint(edge.from.position, edge.to.position, edge.type),
        to: edge.to.position,
        color: edgeStyle(edge.type).color,
        key: `${edge.from.id}->${edge.to.id}:${edge.type}`
      })),
    [flowEdges]
  );
  const flow = useMemo(() => buildFlowParticles(flowInputs, rich ? 2 : 1, scaledBudget.flowMax), [flowInputs, rich, scaledBudget.flowMax]);
  const groupPullInputs = useMemo<GroupPullInput[]>(() => {
    const center = layout.nodes.find((node) => node.isRoot && node.isGroup);
    if (!center) return [];
    const memberIds = new Set(center.groupMemberIds ?? []);
    const previewIds = new Set(center.groupPreviewIds ?? []);
    const centerPoint = new THREE.Vector3(...center.position);
    const limit = scaledBudget.groupInputLimit;
    return layout.nodes
      .filter((node) => {
        if (node.id === center.id || node.isGroup) return false;
        return memberIds.has(node.id) || previewIds.has(node.id);
      })
      .sort((a, b) => centerPoint.distanceTo(new THREE.Vector3(...a.position)) - centerPoint.distanceTo(new THREE.Vector3(...b.position)))
      .slice(0, limit)
      .map((node) => ({
        from: node.position,
        to: center.position,
        color: contextStyle(node.context).accent,
        key: `${node.id}->${center.id}:group_pull`
      }));
  }, [scaledBudget.groupInputLimit, layout.nodes]);
  const groupPull = useMemo(() => buildGroupPullParticles(groupPullInputs, rich ? 2 : 1, scaledBudget.groupPullMax), [groupPullInputs, rich, scaledBudget.groupPullMax]);
  const embers = useMemo(
    () => buildEmberParticles(layout.nodes.filter((node) => node.freshness_state === "stale"), rich ? 5 : 3, scaledBudget.emberMax),
    [layout.nodes, rich, scaledBudget.emberMax]
  );
  const stems = useMemo(
    () => buildStemParticles(layout.nodes.filter((node) => node.approved_state === "proposal" && node.position[1] > 0.05), 3, 24),
    [layout.nodes]
  );
  // Gap motes are opt-in (the ?filter=unsourced lens) so they never compete with
  // embers at rest. Cold indigo that SINKS: a page quietly missing its evidence,
  // the visual inverse of the rising proposal stems.
  const gaps = useMemo(
    () =>
      showGaps
        ? buildGapParticles(
            layout.nodes.filter((node) => isEvidenceGap(node.page_type, node.source_ref_count)),
            scaledBudget.gapMax
          )
        : [],
    [layout.nodes, scaledBudget.gapMax, showGaps]
  );
  const rendered = enabled && motion && quality !== "compact" && motionScale > 0.01;
  const renderedCount = rendered ? aura.length + flow.length + groupPull.length + embers.length + stems.length + gaps.length : 0;
  useEffect(() => onCount?.(renderedCount), [onCount, renderedCount]);
  if (!rendered) return null;
  return (
    <group>
      <ParticleCloud particles={aura} evaluate={auraPoint} size={0.62} glow={glow} motionScale={motionScale} baseColor={trustColor("root")} />
      <ParticleCloud particles={flow} evaluate={flowPoint} size={0.58} glow={glow} motionScale={motionScale} colorFor={flowParticleColor} />
      <ParticleCloud particles={groupPull} evaluate={groupPullPoint} size={0.54} glow={glow} motionScale={motionScale} colorFor={flowParticleColor} />
      <ParticleCloud particles={embers} evaluate={emberPoint} size={0.6} glow={glow} motionScale={motionScale} baseColor="#ffd27a" />
      <ParticleCloud particles={stems} evaluate={stemPoint} size={0.6} glow={glow} motionScale={motionScale} baseColor="#e2aaff" />
      {gaps.length > 0 && <ParticleCloud particles={gaps} evaluate={gapPoint} size={0.5} glow={glow} motionScale={motionScale} baseColor="#8b93c9" />}
    </group>
  );
}

export function AmbientDriver({
  enabled,
  rootRef,
  pulses,
  motionScale = 1,
  glow = 1
}: {
  enabled: boolean;
  rootRef: React.RefObject<THREE.Mesh | null>;
  pulses: React.RefObject<{ stale: THREE.SpriteMaterial[]; highlight: THREE.SpriteMaterial[]; staleMaterials: THREE.MeshStandardMaterial[] }>;
  motionScale?: number;
  glow?: number;
}) {
  useFrame((state) => {
    if (!enabled || motionScale <= 0.01) return;
    const t = state.clock.elapsedTime * motionScale;
    if (rootRef.current) {
      const breath = 1 + Math.sin(t * Math.PI * 0.5) * (0.02 + 0.015 * glow);
      rootRef.current.scale.setScalar(0.5 * breath);
    }
    // Pulse AROUND the static 0.5 base (never below the no-motion floor).
    const stalePulse = 0.5 + 0.12 * glow * Math.sin((t * Math.PI * 2) / 2.4);
    for (const material of pulses.current?.stale ?? []) material.opacity = stalePulse;
    const staleEmissive = 0.9 + 0.35 * glow * Math.sin((t * Math.PI * 2) / 2.4);
    for (const material of pulses.current?.staleMaterials ?? []) material.emissiveIntensity = staleEmissive;
    const highlightPulse = 0.5 + 0.18 * glow * Math.sin((t * Math.PI * 2) / 1.5);
    for (const material of pulses.current?.highlight ?? []) material.opacity = highlightPulse;
  });
  return null;
}
