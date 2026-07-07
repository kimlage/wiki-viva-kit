// Node rendering: instanced node meshes with MORPH tweening (nodes keep their
// identity across perspective switches), the honest aggregates (cluster-stars,
// horizon beacons), and the sprite layers — attention glows, risk/evidence
// rings and the ambient starfield.

import { Html } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import type { ThreeEvent } from "@react-three/fiber";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { t } from "../../data/i18n";
import { agedColor, contextStyle, edgeStyle, trustColor, worldGroupLabel } from "../../data/presentation";
import { glowTexture, ringTexture } from "../glow";
import type { LayoutNode, ScenePerformanceProfile } from "../layout";
import type { Beacon, ClusterStar } from "../perspectives";
import { nodeTrustKey, superShape, trustDisplayColor, trustMaterial, TRUST_MATERIALS } from "./materials";
import type { SuperShape, TrustKey } from "./materials";

type NodeGroup = {
  key: string;
  shape: SuperShape;
  material: (typeof TRUST_MATERIALS)[TrustKey | "root"];
  trust: TrustKey | "root";
  dimmed: boolean;
  items: LayoutNode[];
};

export type MorphState = {
  from: Map<string, [number, number, number]>;
  start: number | null;
  duration: number;
  active: boolean;
};

export function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

function InstancedNodeMesh({
  group,
  profile,
  selectedId,
  morph,
  onSelect,
  onHover,
  registerMaterial
}: {
  group: NodeGroup;
  profile: ScenePerformanceProfile;
  selectedId: string;
  morph: React.RefObject<MorphState>;
  onSelect: (node: LayoutNode) => void;
  onHover: (node: LayoutNode | null, event?: ThreeEvent<PointerEvent>) => void;
  registerMaterial: (trust: TrustKey | "root", dimmed: boolean, material: THREE.MeshStandardMaterial | null) => void;
}) {
  const ref = useRef<THREE.InstancedMesh>(null);
  // Invisible companion mesh with generously enlarged spheres that OWNS the
  // pointer events. Tiny nodes at 532-page scale are almost unclickable and
  // hover flickers between adjacent instanced meshes; a fat, uniform hit target
  // makes clicking/hovering reliable without changing the visuals.
  const hitRef = useRef<THREE.InstancedMesh>(null);
  const { invalidate } = useThree();
  const matrix = useMemo(() => new THREE.Matrix4(), []);
  const hitMatrix = useMemo(() => new THREE.Matrix4(), []);
  const quaternion = useMemo(() => new THREE.Quaternion(), []);
  const scaleVec = useMemo(() => new THREE.Vector3(), []);
  const posVec = useMemo(() => new THREE.Vector3(), []);

  const applyPositions = useCallback(
    (t: number) => {
      if (!ref.current) return;
      const state = morph.current;
      group.items.forEach((node, index) => {
        const selected = node.id === selectedId || node.path === selectedId ? 1.18 : 1;
        const from = state?.from.get(node.id);
        // Per-context stagger keeps the morph readable at scale.
        const stagger = ((node.context || "system").length % 5) * 0.06;
        const local = Math.min(Math.max((t - stagger) / Math.max(1 - stagger, 0.01), 0), 1);
        const eased = easeOutCubic(local);
        const x = from ? from[0] + (node.position[0] - from[0]) * eased : node.position[0];
        const y = from ? from[1] + (node.position[1] - from[1]) * eased : node.position[1];
        const z = from ? from[2] + (node.position[2] - from[2]) * eased : node.position[2];
        const dampen = node.faint ? 0.85 : 1;
        const visScale = node.scale * selected * dampen;
        posVec.set(x, y, z);
        matrix.compose(posVec, quaternion, scaleVec.set(visScale, visScale, visScale));
        ref.current?.setMatrixAt(index, matrix);
        // Hit sphere: at least a comfortable minimum radius, ~1.7× the node.
        const hit = Math.max(visScale * 1.7, 0.34);
        hitMatrix.compose(posVec, quaternion, scaleVec.set(hit, hit, hit));
        hitRef.current?.setMatrixAt(index, hitMatrix);
      });
      if (ref.current) ref.current.instanceMatrix.needsUpdate = true;
      if (hitRef.current) hitRef.current.instanceMatrix.needsUpdate = true;
    },
    [group.items, matrix, hitMatrix, morph, quaternion, scaleVec, posVec, selectedId]
  );

  useLayoutEffect(() => {
    applyPositions(morph.current?.active ? 0 : 1);
    invalidate();
  }, [applyPositions, invalidate, morph]);

  useFrame((state) => {
    const morphState = morph.current;
    if (!morphState?.active) return;
    if (morphState.start === null) morphState.start = state.clock.elapsedTime;
    const t = Math.min((state.clock.elapsedTime - morphState.start) / morphState.duration, 1);
    applyPositions(t);
    state.invalidate();
    if (t >= 1) morphState.active = false;
  });

  const dim = group.dimmed ? 0.25 : 1;
  // The shader multiplies material.color × instanceColor, so the material base
  // is WHITE (scaled by the dim factor) and each instance carries its context
  // hue with the state tone premixed (agedColor). Emissive stays uniform per
  // partition — that is exactly the per-state attention channel.
  const baseColor = useMemo(() => new THREE.Color(1, 1, 1).multiplyScalar(dim), [dim]);
  const emissiveColor = useMemo(() => new THREE.Color(trustColor(group.trust as TrustKey | "root")).multiplyScalar(dim), [dim, group.trust]);

  // Per-instance context colors. useLayoutEffect (pre-paint, refs attached) so
  // no white-flash frame; keyed on group.items — the same dependency
  // applyPositions uses — so same-length membership swaps recolor correctly.
  // NEVER inside the morph loop: instanceColor is independent of matrices.
  const colorScratch = useMemo(() => new THREE.Color(), []);
  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    group.items.forEach((node, index) => {
      const hex = group.trust === "root" ? trustColor("root") : agedColor(contextStyle(node.context).accent, group.trust as TrustKey);
      mesh.setColorAt(index, colorScratch.set(hex));
    });
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    invalidate();
  }, [colorScratch, group.items, group.trust, invalidate]);
  return (
    <group>
      <instancedMesh
        ref={ref}
        args={[undefined, undefined, Math.max(group.items.length, 1)]}
        // Never frustum-cull: three culls an InstancedMesh by its GEOMETRY
        // bounding sphere (a unit sphere at the origin), not by the instance
        // spread, so drilling/focusing away from the center would cull the whole
        // mesh — every node would vanish and become unclickable. Counts are
        // capped at ~160, so skipping the cull test is free.
        frustumCulled={false}
      >
        {group.shape === "crystal" ? (
          <octahedronGeometry args={[1, 0]} />
        ) : group.shape === "hub" ? (
          <icosahedronGeometry args={[1, 1]} />
        ) : group.shape === "frame" ? (
          <octahedronGeometry args={[1, 1]} />
        ) : (
          <sphereGeometry args={[1, profile.geometrySegments, profile.geometrySegments]} />
        )}
        <meshStandardMaterial
          ref={(material) => registerMaterial(group.trust, group.dimmed, material)}
          color={baseColor}
          emissive={emissiveColor}
          emissiveIntensity={group.material.emissiveIntensity * dim}
          transparent={group.material.opacity < 1}
          opacity={group.material.opacity}
          roughness={0.5}
          metalness={0.1}
          flatShading={group.shape !== "sphere"}
          // Blueprints: molds render as wireframe — geometry, not a new color.
          wireframe={group.shape === "frame"}
        />
      </instancedMesh>
      {/* Invisible, generously-sized hit layer that owns all pointer events so
          tiny nodes stay reliably clickable/hoverable at scale. */}
      <instancedMesh
        ref={hitRef}
        args={[undefined, undefined, Math.max(group.items.length, 1)]}
        frustumCulled={false}
        onClick={(event) => {
          event.stopPropagation();
          if (typeof event.instanceId === "number" && group.items[event.instanceId]) onSelect(group.items[event.instanceId]);
        }}
        onPointerMove={(event) => {
          event.stopPropagation();
          if (typeof event.instanceId === "number" && group.items[event.instanceId]) onHover(group.items[event.instanceId], event);
        }}
        onPointerOut={() => onHover(null)}
      >
        <sphereGeometry args={[1, 8, 8]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} colorWrite={false} />
      </instancedMesh>
    </group>
  );
}

export function NodeInstances({
  nodes,
  profile,
  selectedId,
  morph,
  dimTest,
  onSelect,
  onHover,
  registerMaterial
}: {
  nodes: LayoutNode[];
  profile: ScenePerformanceProfile;
  selectedId: string;
  morph: React.RefObject<MorphState>;
  dimTest: (node: LayoutNode) => boolean;
  onSelect: (node: LayoutNode) => void;
  onHover: (node: LayoutNode | null, event?: ThreeEvent<PointerEvent>) => void;
  registerMaterial: (trust: TrustKey | "root", dimmed: boolean, material: THREE.MeshStandardMaterial | null) => void;
}) {
  const groups = useMemo(() => {
    const byKey = new Map<string, NodeGroup>();
    for (const node of nodes) {
      const shape = superShape(node.page_type);
      const trust = node.isRoot ? ("root" as const) : nodeTrustKey(node);
      const dimmed = dimTest(node);
      const key = `${shape}:${trust}:${dimmed ? "dim" : "lit"}`;
      const group = byKey.get(key) ?? { key, shape, trust, material: TRUST_MATERIALS[trust], dimmed, items: [] };
      group.items.push(node);
      byKey.set(key, group);
    }
    return [...byKey.values()].sort((a, b) => a.key.localeCompare(b.key));
  }, [dimTest, nodes]);
  return (
    <>
      {groups.map((group) => (
        <InstancedNodeMesh
          key={group.key}
          group={group}
          profile={profile}
          selectedId={selectedId}
          morph={morph}
          onSelect={onSelect}
          onHover={onHover}
          registerMaterial={registerMaterial}
        />
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// Cluster-stars and horizon beacons: the honest aggregates and lateral jumps.

export function ClusterStars({ stars, onDrill }: { stars: ClusterStar[]; onDrill: (star: ClusterStar) => void }) {
  const texture = glowTexture();
  return (
    <group>
      {stars.map((star) => (
        <group key={star.key} position={star.position}>
          <mesh
            onClick={(event) => {
              event.stopPropagation();
              onDrill(star);
            }}
          >
            <icosahedronGeometry args={[star.scale, 1]} />
            <meshStandardMaterial color="#334a5c" emissive="#6bd7ff" emissiveIntensity={0.5} flatShading toneMapped={false} />
          </mesh>
          {texture && (
            <sprite scale={[star.scale * 2.6, star.scale * 2.6, 1]}>
              <spriteMaterial map={texture} color="#6bd7ff" transparent opacity={0.25} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
            </sprite>
          )}
          <Html position={[0, star.scale * 2 + 0.16, 0]} center distanceFactor={5.2} wrapperClass="sceneHtmlLabel" className="clusterStarLabel" zIndexRange={[35, 0]}>
            <button type="button" onClick={() => onDrill(star)} title={star.drill ? t("scene.openHiddenTitle", { n: star.count }) : t("scene.showingMore", { n: star.count, label: worldGroupLabel(star.kind, star.labelKey) })}>
              <strong>+{star.count}</strong>
              <span className="rimDots" aria-hidden>
                {star.histogram.fresh > 0 && <i style={{ background: trustColor("fresh") }} />}
                {star.histogram.stale > 0 && <i style={{ background: trustColor("stale") }} />}
                {star.histogram.proposal > 0 && <i style={{ background: trustColor("proposal") }} />}
                {star.histogram.unknown > 0 && <i style={{ background: trustColor("unknown") }} />}
                {star.histogram.risk > 0 && <i style={{ background: trustColor("risk") }} />}
              </span>
            </button>
          </Html>
        </group>
      ))}
    </group>
  );
}

export function HorizonBeacons({ beacons, onJump }: { beacons: Beacon[]; onJump: (context: string) => void }) {
  return (
    <group>
      {beacons.map((beacon) => {
        const style = contextStyle(beacon.context);
        return (
          <Html key={`beacon-${beacon.context}`} position={beacon.position} center distanceFactor={6} wrapperClass="sceneHtmlLabel" className="horizonBeacon" zIndexRange={[25, 0]}>
            <button style={{ borderColor: style.accent }} onClick={() => onJump(beacon.context)} type="button" title={t("scene.goTo", { label: style.label })}>
              <strong>{style.label}</strong>
              <small>
                {beacon.count}
                {beacon.attentionCount > 0 ? ` · ${beacon.attentionCount}!` : ""}
              </small>
            </button>
          </Html>
        );
      })}
    </group>
  );
}

export function GlowSprites({
  nodes,
  highlightedIds,
  approvalIds,
  selectedId,
  walkTargetId,
  registerPulse
}: {
  nodes: LayoutNode[];
  highlightedIds: Set<string>;
  approvalIds: Set<string>;
  selectedId: string;
  walkTargetId: string;
  registerPulse: (kind: "stale" | "highlight", material: THREE.SpriteMaterial | null) => void;
}) {
  const texture = glowTexture();
  const glowing = useMemo(
    () =>
      nodes.filter(
        (node) =>
          trustMaterial(node).glows ||
          node.risk_flags.length > 0 ||
          highlightedIds.has(node.id) ||
          highlightedIds.has(node.path) ||
          approvalIds.has(node.id) ||
          approvalIds.has(node.path) ||
          node.id === selectedId ||
          node.path === selectedId ||
          node.id === walkTargetId
      ),
    [highlightedIds, approvalIds, nodes, selectedId, walkTargetId]
  );
  if (!texture) return null;
  return (
    <group>
      {glowing.map((node) => {
        const approval = approvalIds.has(node.id) || approvalIds.has(node.path);
        const highlighted = highlightedIds.has(node.id) || highlightedIds.has(node.path);
        const selected = node.id === selectedId || node.path === selectedId || node.id === walkTargetId;
        const trust = nodeTrustKey(node);
        // Approval (a changed content page at the gate) gets a distinct PURPLE
        // halo — the loudest thing, pulsing — so the operator SEES which pages
        // the human gate is about, not just a list in the dock. Search/packet/
        // hover stay cyan; the two never collide.
        const color = approval
          ? "#c57cff"
          : selected
          ? "#dff8ff"
          : highlighted
          ? "#79e6ff"
          : trustDisplayColor(node);
        const size = node.scale * (approval ? 6.8 : highlighted ? 6.4 : selected ? 6 : 4.2);
        // Stale's STATIC base is strong enough to read without animation —
        // reduced-motion/compact tiers must never lose the attention cue.
        const opacity = approval ? 0.82 : highlighted ? 0.75 : selected ? 0.62 : trust === "stale" ? 0.5 : 0.3;
        return (
          <sprite key={`glow-${node.id}`} position={node.position} scale={[size, size, 1]}>
            <spriteMaterial
              ref={(material) => {
                if (trust === "stale" && !selected && !highlighted && !approval) registerPulse("stale", material);
                if (highlighted || approval) registerPulse("highlight", material);
              }}
              map={texture}
              color={color}
              transparent
              opacity={opacity}
              blending={THREE.AdditiveBlending}
              depthWrite={false}
              toneMapped={false}
            />
          </sprite>
        );
      })}
    </group>
  );
}

export function RingSprites({ nodes }: { nodes: LayoutNode[] }) {
  const riskTexture = ringTexture(0.09);
  const evidenceTexture = ringTexture(0.05);
  if (!riskTexture || !evidenceTexture) return null;
  const risky = nodes.filter((node) => node.risk_flags.length > 0);
  const evidenced = nodes.filter((node) => node.source_ref_count > 0 && node.risk_flags.length === 0);
  return (
    <group>
      {risky.map((node) => (
        <sprite key={`risk-${node.id}`} position={node.position} scale={[node.scale * 3.6, node.scale * 3.6, 1]}>
          <spriteMaterial map={riskTexture} color={trustColor("risk")} transparent opacity={0.85} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
        </sprite>
      ))}
      {evidenced.map((node) => (
        <sprite key={`evidence-${node.id}`} position={node.position} scale={[node.scale * 3, node.scale * 3, 1]}>
          <spriteMaterial
            map={evidenceTexture}
            color={edgeStyle("source_ref").color}
            transparent
            opacity={Math.min(0.35 + node.source_ref_count * 0.07, 0.8)}
            blending={THREE.AdditiveBlending}
            depthWrite={false}
            toneMapped={false}
          />
        </sprite>
      ))}
    </group>
  );
}

export function StarField({ quality }: { quality: string }) {
  const texture = glowTexture();
  const object = useMemo(() => {
    const layers = [
      { count: quality === "rich" ? 500 : quality === "balanced" ? 300 : 150, color: "#4d708c", size: 0.06, opacity: 0.5, minR: 16, maxR: 30 },
      { count: quality === "rich" ? 300 : quality === "balanced" ? 180 : 80, color: "#a8d8f0", size: 0.14, opacity: 0.35, minR: 12, maxR: 24 }
    ];
    let seed = 1337;
    const random = () => {
      seed = (seed * 16807) % 2147483647;
      return (seed - 1) / 2147483646;
    };
    return layers.map((layer) => {
      const positions = new Float32Array(layer.count * 3);
      for (let index = 0; index < layer.count; index += 1) {
        const radius = layer.minR + random() * (layer.maxR - layer.minR);
        const theta = random() * Math.PI * 2;
        const phi = Math.acos(random() * 2 - 1);
        positions[index * 3] = radius * Math.sin(phi) * Math.cos(theta);
        positions[index * 3 + 1] = radius * Math.cos(phi) * 0.6;
        positions[index * 3 + 2] = radius * Math.sin(phi) * Math.sin(theta);
      }
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      const material = new THREE.PointsMaterial({
        color: layer.color,
        size: layer.size,
        sizeAttenuation: true,
        transparent: true,
        opacity: layer.opacity,
        map: texture ?? undefined,
        alphaTest: 0.01,
        blending: THREE.AdditiveBlending,
        depthWrite: false
      });
      return { points: new THREE.Points(geometry, material), geometry, material };
    });
  }, [quality, texture]);
  useEffect(() => {
    return () => {
      object.forEach((layer) => {
        layer.geometry.dispose();
        layer.material.dispose();
      });
    };
  }, [object]);
  return (
    <>
      {object.map((layer, index) => (
        <primitive object={layer.points} key={index} />
      ))}
    </>
  );
}
