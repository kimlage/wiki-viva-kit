// Particle layers + ambient driver: the generic ParticleCloud renderer, the
// composed SceneParticles group (aura, flows, stale embers, proposal stems,
// opt-in evidence-gap motes), the isEvidenceGap rule they share with the
// census, and the AmbientDriver pulsing the attention materials each frame.

import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { edgeStyle, isRawData, trustColor } from "../../data/presentation";
import { glowTexture } from "../glow";
import {
  auraPoint,
  buildAuraParticles,
  buildEmberParticles,
  buildFlowParticles,
  buildGapParticles,
  buildStemParticles,
  emberPoint,
  flowPoint,
  gapPoint,
  stemPoint
} from "../particles";
import type { FlowEdgeInput } from "../particles";
import type { WorldLayout } from "../perspectives";
import { edgeControlPoint } from "./materials";
import type { SceneEdge } from "./materials";

function ParticleCloud<P>({
  particles,
  evaluate,
  size,
  baseColor,
  colorFor
}: {
  particles: P[];
  evaluate: (particle: P, t: number) => [number, number, number, number];
  size: number;
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
    const t = state.clock.elapsedTime;
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
        size={size}
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
  showGaps
}: {
  layout: WorldLayout;
  flowEdges: SceneEdge[];
  activityLevel: number;
  quality: string;
  motion: boolean;
  showGaps: boolean;
}) {
  const rich = quality === "rich";
  const aura = useMemo(() => buildAuraParticles(activityLevel, rich ? 120 : 60), [activityLevel, rich]);
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
  const flow = useMemo(() => buildFlowParticles(flowInputs, rich ? 2 : 1, rich ? 72 : 36), [flowInputs, rich]);
  const embers = useMemo(
    () => buildEmberParticles(layout.nodes.filter((node) => node.freshness_state === "stale"), rich ? 5 : 3, rich ? 60 : 30),
    [layout.nodes, rich]
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
            rich ? 140 : 70
          )
        : [],
    [layout.nodes, rich, showGaps]
  );
  if (!motion || quality === "compact") return null;
  return (
    <group>
      <ParticleCloud particles={aura} evaluate={auraPoint} size={0.62} baseColor={trustColor("root")} />
      <ParticleCloud particles={flow} evaluate={flowPoint} size={0.58} colorFor={flowParticleColor} />
      <ParticleCloud particles={embers} evaluate={emberPoint} size={0.6} baseColor="#ffd27a" />
      <ParticleCloud particles={stems} evaluate={stemPoint} size={0.6} baseColor="#e2aaff" />
      {gaps.length > 0 && <ParticleCloud particles={gaps} evaluate={gapPoint} size={0.5} baseColor="#8b93c9" />}
    </group>
  );
}

export function AmbientDriver({
  enabled,
  rootRef,
  pulses
}: {
  enabled: boolean;
  rootRef: React.RefObject<THREE.Mesh | null>;
  pulses: React.RefObject<{ stale: THREE.SpriteMaterial[]; highlight: THREE.SpriteMaterial[]; staleMaterials: THREE.MeshStandardMaterial[] }>;
}) {
  useFrame((state) => {
    if (!enabled) return;
    const t = state.clock.elapsedTime;
    if (rootRef.current) {
      const breath = 1 + Math.sin(t * Math.PI * 0.5) * 0.03;
      rootRef.current.scale.setScalar(0.5 * breath);
    }
    // Pulse AROUND the static 0.5 base (never below the no-motion floor).
    const stalePulse = 0.5 + 0.12 * Math.sin((t * Math.PI * 2) / 2.4);
    for (const material of pulses.current?.stale ?? []) material.opacity = stalePulse;
    const staleEmissive = 0.9 + 0.35 * Math.sin((t * Math.PI * 2) / 2.4);
    for (const material of pulses.current?.staleMaterials ?? []) material.emissiveIntensity = staleEmissive;
    const highlightPulse = 0.5 + 0.18 * Math.sin((t * Math.PI * 2) / 1.5);
    for (const material of pulses.current?.highlight ?? []) material.opacity = highlightPulse;
  });
  return null;
}
