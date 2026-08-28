// Node rendering: instanced node meshes with MORPH tweening (nodes keep their
// identity across perspective switches), the honest aggregates (cluster-stars,
// horizon beacons), and the sprite layers — attention glows, risk/evidence
// rings and the ambient starfield.

import { Html } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import type { ThreeEvent } from "@react-three/fiber";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from "react";
import type { RefObject } from "react";
import * as THREE from "three";
import { t } from "../../../data/i18n";
import { contextStyle, edgeStyle, pageTypeStyle, trustColor, worldGroupLabel } from "../../../data/presentation";
import { strongAttentionNodeIds, visualEncodingResolver } from "../../../data/visualEncoding";
import type { ResolvedVisualEncoding } from "../../../data/visualEncoding";
import { resolvePrimitiveForSlot } from "../../../data/visualPrimitives";
import type { VisualPrimitiveId, VisualSlotId } from "../../../data/visualPrimitives";
import type { AnchorRecord } from "../../../types";
import { glowTexture, ringTexture } from "../glow";
import { SCENE_FACETS } from "../../../scene/facets";
import { layoutNodeInstanceKeys } from "../../../scene/layout";
import type { LayoutNode, ScenePerformanceProfile, SceneQuality } from "../../../scene/layout";
import type { Beacon, ClusterStar } from "../../../scene/perspectives";
import type { OverlayId } from "../../../world/contracts";
import { motionProgress, motionStagger } from "../../../world/visual/motionGrammar";
import type { MotionIntent } from "../../../world/visual/motionGrammar";
import { nodeTrustKey, superShape, trustDisplayColor, trustMaterial, TRUST_MATERIALS } from "./materials";
import type { SuperShape, TrustKey } from "./materials";

type NodeGroup = {
  key: string;
  shape: SuperShape;
  fromEncoding: ResolvedVisualEncoding;
  encoding: ResolvedVisualEncoding;
  trust: TrustKey | "root";
  dimmed: boolean;
  items: LayoutNode[];
};

export type MorphState = {
  from: Map<string, [number, number, number]>;
  current?: Map<string, [number, number, number]>;
  start: number | null;
  duration: number;
  active: boolean;
  intent?: MotionIntent;
  sequence?: number;
};

/**
 * Geometry that cannot share the entity matrices stays hidden while the world
 * is changing shape, then resolves during the final quarter of the same
 * transaction. This keeps relation lines attached perceptually without adding
 * another animation clock.
 */
export function morphAttachmentOpacity(
  morph: MorphState | null | undefined,
  elapsedTime: number,
  baseOpacity = 1
): number {
  if (!morph?.active) return baseOpacity;
  if (morph.start === null || morph.duration <= 0) return 0;
  const progress = Math.min(Math.max((elapsedTime - morph.start) / morph.duration, 0), 1);
  const resolveProgress = Math.min(Math.max((progress - 0.72) / 0.28, 0), 1);
  return baseOpacity * motionProgress("overlay", resolveProgress);
}

export type OverlayTransitionState = {
  from: OverlayId;
  to: OverlayId;
  start: number | null;
  duration: number;
  active: boolean;
};

export type EntityMotionSample = {
  local: number;
  eased: number;
};

/**
 * A quadrant lens is a real spatial scope at the world root. Nodes outside the
 * selected territory must not remain as mouse-only WebGL hit targets after
 * their DOM labels disappear. Deeper collection drills own their complete
 * member set, so the lens no longer filters them.
 */
export function visibleSceneNodesForQuadrantLens(
  nodes: LayoutNode[],
  perspective: string,
  level: number,
  activeQuadrant?: string
): LayoutNode[] {
  const quadrant = activeQuadrant && SCENE_FACETS.includes(activeQuadrant as (typeof SCENE_FACETS)[number])
    ? activeQuadrant
    : null;
  if (perspective !== "quadrants" || level !== 0 || !quadrant) return nodes;
  return nodes.filter((node) => node.isRoot || node.quadrant === quadrant);
}

/** One entity clock for bodies, labels, halos, rings and group shells. */
export function entityMotionSample(
  key: string,
  progress: number,
  intent: MotionIntent = "view",
  maximumStagger = 0.1
): EntityMotionSample {
  const stagger = motionStagger(key, maximumStagger);
  const local = Math.min(Math.max((progress - stagger) / Math.max(1 - stagger, 0.01), 0), 1);
  return { local, eased: motionProgress(intent, local) };
}

export function overlayCrossfadeWeights(key: string, progress: number): { from: number; to: number } {
  const sample = entityMotionSample(key, progress, "overlay", 0.12).eased;
  return { from: 1 - sample, to: sample };
}

export function MorphingNodeGroup({
  node,
  morph,
  children
}: {
  node: LayoutNode;
  morph: RefObject<MorphState>;
  children: React.ReactNode;
}) {
  const ref = useRef<THREE.Group>(null);
  const { invalidate } = useThree();
  const applyPosition = useCallback(
    (progress: number) => {
      if (!ref.current) return;
      const state = morph.current;
      const from = state?.from.get(node.id);
      const { eased } = entityMotionSample(node.id, progress, state?.intent ?? "view");
      ref.current.position.set(
        from ? from[0] + (node.position[0] - from[0]) * eased : node.position[0],
        from ? from[1] + (node.position[1] - from[1]) * eased : node.position[1],
        from ? from[2] + (node.position[2] - from[2]) * eased : node.position[2]
      );
      state?.current?.set(node.id, [ref.current.position.x, ref.current.position.y, ref.current.position.z]);
    },
    [morph, node.id, node.position]
  );
  useLayoutEffect(() => {
    applyPosition(morph.current?.active ? 0 : 1);
    invalidate();
  }, [applyPosition, invalidate, morph]);
  useFrame((state) => {
    const current = morph.current;
    if (!current?.active) return;
    if (current.start === null) current.start = state.clock.elapsedTime;
    const progress = Math.min((state.clock.elapsedTime - current.start) / current.duration, 1);
    applyPosition(progress);
    state.invalidate();
  });
  return <group ref={ref}>{children}</group>;
}

export function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

export function groupDrillGrowthScale(
  node: Pick<LayoutNode, "isRoot" | "isGroup">,
  layoutLevel: number,
  hasTravelOrigin: boolean,
  t: number
): number {
  if (!node.isRoot || !node.isGroup || layoutLevel < 1 || !hasTravelOrigin) return 1;
  const safeT = Math.min(Math.max(t, 0), 1);
  const eased = easeOutCubic(safeT);
  const start = layoutLevel >= 2 ? 0.42 : 0.34;
  const overshoot = Math.sin(safeT * Math.PI) * (layoutLevel >= 2 ? 0.045 : 0.06);
  return Number(Math.min(1.04, start + (1 - start) * eased + overshoot).toFixed(4));
}

function InstancedNodeMesh({
  group,
  profile,
  selectedId,
  morph,
  overlayTransition,
  onSelect,
  onHover,
  registerMaterial
}: {
  group: NodeGroup;
  profile: ScenePerformanceProfile;
  selectedId: string;
  morph: React.RefObject<MorphState>;
  overlayTransition?: RefObject<OverlayTransitionState>;
  onSelect: (node: LayoutNode) => void;
  onHover: (node: LayoutNode | null, event?: ThreeEvent<PointerEvent>) => void;
  registerMaterial: (trust: TrustKey | "root", dimmed: boolean, material: THREE.MeshStandardMaterial | null) => void;
}) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const materialRef = useRef<THREE.MeshStandardMaterial | null>(null);
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
        // Stable per-entity stagger keeps dense layouts readable without
        // synchronizing by translated context-name length.
        const { eased } = entityMotionSample(node.id, t, state?.intent ?? "view");
        const x = from ? from[0] + (node.position[0] - from[0]) * eased : node.position[0];
        const y = from ? from[1] + (node.position[1] - from[1]) * eased : node.position[1];
        const z = from ? from[2] + (node.position[2] - from[2]) * eased : node.position[2];
        state?.current?.set(node.id, [x, y, z]);
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
  });

  const dim = group.dimmed ? 0.25 : 1;
  // The shader multiplies material.color × instanceColor, so the material base
  // is WHITE (scaled by the dim factor) and each instance carries its resolved
  // active-overlay color. Context is encoded by position/labels, never body hue.
  const baseColor = useMemo(() => new THREE.Color(1, 1, 1).multiplyScalar(dim), [dim]);
  const emissiveColor = useMemo(() => new THREE.Color(group.encoding.color).multiplyScalar(dim), [dim, group.encoding.color]);

  // Per-instance color keeps each entity identifiable while the shared group
  // material interpolates the exact previous/current opacity and emissive
  // states. Groups are split by both semantic states, so one material remains
  // honest for every instance it owns.
  const fromColor = useMemo(() => new THREE.Color(), []);
  const toColor = useMemo(() => new THREE.Color(), []);
  const mixedColor = useMemo(() => new THREE.Color(), []);
  const fromEmissive = useMemo(() => new THREE.Color(), []);
  const toEmissive = useMemo(() => new THREE.Color(), []);
  const applyOverlayEncoding = useCallback(
    (progress: number) => {
      const mesh = ref.current;
      const material = materialRef.current;
      if (!mesh || !material) return;
      const transition = overlayTransition?.current;
      const transitioning = Boolean(
        transition?.active &&
        transition.to === group.encoding.overlay &&
        transition.from === group.fromEncoding.overlay
      );
      group.items.forEach((node, index) => {
        const weights = transitioning ? overlayCrossfadeWeights(node.id, progress) : { from: 0, to: 1 };
        const previous = visualEncodingResolver.resolve(node, group.fromEncoding.overlay);
        const next = visualEncodingResolver.resolve(node, group.encoding.overlay);
        mixedColor.lerpColors(fromColor.set(previous.color), toColor.set(next.color), weights.to);
        mesh.setColorAt(index, mixedColor);
      });
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;

      const materialProgress = transitioning ? motionProgress("overlay", progress) : 1;
      material.emissive.lerpColors(
        fromEmissive.set(group.fromEncoding.color),
        toEmissive.set(group.encoding.color),
        materialProgress
      ).multiplyScalar(dim);
      material.emissiveIntensity = THREE.MathUtils.lerp(
        group.fromEncoding.emissive * dim,
        group.encoding.emissive * dim,
        materialProgress
      );
      material.opacity = THREE.MathUtils.lerp(
        group.fromEncoding.opacity,
        group.encoding.opacity,
        materialProgress
      );
    },
    [dim, fromColor, fromEmissive, group, mixedColor, overlayTransition, toColor, toEmissive]
  );

  useLayoutEffect(() => {
    const transition = overlayTransition?.current;
    const transitioning = Boolean(
      transition?.active &&
      transition.to === group.encoding.overlay &&
      transition.from === group.fromEncoding.overlay
    );
    applyOverlayEncoding(transitioning ? 0 : 1);
    invalidate();
  }, [applyOverlayEncoding, group.encoding.overlay, group.fromEncoding.overlay, invalidate, overlayTransition]);

  useFrame((state) => {
    const transition = overlayTransition?.current;
    if (!transition?.active || transition.to !== group.encoding.overlay) return;
    if (transition.start === null) transition.start = state.clock.elapsedTime;
    const progress = transition.duration <= 0
      ? 1
      : Math.min((state.clock.elapsedTime - transition.start) / transition.duration, 1);
    applyOverlayEncoding(progress);
    state.invalidate();
  });

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
        {group.shape === "source" ? (
          <boxGeometry args={[1, 0.18, 0.72]} />
        ) : group.shape === "crystal" ? (
          <octahedronGeometry args={[1, 0]} />
        ) : group.shape === "comet" ? (
          <coneGeometry args={[0.72, 1.35, 4]} />
        ) : group.shape === "slab" ? (
          <boxGeometry args={[1.26, 0.32, 0.62]} />
        ) : group.shape === "spark" ? (
          <torusGeometry args={[0.68, 0.08, 6, 32]} />
        ) : group.shape === "totem" ? (
          <cylinderGeometry args={[0.46, 0.62, 1.16, 14]} />
        ) : group.shape === "hub" ? (
          <icosahedronGeometry args={[1, 1]} />
        ) : group.shape === "frame" ? (
          <octahedronGeometry args={[1, 1]} />
        ) : (
          <sphereGeometry args={[1, profile.geometrySegments, profile.geometrySegments]} />
        )}
        <meshStandardMaterial
          ref={(material) => {
            materialRef.current = material;
            registerMaterial(group.trust, group.dimmed, material);
          }}
          color={baseColor}
          emissive={emissiveColor}
          emissiveIntensity={group.encoding.emissive * dim}
          transparent={group.fromEncoding.opacity < 1 || group.encoding.opacity < 1 || dim < 1}
          opacity={group.encoding.opacity}
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
  overlay,
  profile,
  selectedId,
  morph,
  overlayTransition,
  dimTest,
  onSelect,
  onHover,
  registerMaterial
}: {
  nodes: LayoutNode[];
  overlay: OverlayId;
  profile: ScenePerformanceProfile;
  selectedId: string;
  morph: React.RefObject<MorphState>;
  overlayTransition?: RefObject<OverlayTransitionState>;
  dimTest: (node: LayoutNode) => boolean;
  onSelect: (node: LayoutNode) => void;
  onHover: (node: LayoutNode | null, event?: ThreeEvent<PointerEvent>) => void;
  registerMaterial: (trust: TrustKey | "root", dimmed: boolean, material: THREE.MeshStandardMaterial | null) => void;
}) {
  const groups = useMemo(() => {
    const byKey = new Map<string, NodeGroup>();
    const transition = overlayTransition?.current;
    const fromOverlay = transition?.to === overlay ? transition.from : overlay;
    for (const node of nodes) {
      if (node.isGroup) continue;
      const shape = superShape(node.page_type);
      const trust = node.isRoot ? ("root" as const) : nodeTrustKey(node);
      const dimmed = dimTest(node);
      const fromEncoding = visualEncodingResolver.resolve(node, fromOverlay);
      const encoding = visualEncodingResolver.resolve(node, overlay);
      const key = `${shape}:${trust}:${fromEncoding.overlay}:${fromEncoding.state}->${encoding.overlay}:${encoding.state}:${dimmed ? "dim" : "lit"}`;
      const group = byKey.get(key) ?? { key, shape, trust, fromEncoding, encoding, dimmed, items: [] };
      group.items.push(node);
      byKey.set(key, group);
    }
    return [...byKey.values()].sort((a, b) => a.key.localeCompare(b.key));
  }, [dimTest, nodes, overlay, overlayTransition]);
  return (
    <>
      {groups.map((group) => (
        <InstancedNodeMesh
          key={group.key}
          group={group}
          profile={profile}
          selectedId={selectedId}
          morph={morph}
          overlayTransition={overlayTransition}
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
  registerPulse,
  morph
}: {
  nodes: LayoutNode[];
  highlightedIds: Set<string>;
  approvalIds: Set<string>;
  selectedId: string;
  walkTargetId: string;
  registerPulse: (kind: "stale" | "highlight", material: THREE.SpriteMaterial | null) => void;
  morph: RefObject<MorphState>;
}) {
  const texture = glowTexture();
  const glowing = useMemo(
    () =>
      nodes.filter((node) => {
        if (node.isRoot && node.isGroup) return false;
        return (
          trustMaterial(node).glows ||
          node.risk_flags.length > 0 ||
          highlightedIds.has(node.id) ||
          highlightedIds.has(node.path) ||
          approvalIds.has(node.id) ||
          approvalIds.has(node.path) ||
          node.id === selectedId ||
          node.path === selectedId ||
          node.id === walkTargetId
        );
      }),
    [highlightedIds, approvalIds, nodes, selectedId, walkTargetId]
  );
  if (!texture) return null;
  const instanceKeys = layoutNodeInstanceKeys(glowing);
  return (
    <group>
      {glowing.map((node, index) => {
        const approval = approvalIds.has(node.id) || approvalIds.has(node.path);
        const highlighted = highlightedIds.has(node.id) || highlightedIds.has(node.path);
        const selected = node.id === selectedId || node.path === selectedId || node.id === walkTargetId;
        const centerGroup = Boolean(node.isRoot && node.isGroup);
        const semanticFamily = semanticDetailFamily(node.page_type);
        const selectedSemantic = selected && Boolean(semanticFamily);
        const selectedSemanticColor = semanticFamily ? pageTypeStyle(`visual_group_${semanticFamily}`).accent : "";
        const trust = nodeTrustKey(node);
        // Approval (a changed content page at the gate) gets a distinct PURPLE
        // halo — the loudest thing, pulsing — so the operator SEES which pages
        // the human gate is about, not just a list in the dock. Search/packet/
        // hover stay cyan; the two never collide.
        const color = approval
          ? "#c57cff"
          : selectedSemantic
          ? selectedSemanticColor
          : selected
          ? "#dff8ff"
          : highlighted
          ? "#79e6ff"
          : trustDisplayColor(node);
        const size = node.scale * (centerGroup ? 1.65 : approval ? 6.8 : highlighted ? 6.4 : selectedSemantic ? 2.35 : selected ? 6 : 4.2);
        // Stale's STATIC base is strong enough to read without animation —
        // reduced-motion/compact tiers must never lose the attention cue.
        const opacity = centerGroup ? 0.18 : approval ? 0.82 : highlighted ? 0.75 : selectedSemantic ? 0.12 : selected ? 0.62 : trust === "stale" ? 0.5 : 0.3;
        return (
          <MorphingNodeGroup key={`glow-${instanceKeys[index]}`} node={node} morph={morph}>
            <sprite scale={[size, size, 1]}>
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
          </MorphingNodeGroup>
        );
      })}
    </group>
  );
}

export function RingSprites({
  nodes,
  overlay,
  morph,
  overlayTransition
}: {
  nodes: LayoutNode[];
  overlay: OverlayId;
  morph: RefObject<MorphState>;
  overlayTransition?: RefObject<OverlayTransitionState>;
}) {
  const strongTexture = ringTexture(0.09);
  const quietTexture = ringTexture(0.045);
  const { invalidate } = useThree();
  const materialRefs = useRef(new Map<string, THREE.SpriteMaterial>());
  const groupRefs = useRef(new Map<string, THREE.Group>());
  const strongAttention = useMemo(() => strongAttentionNodeIds(nodes), [nodes]);
  const transition = overlayTransition?.current;
  const fromOverlay = transition?.to === overlay ? transition.from : overlay;
  const keyed = useMemo(() => {
    const encoded = nodes
      .map((node) => {
        const fromEncoding = visualEncodingResolver.resolve(node, fromOverlay);
        const encoding = visualEncodingResolver.resolve(node, overlay);
        const fromVisible = fromEncoding.ring !== "none" && (fromOverlay !== "attention" || strongAttention.has(node.id));
        const visible = encoding.ring !== "none" && (overlay !== "attention" || strongAttention.has(node.id));
        return { node, fromEncoding, encoding, fromVisible, visible };
      })
      .filter(({ fromVisible, visible }) => fromVisible || visible);
    const instanceKeys = layoutNodeInstanceKeys(encoded.map(({ node }) => node));
    return encoded.map((entry, index) => ({ ...entry, instanceKey: instanceKeys[index] }));
  }, [fromOverlay, nodes, overlay, strongAttention]);

  const applyRingEncoding = useCallback(
    (progress: number) => {
      const current = overlayTransition?.current;
      const transitioning = Boolean(current?.active && current.to === overlay && current.from === fromOverlay);
      keyed.forEach(({ node, fromEncoding, encoding, fromVisible, visible, instanceKey }) => {
        const weights = transitioning ? overlayCrossfadeWeights(node.id, progress) : { from: 0, to: 1 };
        const fromOpacity = fromVisible ? Math.min(0.3 + fromEncoding.emissive * 0.65, 0.9) * weights.from : 0;
        const toOpacity = visible ? Math.min(0.3 + encoding.emissive * 0.65, 0.9) * weights.to : 0;
        const fromGroup = groupRefs.current.get(`${instanceKey}:from`);
        const toGroup = groupRefs.current.get(`${instanceKey}:to`);
        if (fromGroup) fromGroup.visible = fromOpacity > 0.001;
        if (toGroup) toGroup.visible = toOpacity > 0.001;
        const fromMain = materialRefs.current.get(`${instanceKey}:from:main`);
        const fromDouble = materialRefs.current.get(`${instanceKey}:from:double`);
        const toMain = materialRefs.current.get(`${instanceKey}:to:main`);
        const toDouble = materialRefs.current.get(`${instanceKey}:to:double`);
        if (fromMain) fromMain.opacity = fromOpacity;
        if (fromDouble) fromDouble.opacity = fromOpacity * 0.65;
        if (toMain) toMain.opacity = toOpacity;
        if (toDouble) toDouble.opacity = toOpacity * 0.65;
      });
    },
    [fromOverlay, keyed, overlay, overlayTransition]
  );

  useLayoutEffect(() => {
    const current = overlayTransition?.current;
    const transitioning = Boolean(current?.active && current.to === overlay && current.from === fromOverlay);
    applyRingEncoding(transitioning ? 0 : 1);
    invalidate();
  }, [applyRingEncoding, fromOverlay, invalidate, overlay, overlayTransition]);

  useFrame((state) => {
    const current = overlayTransition?.current;
    if (!current?.active || current.to !== overlay) return;
    if (current.start === null) current.start = state.clock.elapsedTime;
    const progress = current.duration <= 0
      ? 1
      : Math.min((state.clock.elapsedTime - current.start) / current.duration, 1);
    applyRingEncoding(progress);
    state.invalidate();
  });

  if (!strongTexture || !quietTexture) return null;
  return (
    <group>
      {keyed.map(({ node, fromEncoding, encoding, fromVisible, visible, instanceKey }) => {
        const fromSize = node.scale * (fromEncoding.ring === "double" ? 3.8 : 3.2);
        const size = node.scale * (encoding.ring === "double" ? 3.8 : 3.2);
        return (
          <MorphingNodeGroup key={`overlay-ring-${instanceKey}`} node={node} morph={morph}>
            <group
              ref={(group) => {
                if (group) groupRefs.current.set(`${instanceKey}:from`, group);
                else groupRefs.current.delete(`${instanceKey}:from`);
              }}
            >
              {fromVisible && (
                <sprite scale={[fromSize, fromSize, 1]}>
                  <spriteMaterial
                    ref={(material) => {
                      if (material) materialRefs.current.set(`${instanceKey}:from:main`, material);
                      else materialRefs.current.delete(`${instanceKey}:from:main`);
                    }}
                    map={fromEncoding.ring === "dashed" ? quietTexture : strongTexture}
                    color={fromEncoding.color}
                    transparent
                    opacity={0}
                    blending={THREE.AdditiveBlending}
                    depthWrite={false}
                    toneMapped={false}
                  />
                </sprite>
              )}
              {fromVisible && fromEncoding.ring === "double" && (
                <sprite scale={[fromSize * 1.25, fromSize * 1.25, 1]}>
                  <spriteMaterial
                    ref={(material) => {
                      if (material) materialRefs.current.set(`${instanceKey}:from:double`, material);
                      else materialRefs.current.delete(`${instanceKey}:from:double`);
                    }}
                    map={quietTexture}
                    color={fromEncoding.color}
                    transparent
                    opacity={0}
                    blending={THREE.AdditiveBlending}
                    depthWrite={false}
                    toneMapped={false}
                  />
                </sprite>
              )}
            </group>
            <group
              ref={(group) => {
                if (group) groupRefs.current.set(`${instanceKey}:to`, group);
                else groupRefs.current.delete(`${instanceKey}:to`);
              }}
            >
              {visible && (
                <sprite scale={[size, size, 1]}>
                  <spriteMaterial
                    ref={(material) => {
                      if (material) materialRefs.current.set(`${instanceKey}:to:main`, material);
                      else materialRefs.current.delete(`${instanceKey}:to:main`);
                    }}
                    map={encoding.ring === "dashed" ? quietTexture : strongTexture}
                    color={encoding.color}
                    transparent
                    opacity={0}
                    blending={THREE.AdditiveBlending}
                    depthWrite={false}
                    toneMapped={false}
                  />
                </sprite>
              )}
              {visible && encoding.ring === "double" && (
                <sprite scale={[size * 1.25, size * 1.25, 1]}>
                  <spriteMaterial
                    ref={(material) => {
                      if (material) materialRefs.current.set(`${instanceKey}:to:double`, material);
                      else materialRefs.current.delete(`${instanceKey}:to:double`);
                    }}
                    map={quietTexture}
                    color={encoding.color}
                    transparent
                    opacity={0}
                    blending={THREE.AdditiveBlending}
                    depthWrite={false}
                    toneMapped={false}
                  />
                </sprite>
              )}
            </group>
          </MorphingNodeGroup>
        );
      })}
    </group>
  );
}

function CenterSignalObject({ signal, scale }: { signal: CenterSignalBadge; scale: number }) {
  const material = <meshBasicMaterial color={signal.color} transparent opacity={0.86} toneMapped={false} />;
  const glowMaterial = <meshBasicMaterial color="#dff8ff" transparent opacity={0.2} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />;

  if (signal.primitive === "source_badge") {
    return (
      <group rotation={[0, Math.PI / 7, 0]}>
        {[0, 1, 2].map((index) => (
          <mesh key={`source-signal-${index}`} position={[0, index * scale * 0.13, (index - 1) * scale * 0.18]} scale={[scale * 0.9, scale * 0.1, scale * 0.54]}>
            <boxGeometry args={[1, 1, 1]} />
            {material}
          </mesh>
        ))}
        <mesh position={[0, scale * 0.5, 0]} scale={[scale * 0.44, scale * 0.05, scale * 0.66]}>
          <boxGeometry args={[1, 1, 1]} />
          {glowMaterial}
        </mesh>
      </group>
    );
  }

  if (signal.primitive === "action_lane") {
    return (
      <group>
        <mesh position={[0, scale * 0.32, 0]} scale={[scale * 0.08, scale * 0.72, scale * 0.08]}>
          <cylinderGeometry args={[1, 1, 1, 6]} />
          {material}
        </mesh>
        <mesh position={[scale * 0.26, scale * 0.74, 0]} rotation={[0, 0, -Math.PI / 2]} scale={[scale * 0.34, scale * 0.24, scale * 0.08]}>
          <coneGeometry args={[1, 1, 3]} />
          {material}
        </mesh>
      </group>
    );
  }

  if (signal.primitive === "risk_notch") {
    return (
      <group rotation={[0.22, Math.PI / 4, 0]}>
        <mesh scale={[scale * 0.48, scale * 0.7, scale * 0.48]}>
          <tetrahedronGeometry args={[1, 0]} />
          {material}
        </mesh>
        <mesh position={[0, scale * 0.16, 0]} scale={[scale * 0.7, scale * 0.06, scale * 0.7]}>
          <boxGeometry args={[1, 1, 1]} />
          {glowMaterial}
        </mesh>
      </group>
    );
  }

  if (signal.primitive === "review_halo") {
    return (
      <group rotation={[Math.PI / 2, 0, 0]}>
        <mesh>
          <torusGeometry args={[scale * 0.42, scale * 0.045, 6, 28]} />
          {material}
        </mesh>
        <mesh rotation={[0, 0, Math.PI / 4]}>
          <torusGeometry args={[scale * 0.2, scale * 0.026, 5, 18]} />
          {glowMaterial}
        </mesh>
      </group>
    );
  }

  if (signal.primitive === "attention_rail") {
    return (
      <group rotation={[0, signal.phase * Math.PI, 0]}>
        <mesh position={[-scale * 0.16, 0, 0]} scale={[scale * 0.08, scale * 0.72, scale * 0.08]}>
          <boxGeometry args={[1, 1, 1]} />
          {material}
        </mesh>
        <mesh position={[scale * 0.16, 0, 0]} scale={[scale * 0.08, scale * 0.72, scale * 0.08]}>
          <boxGeometry args={[1, 1, 1]} />
          {material}
        </mesh>
        <mesh position={[0, 0, 0]} scale={[scale * 0.46, scale * 0.055, scale * 0.055]}>
          <boxGeometry args={[1, 1, 1]} />
          {glowMaterial}
        </mesh>
      </group>
    );
  }

  return (
    <group rotation={[Math.PI / 2, 0, 0]}>
      <mesh>
        <torusGeometry args={[scale * 0.42, scale * 0.04, 5, 28]} />
        {material}
      </mesh>
      <mesh rotation={[0, 0, Math.PI / 4]} scale={[scale * 0.28, scale * 0.28, scale * 0.28]}>
        <octahedronGeometry args={[1, 0]} />
        {glowMaterial}
      </mesh>
    </group>
  );
}

export function CenterSignalSprites({
  node,
  record,
  quality,
  motion
}: {
  node: LayoutNode | undefined | null;
  record?: AnchorRecord | null;
  quality: SceneQuality | string;
  motion: boolean;
}) {
  const groupRef = useRef<THREE.Group>(null);
  const texture = glowTexture();
  const signals = useMemo(() => {
    if (!node) return [];
    const badges = centerSignalBadges(node, record);
    return quality === "compact" ? badges.slice(0, 3) : badges;
  }, [node, quality, record]);

  useFrame((state, delta) => {
    if (!motion || quality === "compact" || !groupRef.current || !node) return;
    groupRef.current.rotation.y += delta * 0.22;
    groupRef.current.position.y = node.position[1] + Math.sin(state.clock.elapsedTime * 1.4) * 0.018;
    state.invalidate();
  });

  if (!node || signals.length === 0) return null;
  const radius = Math.max(0.72, node.scale * 2.35);
  const baseLift = Math.max(0.34, node.scale * 1.16);
  const size = Math.max(0.18, node.scale * 0.52);

  return (
    <group ref={groupRef} position={node.position} renderOrder={6}>
      {signals.map((signal, index) => {
        const angle = signal.angle + (quality === "rich" ? (signal.phase - 0.5) * 0.16 : 0);
        const laneLift = baseLift + (index % 2) * size * 0.22;
        const position: [number, number, number] = [Math.cos(angle) * radius, laneLift, Math.sin(angle) * radius];
        const badgeScale = size * signal.strength;
        return (
          <group key={`center-signal-${node.id}-${signal.key}`} position={position} rotation={[0, -angle + Math.PI / 2, 0]}>
            {texture && (
              <sprite scale={[badgeScale * 2.4, badgeScale * 2.4, 1]}>
                <spriteMaterial map={texture} color={signal.color} transparent opacity={0.16 + signal.strength * 0.08} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
              </sprite>
            )}
            <CenterSignalObject signal={signal} scale={badgeScale} />
          </group>
        );
      })}
    </group>
  );
}

function GroupOrbitParticles({
  node,
  radius,
  color,
  enabled,
  quality
}: {
  node: LayoutNode;
  radius: number;
  color: string;
  enabled: boolean;
  quality: string;
}) {
  const members = node.groupMemberIds?.length ?? 0;
  const count = Math.max(0, Math.min(node.isRoot ? 36 : 18, Math.ceil(Math.log2(Math.max(members, 2))) * (node.isRoot ? 5 : 3)));
  const geometryRef = useRef<THREE.BufferGeometry>(null);
  const phaseRef = useRef(0);
  const texture = glowTexture();
  const buffers = useMemo(() => {
    const positions = new Float32Array(count * 3);
    const seeds = Array.from({ length: count }, (_, index) => {
      const seed = stableNumber(`${node.id}:${index}`);
      return {
        angle: seed * Math.PI * 2,
        lane: index % 3,
        speed: 0.16 + (seed % 0.37) + Math.min(members, 40) * 0.004,
        bob: 0.018 + (seed % 0.04)
      };
    });
    seeds.forEach((seed, index) => {
      const laneOffset = (seed.lane - 1) * 0.09;
      const orbit = radius * (0.66 + seed.lane * 0.11);
      positions[index * 3] = Math.cos(seed.angle) * orbit;
      positions[index * 3 + 1] = 0.12 + laneOffset + Math.sin(seed.angle * 1.7) * seed.bob;
      positions[index * 3 + 2] = Math.sin(seed.angle) * orbit;
    });
    return { positions, seeds };
  }, [count, members, node.id, radius]);

  useFrame((state, delta) => {
    if (!enabled || !geometryRef.current || count === 0) return;
    phaseRef.current += delta;
    const attentionBoost = node.freshness_state === "stale" || node.risk_flags.length > 0 ? 1.35 : node.approved_state === "proposal" ? 1.2 : 1;
    for (let index = 0; index < count; index += 1) {
      const seed = buffers.seeds[index];
      const angle = seed.angle + phaseRef.current * seed.speed * attentionBoost;
      const laneOffset = (seed.lane - 1) * 0.09;
      const orbit = radius * (0.66 + seed.lane * 0.11);
      buffers.positions[index * 3] = Math.cos(angle) * orbit;
      buffers.positions[index * 3 + 1] = 0.12 + laneOffset + Math.sin(angle * 1.7 + seed.angle) * seed.bob;
      buffers.positions[index * 3 + 2] = Math.sin(angle) * orbit;
    }
    geometryRef.current.attributes.position.needsUpdate = true;
    state.invalidate();
  });

  if (!enabled || quality === "compact" || count === 0 || !texture) return null;
  return (
    <points frustumCulled={false} renderOrder={3}>
      <bufferGeometry ref={geometryRef}>
        <bufferAttribute attach="attributes-position" args={[buffers.positions, 3]} />
      </bufferGeometry>
      <pointsMaterial
        map={texture}
        color={color}
        size={node.isRoot ? 0.18 : 0.13}
        sizeAttenuation
        transparent
        opacity={node.isRoot ? 0.44 : 0.3}
        alphaTest={0.04}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        toneMapped={false}
      />
    </points>
  );
}

function stableNumber(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) / 4294967296;
}

export type GroupVisualPip = {
  family: string;
  count: number;
  mass: number;
  angle: number;
  lane: number;
};

export type GroupStatusBeacon = {
  key: "risk" | "stale" | "proposal" | "evidence";
  color: string;
  strength: number;
  angle: number;
};

export type CenterSignalKind = "scope" | "evidence" | "risk" | "review" | "stale" | "action";

export type CenterSignalBadge = {
  key: CenterSignalKind;
  primitive: VisualPrimitiveId;
  slot: VisualSlotId;
  color: string;
  strength: number;
  angle: number;
  phase: number;
};

export type GroupShellProfile = {
  active: boolean;
  center: boolean;
  satellite: boolean;
  radiusScale: number;
  ringOpacity: number;
  ghostOpacity: number;
  detailScale: number;
  beaconOpacity: number;
  orbitParticles: boolean;
  pipLimit: number;
};

export type GroupLandmarkProfile = {
  family: string;
  color: string;
  height: number;
  radius: number;
  crown: "region" | "stack" | "spire" | "flag" | "node" | "archive";
  opacity: number;
  pulse: boolean;
  satellite: boolean;
};

export type GroupChildOrbitEntry = {
  id: string;
  family: string;
  lane: number;
  laneKind: GroupChildOrbitLane;
  laneColor: string;
  angle: number;
  radius: number;
  y: number;
  color: string;
  mass: number;
  attention: boolean;
  group: boolean;
};

export type GroupChildOrbitEntryHitProfile = {
  localRadius: number;
  lift: number;
  navigable: boolean;
};

export type GroupChildOrbitLane = "context" | "evidence" | "gap" | "attention";

export type GroupChildOrbitLaneSummary = {
  laneKind: GroupChildOrbitLane;
  lane: number;
  color: string;
  radius: number;
  count: number;
  moteCount: number;
  speed: number;
};

export type GroupCompositionArc = {
  laneKind: GroupChildOrbitLane;
  color: string;
  count: number;
  share: number;
  start: number;
  end: number;
  radius: number;
};

export type GroupContainmentFlow = {
  id: string;
  laneKind: GroupChildOrbitLane;
  color: string;
  angle: number;
  radius: number;
  y: number;
  strength: number;
  phase: number;
  speed: number;
  inbound: boolean;
};

export type GroupChildOrbitClusterPose = {
  id: string;
  clusterKey: string;
  clusterColor: string;
  clusterAngle: number;
  clusterRadius: number;
  memberCount: number;
  position: [number, number, number];
  rotationY: number;
};

export type GroupChildOrbitClusterSummary = {
  key: string;
  family: string;
  laneKind: GroupChildOrbitLane;
  color: string;
  angle: number;
  radius: number;
  y: number;
  count: number;
  representativeId: string;
};

export type GroupChildOrbitClusterVisualProfile = {
  family: string;
  color: string;
  laneColor: string;
  ringRadius: number;
  glyphMass: number;
  hitRadius: number;
  labelVisible: boolean;
};

export function groupChildOrbitClusterVisualProfile(
  cluster: Pick<GroupChildOrbitClusterSummary, "family" | "laneKind" | "color" | "count">,
  quality: SceneQuality | string
): GroupChildOrbitClusterVisualProfile {
  const familyColor = pageTypeStyle(`visual_group_${cluster.family}`).accent || cluster.color;
  const countGain = Math.min(0.34, Math.sqrt(Math.max(cluster.count, 1)) * 0.045);
  const ringRadius = Number(Math.max(0.14, countGain).toFixed(4));
  const laneBoost = cluster.laneKind === "attention" ? 0.16 : cluster.laneKind === "evidence" ? 0.08 : 0;
  const glyphMass = Number(Math.min(1.46, 0.74 + Math.sqrt(Math.max(cluster.count, 1)) * 0.1 + laneBoost).toFixed(4));
  return {
    family: cluster.family,
    color: familyColor,
    laneColor: cluster.color,
    ringRadius,
    glyphMass,
    hitRadius: Number(Math.max(ringRadius * 2.1, 0.34).toFixed(4)),
    labelVisible: quality !== "compact" || cluster.count >= 8
  };
}

export function groupVisualPips(
  composition: { family: string; count: number }[] | undefined,
  fallbackFamily: string,
  totalMembers: number,
  isCenterGroup: boolean
): GroupVisualPip[] {
  const hasComposition = Boolean(composition && composition.length > 0);
  const entries = (hasComposition ? composition ?? [] : [{ family: fallbackFamily || "content", count: Math.max(totalMembers, 1) }])
    .filter((entry) => entry.count > 0)
    .slice(0, 5);
  if (entries.length === 0) return [];
  const maxPips = hasComposition ? (isCenterGroup ? 12 : 7) : Math.min(isCenterGroup ? 6 : 3, Math.max(1, Math.ceil(Math.log2(totalMembers + 1))));
  const maxCount = Math.max(...entries.map((entry) => entry.count), 1);
  const weightSum = entries.reduce((sum, entry) => sum + Math.sqrt(entry.count), 0) || 1;
  const allocated = entries.map((entry) => ({
    family: entry.family,
    count: entry.count,
    slots: Math.max(1, Math.round((Math.sqrt(entry.count) / weightSum) * maxPips))
  }));
  while (allocated.reduce((sum, entry) => sum + entry.slots, 0) > maxPips) {
    const largest = allocated
      .filter((entry) => entry.slots > 1)
      .sort((a, b) => b.slots - a.slots || b.count - a.count || a.family.localeCompare(b.family))[0];
    if (!largest) break;
    largest.slots -= 1;
  }
  while (allocated.reduce((sum, entry) => sum + entry.slots, 0) < Math.min(maxPips, entries.length + 2)) {
    const strongest = allocated.sort((a, b) => b.count - a.count || a.family.localeCompare(b.family))[0];
    if (!strongest) break;
    strongest.slots += 1;
  }

  const pips: GroupVisualPip[] = [];
  allocated.forEach((entry) => {
    for (let index = 0; index < entry.slots; index += 1) {
      pips.push({
        family: entry.family,
        count: entry.count,
        mass: Math.sqrt(entry.count / maxCount),
        angle: 0,
        lane: index % 3
      });
    }
  });
  const arc = isCenterGroup ? Math.PI * 2 : Math.PI * 1.36;
  const start = isCenterGroup ? -Math.PI / 2 : -Math.PI * 0.68;
  return pips
    .slice(0, maxPips)
    .map((pip, index, list) => ({ ...pip, angle: start + (index / Math.max(list.length - (isCenterGroup ? 0 : 1), 1)) * arc }));
}

export function groupStatusBeacons(node: LayoutNode): GroupStatusBeacon[] {
  const beacons: GroupStatusBeacon[] = [];
  if (node.risk_flags.length > 0) beacons.push({ key: "risk", color: trustColor("risk"), strength: 1, angle: -Math.PI * 0.2 });
  if (node.freshness_state === "stale") beacons.push({ key: "stale", color: trustColor("stale"), strength: Math.max(node.overdueRatio, 0.8), angle: Math.PI * 0.18 });
  if (node.approved_state === "proposal") beacons.push({ key: "proposal", color: trustColor("proposal"), strength: 0.9, angle: Math.PI * 0.62 });
  if (node.source_ref_count > 0) {
    beacons.push({
      key: "evidence",
      color: edgeStyle("source_ref").color,
      strength: Math.min(1.25, 0.45 + Math.log10(node.source_ref_count + 1) * 0.28),
      angle: -Math.PI * 0.62
    });
  }
  return beacons;
}

export function centerSignalBadges(
  node: Pick<LayoutNode, "id" | "page_type" | "isRoot" | "isGroup" | "freshness_state" | "approved_state" | "risk_flags" | "source_ref_count" | "overdueRatio">,
  record?: AnchorRecord | null
): CenterSignalBadge[] {
  if (node.isGroup) return [];
  const family = semanticDetailFamily(node.page_type) ?? pageTypeStyle(node.page_type).family;
  const readerBadge = resolvePrimitiveForSlot(record, null, "reader.badge").id;
  const signals: CenterSignalBadge[] = [];
  const push = (key: CenterSignalKind, primitive: VisualPrimitiveId, slot: VisualSlotId, color: string, strength: number, angle: number) => {
    if (signals.some((signal) => signal.key === key)) return;
    signals.push({
      key,
      primitive,
      slot,
      color,
      strength: Number(strength.toFixed(4)),
      angle,
      phase: stableNumber(`${node.id}:${key}:${primitive}`)
    });
  };

  if (node.source_ref_count > 0 || family === "source") {
    push("evidence", readerBadge, "reader.badge", edgeStyle("source_ref").color, Math.min(1.45, 0.82 + Math.log10(node.source_ref_count + 1) * 0.22), -Math.PI * 0.58);
  }
  if (node.risk_flags.length > 0) {
    push("risk", "risk_notch", "region.marker", trustColor("risk"), 1.32, -Math.PI * 0.16);
  }
  if (node.approved_state === "proposal") {
    push("review", "review_halo", "region.marker", trustColor("proposal"), 1.18, Math.PI * 0.18);
  }
  if (node.freshness_state === "stale") {
    push("stale", "attention_rail", "region.rail", trustColor("stale"), Math.max(1.02, Math.min(1.38, node.overdueRatio || 1)), Math.PI * 0.52);
  }
  if (family === "action") {
    push("action", "action_lane", "dock.action", pageTypeStyle("visual_group_action").accent, 1.08, Math.PI * 0.82);
  }
  if (node.isRoot) {
    push("scope", "center_badge", "region.card", trustColor("root"), 0.76, -Math.PI * 0.88);
  }

  return signals.sort((a, b) => b.strength - a.strength || a.key.localeCompare(b.key)).slice(0, 4);
}

export function groupShellProfile(node: LayoutNode, layoutLevel: number, activeGroupId = ""): GroupShellProfile {
  const active = Boolean(activeGroupId) && (node.id === activeGroupId || node.path === activeGroupId || node.groupKey === activeGroupId || node.groupDrill?.group === activeGroupId);
  const center = Boolean(node.isRoot);
  const satellite = layoutLevel > 0 && !center && !active;
  const peripheralQuadrant = satellite && node.groupKind === "quadrant";
  const deepCenter = center && layoutLevel > 1;
  return {
    active,
    center,
    satellite,
    radiusScale: deepCenter ? 0.74 : peripheralQuadrant ? 0.56 : satellite ? 0.72 : 1,
    ringOpacity: active ? 0.98 : deepCenter ? 0.62 : center ? 0.78 : satellite ? 0.32 : 0.56,
    ghostOpacity: active ? 0.46 : deepCenter ? 0.16 : center ? 0.28 : satellite ? 0.08 : 0.18,
    detailScale: active ? 1.08 : deepCenter ? 0.88 : center ? 1 : satellite ? 0.72 : 0.9,
    beaconOpacity: active ? 0.72 : center ? 0.58 : satellite ? 0.34 : 0.48,
    // Root overviews can contain many family landmarks. Keep their semantic
    // shells and status beacons, but wake the per-group orbit cloud only on
    // hover/focus; otherwise every family runs its own continuous animation.
    orbitParticles: !satellite && !(center && layoutLevel > 1) && (center || active || layoutLevel > 0),
    pipLimit: center ? 99 : satellite ? (peripheralQuadrant ? 2 : 4) : 7
  };
}

function landmarkCrownForFamily(family: string, groupKind?: string): GroupLandmarkProfile["crown"] {
  if (groupKind === "quadrant" || family === "region") return "region";
  if (family === "source") return "stack";
  if (family === "event") return "spire";
  if (family === "action") return "flag";
  if (family === "person") return "node";
  return "archive";
}

function normalizedGroupFamily(family: string): string {
  if (["source", "hub", "decision", "action", "rule", "event", "person", "root", "region"].includes(family)) return family;
  return "content";
}

export function groupLandmarkProfile(
  node: LayoutNode,
  shell: GroupShellProfile,
  fallbackFamily: string,
  memberCount: number
): GroupLandmarkProfile {
  const family = node.groupComposition?.[0]?.family ?? fallbackFamily ?? "content";
  const normalizedFamily = node.groupKind === "quadrant" ? "region" : normalizedGroupFamily(family);
  const hasAttention = node.risk_flags.length > 0 || node.freshness_state === "stale" || node.approved_state === "proposal";
  const hasEvidence = node.source_ref_count > 0 || normalizedFamily === "source";
  const mass = Math.log2(Math.max(memberCount, 1) + 1);
  const base = shell.center ? 0.48 : shell.active ? 0.4 : shell.satellite ? 0.22 : 0.32;
  const gain = shell.center ? 0.062 : shell.satellite ? 0.026 : 0.04;
  const maxHeight = shell.center ? 1.1 : shell.satellite ? 0.46 : 0.66;
  const height = Number(Math.min(base + mass * gain, maxHeight).toFixed(4)) * shell.detailScale;
  const radius = Number((shell.center ? 0.055 : shell.satellite ? 0.028 : 0.04).toFixed(4));
  const opacityBase = shell.center ? 0.48 : shell.active ? 0.42 : shell.satellite ? 0.2 : 0.32;
  const opacity = Math.min(opacityBase + (hasAttention ? 0.18 : 0) + (hasEvidence ? 0.08 : 0), 0.82);
  const color =
    normalizedFamily === "region"
      ? pageTypeStyle("visual_group_region").accent
      : pageTypeStyle(`visual_group_${normalizedFamily}`).accent || pageTypeStyle("visual_group_content").accent;
  return {
    family: normalizedFamily,
    color,
    height,
    radius,
    crown: landmarkCrownForFamily(normalizedFamily, node.groupKind),
    opacity,
    pulse: hasAttention || shell.active || shell.center,
    satellite: shell.satellite
  };
}

const ORBIT_FAMILY_RANK = new Map(
  ["source", "hub", "decision", "action", "rule", "event", "person", "content", "root"].map((family, index) => [family, index])
);

function orbitFamilyRank(family: string): number {
  return ORBIT_FAMILY_RANK.get(family) ?? ORBIT_FAMILY_RANK.get("content") ?? 99;
}

function orbitBudget(quality: SceneQuality | string, layoutLevel: number): number {
  if (layoutLevel > 1) {
    if (quality === "compact") return 8;
    if (quality === "balanced") return 12;
    return 16;
  }
  if (quality === "compact") return 12;
  if (quality === "balanced") return 20;
  return 30;
}

export function groupChildOrbitDensityExpansion(memberCount: number, layoutLevel: number, quality: SceneQuality | string): number {
  if (layoutLevel < 1 || memberCount < 12) return 1;
  const qualityCap = quality === "compact" ? 1.08 : quality === "balanced" ? 1.14 : 1.18;
  const drillGain = layoutLevel > 1 ? 0.08 : 0.03;
  const densityGain = Math.log2(memberCount / 8) * 0.08;
  return Number(Math.min(qualityCap, 1 + drillGain + densityGain).toFixed(4));
}

function groupChildCandidate(center: LayoutNode, node: LayoutNode, memberIds: Set<string>, previewIds: Set<string>): boolean {
  if (node.id === center.id || node.path === center.path) return false;
  if (node.isGroup) {
    if (node.groupKind !== "region_family") return false;
    return (node.groupMemberIds ?? []).some((id) => memberIds.has(id));
  }
  return memberIds.has(node.id) || memberIds.has(node.path) || previewIds.has(node.id) || previewIds.has(node.path);
}

export function groupChildOrbitLane(node: LayoutNode, family = pageTypeStyle(node.page_type).family): GroupChildOrbitLane {
  if (node.risk_flags.length > 0 || node.freshness_state === "stale" || node.approved_state === "proposal") return "attention";
  if (family === "source" || node.source_ref_count > 0) return "evidence";
  if (family !== "hub" && family !== "root" && node.source_ref_count === 0) return "gap";
  return "context";
}

function groupChildOrbitLaneIndex(lane: GroupChildOrbitLane): number {
  if (lane === "context") return 0;
  if (lane === "evidence") return 1;
  if (lane === "gap") return 2;
  return 3;
}

function groupChildOrbitLaneColor(lane: GroupChildOrbitLane): string {
  if (lane === "attention") return trustColor("risk");
  if (lane === "evidence") return edgeStyle("source_ref").color;
  if (lane === "gap") return "#8b93c9";
  return "#dff8ff";
}

function groupChildOrbitLaneRadiusMultiplier(lane: GroupChildOrbitLane): number {
  if (lane === "attention") return 1.56;
  if (lane === "gap") return 1.39;
  if (lane === "evidence") return 1.22;
  return 1.08;
}

export function groupChildOrbitEntries(nodes: LayoutNode[], layoutLevel: number, quality: SceneQuality | string): GroupChildOrbitEntry[] {
  if (layoutLevel < 1) return [];
  const center = nodes.find((node) => node.isRoot && node.isGroup);
  if (!center || !center.groupMemberIds?.length) return [];
  const memberIds = new Set(center.groupMemberIds);
  const previewIds = new Set(center.groupPreviewIds ?? []);
  const centerPoint = new THREE.Vector3(...center.position);
  const budget = orbitBudget(quality, layoutLevel);
  const densityExpansion = groupChildOrbitDensityExpansion(center.groupMemberIds.length, layoutLevel, quality);
  return nodes
    .filter((node) => groupChildCandidate(center, node, memberIds, previewIds))
    .sort((a, b) => {
      const groupRank = Number(b.isGroup) - Number(a.isGroup);
      if (groupRank !== 0) return groupRank;
      const attentionRank =
        Number(b.risk_flags.length > 0 || b.freshness_state === "stale" || b.approved_state === "proposal") -
        Number(a.risk_flags.length > 0 || a.freshness_state === "stale" || a.approved_state === "proposal");
      if (attentionRank !== 0) return attentionRank;
      const aFamily = pageTypeStyle(a.page_type).family;
      const bFamily = pageTypeStyle(b.page_type).family;
      return orbitFamilyRank(aFamily) - orbitFamilyRank(bFamily) || a.title.localeCompare(b.title) || a.id.localeCompare(b.id);
    })
    .slice(0, budget)
    .map((node, index) => {
      const offset = new THREE.Vector3(...node.position).sub(centerPoint);
      const fallbackAngle = stableNumber(`${center.id}:${node.id}:orbit`) * Math.PI * 2;
      const angle = offset.lengthSq() > 0.0001 ? Math.atan2(offset.z, offset.x) : fallbackAngle;
      const family = pageTypeStyle(node.page_type).family;
      const laneKind = groupChildOrbitLane(node, family);
      const lane = groupChildOrbitLaneIndex(laneKind);
      const centerRadius = Math.max(center.scale * 3.25, center.groupKind === "quadrant" ? 1.18 : 0.96);
      const radius = centerRadius * groupChildOrbitLaneRadiusMultiplier(laneKind) * densityExpansion;
      const attention = node.risk_flags.length > 0 || node.freshness_state === "stale" || node.approved_state === "proposal";
      const familyColor = pageTypeStyle(`visual_group_${family}`).accent;
      const laneColor = groupChildOrbitLaneColor(laneKind);
      return {
        id: node.id,
        family,
        lane,
        laneKind,
        laneColor,
        angle: Number((angle + index * 0.018).toFixed(4)),
        radius: Number(radius.toFixed(4)),
        y: Number(((node.isGroup ? 0.17 : 0.09 + lane * 0.055) + (attention ? 0.1 : 0)).toFixed(4)),
        color: familyColor || contextStyle(node.context).accent,
        mass: Number((node.isGroup ? Math.min(1.35, 0.78 + Math.log2((node.groupMemberIds?.length ?? 1) + 1) * 0.12) : Math.min(1.18, 0.72 + node.scale * 1.7)).toFixed(4)),
        attention,
        group: Boolean(node.isGroup)
      };
    });
}

export function groupChildOrbitLaneSummaries(entries: GroupChildOrbitEntry[], quality: SceneQuality | string): GroupChildOrbitLaneSummary[] {
  const maxMotes = quality === "compact" ? 8 : quality === "balanced" ? 18 : 30;
  const byLane = new Map<GroupChildOrbitLane, GroupChildOrbitLaneSummary>();
  entries.forEach((entry) => {
    const current = byLane.get(entry.laneKind);
    if (current) {
      current.count += 1;
      current.radius = Math.max(current.radius, entry.radius);
      return;
    }
    byLane.set(entry.laneKind, {
      laneKind: entry.laneKind,
      lane: entry.lane,
      color: entry.laneColor,
      radius: entry.radius,
      count: 1,
      moteCount: 1,
      speed: entry.laneKind === "attention" ? 0.34 : entry.laneKind === "evidence" ? 0.22 : entry.laneKind === "gap" ? 0.12 : 0.16
    });
  });
  const summaries = [...byLane.values()].sort((a, b) => a.lane - b.lane);
  const totalWeight = summaries.reduce((sum, lane) => sum + Math.sqrt(lane.count), 0) || 1;
  summaries.forEach((lane) => {
    lane.moteCount = Math.max(1, Math.round((Math.sqrt(lane.count) / totalWeight) * maxMotes));
  });
  while (summaries.reduce((sum, lane) => sum + lane.moteCount, 0) > maxMotes) {
    const largest = [...summaries].sort((a, b) => b.moteCount - a.moteCount || b.count - a.count)[0];
    if (!largest || largest.moteCount <= 1) break;
    largest.moteCount -= 1;
  }
  return summaries;
}

export function groupCompositionArcs(entries: GroupChildOrbitEntry[], quality: SceneQuality | string): GroupCompositionArc[] {
  if (entries.length === 0) return [];
  const summaries = groupChildOrbitLaneSummaries(entries, quality);
  const total = summaries.reduce((sum, summary) => sum + summary.count, 0) || 1;
  const gap = quality === "compact" ? 0.08 : 0.11;
  const radius = Math.max(...entries.map((entry) => entry.radius), 1) * (quality === "compact" ? 0.62 : 0.68);
  let cursor = -Math.PI / 2;
  return summaries
    .filter((summary) => summary.count > 0)
    .map((summary) => {
      const share = summary.count / total;
      const length = Math.max(share * Math.PI * 2 - gap, 0.18);
      const arc: GroupCompositionArc = {
        laneKind: summary.laneKind,
        color: summary.color,
        count: summary.count,
        share: Number(share.toFixed(4)),
        start: Number(cursor.toFixed(4)),
        end: Number((cursor + length).toFixed(4)),
        radius: Number(radius.toFixed(4))
      };
      cursor += length + gap;
      return arc;
    });
}

export function groupChildOrbitEntryScale(entry: GroupChildOrbitEntry, visibleCount: number): number {
  const base = entry.group ? entry.mass : entry.mass * 0.82;
  if (visibleCount < 18) return Number(base.toFixed(4));
  const denseFactor = entry.group ? 0.76 : 0.62;
  const attentionFloor = entry.attention ? 0.74 : denseFactor;
  return Number((base * Math.max(denseFactor, attentionFloor)).toFixed(4));
}

export function groupChildOrbitEntryHitProfile(entry: GroupChildOrbitEntry, visibleCount: number): GroupChildOrbitEntryHitProfile {
  const visualScale = Math.max(groupChildOrbitEntryScale(entry, visibleCount), 0.18);
  const globalMinimum = entry.group ? 0.292 : entry.attention ? 0.252 : 0.212;
  const localMinimum = globalMinimum / visualScale;
  const familyMass = entry.family === "source" || entry.family === "event" ? 0.05 : 0;
  return {
    localRadius: Number(Math.min(0.74, Math.max(localMinimum, 0.26 + entry.mass * 0.08 + familyMass)).toFixed(4)),
    lift: Number((entry.attention ? 0.12 : entry.group ? 0.08 : 0.055).toFixed(4)),
    navigable: true
  };
}

export function groupChildOrbitIsDense(entries: GroupChildOrbitEntry[], quality: SceneQuality | string): boolean {
  return entries.length >= (quality === "compact" ? 8 : 12);
}

export function groupChildOrbitClusterSpread(memberCount: number, quality: SceneQuality | string): number {
  const base = quality === "compact" ? 0.12 : quality === "balanced" ? 0.18 : 0.22;
  const max = quality === "compact" ? 0.42 : quality === "balanced" ? 0.62 : 0.78;
  return Number(Math.min(max, base + Math.sqrt(Math.max(memberCount, 1)) * 0.072).toFixed(4));
}

export function groupChildOrbitPoseMinimumDistance(poses: Pick<GroupChildOrbitClusterPose, "position">[]): number {
  if (poses.length < 2) return Infinity;
  let min = Infinity;
  for (let a = 0; a < poses.length; a += 1) {
    for (let b = a + 1; b < poses.length; b += 1) {
      const [ax, ay, az] = poses[a].position;
      const [bx, by, bz] = poses[b].position;
      min = Math.min(min, Math.hypot(ax - bx, (ay - by) * 0.45, az - bz));
    }
  }
  return Number(min.toFixed(4));
}

function circularAverageAngle(entries: GroupChildOrbitEntry[]): number {
  const sum = entries.reduce(
    (acc, entry) => {
      acc.x += Math.cos(entry.angle);
      acc.z += Math.sin(entry.angle);
      return acc;
    },
    { x: 0, z: 0 }
  );
  if (Math.abs(sum.x) + Math.abs(sum.z) < 0.0001) return entries[0]?.angle ?? 0;
  return Math.atan2(sum.z, sum.x);
}

export function groupChildOrbitClusterPoses(entries: GroupChildOrbitEntry[], quality: SceneQuality | string): GroupChildOrbitClusterPose[] {
  if (!groupChildOrbitIsDense(entries, quality)) {
    return entries.map((entry) => {
      const x = Math.cos(entry.angle) * entry.radius;
      const z = Math.sin(entry.angle) * entry.radius;
      return {
        id: entry.id,
        clusterKey: `${entry.laneKind}:${entry.family}`,
        clusterColor: entry.laneColor,
        clusterAngle: Number(entry.angle.toFixed(4)),
        clusterRadius: entry.radius,
        memberCount: 1,
        position: [Number(x.toFixed(4)), entry.y, Number(z.toFixed(4))],
        rotationY: Number((-entry.angle).toFixed(4))
      };
    });
  }

  const byCluster = new Map<string, GroupChildOrbitEntry[]>();
  entries.forEach((entry) => {
    const key = `${entry.laneKind}:${entry.family}`;
    const cluster = byCluster.get(key) ?? [];
    cluster.push(entry);
    byCluster.set(key, cluster);
  });
  const clusters = [...byCluster.entries()]
    .map(([key, cluster]) => ({
      key,
      cluster,
      laneKind: cluster[0]?.laneKind ?? "context",
      family: cluster[0]?.family ?? "content",
      angle: circularAverageAngle(cluster),
      radius: Math.max(...cluster.map((entry) => entry.radius), 1),
      color: cluster[0]?.laneColor ?? "#dff8ff"
    }))
    .sort((a, b) => groupChildOrbitLaneIndex(a.laneKind) - groupChildOrbitLaneIndex(b.laneKind) || orbitFamilyRank(a.family) - orbitFamilyRank(b.family));

  const clusterAngleByKey = new Map(clusters.map((cluster, index) => {
    const separation = clusters.length > 1 ? ((index / clusters.length) - 0.5) * 0.42 : 0;
    return [cluster.key, cluster.angle + separation];
  }));

  return clusters.flatMap((cluster) => {
    const angle = clusterAngleByKey.get(cluster.key) ?? cluster.angle;
    const radial = { x: Math.cos(angle), z: Math.sin(angle) };
    const tangent = { x: -Math.sin(angle), z: Math.cos(angle) };
    const memberCount = cluster.cluster.length;
    const spread = groupChildOrbitClusterSpread(memberCount, quality);
    return cluster.cluster
      .sort((a, b) => Number(b.attention) - Number(a.attention) || Number(b.group) - Number(a.group) || b.mass - a.mass || a.id.localeCompare(b.id))
      .map((entry, index) => {
        const localAngle = index * 2.399963229728653 + stableNumber(`${cluster.key}:cluster-pose`) * 0.42;
        const ring = 0.48 + Math.floor(index / 5) * 0.22 + (index % 2) * 0.07;
        const localTangent = Math.cos(localAngle) * spread * ring;
        const localRadial = Math.sin(localAngle) * spread * 0.62 * ring;
        const radius = cluster.radius * (entry.group ? 0.95 : 1);
        const x = radial.x * (radius + localRadial) + tangent.x * localTangent;
        const z = radial.z * (radius + localRadial) + tangent.z * localTangent;
        const y = entry.y + (index % 4) * 0.018;
        const rotationY = -Math.atan2(z, x);
        return {
          id: entry.id,
          clusterKey: cluster.key,
          clusterColor: cluster.color,
          clusterAngle: Number(angle.toFixed(4)),
          clusterRadius: Number(radius.toFixed(4)),
          memberCount,
          position: [Number(x.toFixed(4)), Number(y.toFixed(4)), Number(z.toFixed(4))] as [number, number, number],
          rotationY: Number(rotationY.toFixed(4))
        };
      });
  });
}

function groupChildOrbitClusterSummaries(poses: GroupChildOrbitClusterPose[]): GroupChildOrbitClusterSummary[] {
  const byCluster = new Map<string, GroupChildOrbitClusterSummary & { x: number; z: number }>();
  poses.forEach((pose) => {
    const current = byCluster.get(pose.clusterKey);
    const [x, y, z] = pose.position;
    if (current) {
      current.count += 1;
      current.x += x;
      current.z += z;
      current.y = Math.max(current.y, y);
      current.radius = Math.max(current.radius, pose.clusterRadius);
      return;
    }
    byCluster.set(pose.clusterKey, {
      key: pose.clusterKey,
      family: pose.clusterKey.split(":")[1] ?? "content",
      laneKind: (pose.clusterKey.split(":")[0] as GroupChildOrbitLane | undefined) ?? "context",
      color: pose.clusterColor,
      angle: pose.clusterAngle,
      radius: pose.clusterRadius,
      y,
      count: 1,
      representativeId: pose.id,
      x,
      z
    });
  });
  return [...byCluster.values()].map((cluster) => {
    const x = cluster.x / Math.max(cluster.count, 1);
    const z = cluster.z / Math.max(cluster.count, 1);
    return {
      key: cluster.key,
      family: cluster.family,
      laneKind: cluster.laneKind,
      color: cluster.color,
      angle: Number(Math.atan2(z, x).toFixed(4)),
      radius: Number(Math.sqrt(x * x + z * z).toFixed(4)),
      y: Number(cluster.y.toFixed(4)),
      count: cluster.count,
      representativeId: cluster.representativeId
    };
  });
}

function clusterPageType(family: string): string {
  if (family === "source") return "source";
  if (family === "event") return "meeting";
  if (family === "action") return "action";
  if (family === "person") return "person";
  if (family === "rule") return "operational_rule";
  return "artifact";
}

function visualFamilyLabel(family: string): string {
  const style = pageTypeStyle(`visual_group_${family}`);
  return style.label || family;
}

export function groupChildOrbitClusterHoverNode(center: LayoutNode, cluster: GroupChildOrbitClusterSummary): LayoutNode {
  const title = `${visualFamilyLabel(cluster.family)} · ${cluster.count}`;
  return {
    ...center,
    id: `cluster:${center.id}:${cluster.key}`,
    path: `cluster:${center.path}:${cluster.key}`,
    title,
    page_type: clusterPageType(cluster.family),
    freshness_state: cluster.laneKind === "attention" ? "stale" : center.freshness_state,
    approved_state: cluster.laneKind === "attention" ? "proposal" : center.approved_state,
    risk_flags: cluster.laneKind === "attention" ? ["cluster_attention"] : [],
    source_ref_count: cluster.laneKind === "evidence" ? cluster.count : 0,
    inbound_links: cluster.count,
    outbound_links: center.outbound_links,
    position: [Math.cos(cluster.angle) * cluster.radius, cluster.y, Math.sin(cluster.angle) * cluster.radius],
    scale: Math.max(0.18, Math.min(0.46, 0.16 + Math.sqrt(cluster.count) * 0.045)),
    groupCaption: title,
    groupPreviewIds: [cluster.representativeId],
    inspection: {
      kind: "orbit_cluster",
      family: cluster.family,
      laneKind: cluster.laneKind,
      count: cluster.count,
      representativeId: cluster.representativeId,
      centerId: center.id
    },
    isRoot: false,
    isHub: false,
    isGroup: false,
    groupMemberIds: undefined,
    groupComposition: undefined
  };
}

export function groupContainmentFlows(entries: GroupChildOrbitEntry[], quality: SceneQuality | string): GroupContainmentFlow[] {
  const limit = quality === "compact" ? 4 : quality === "balanced" ? 8 : 12;
  return [...entries]
    .sort((a, b) => {
      const attentionRank = Number(b.attention) - Number(a.attention);
      if (attentionRank !== 0) return attentionRank;
      const groupRank = Number(b.group) - Number(a.group);
      if (groupRank !== 0) return groupRank;
      const laneRank = groupChildOrbitLaneIndex(b.laneKind) - groupChildOrbitLaneIndex(a.laneKind);
      if (laneRank !== 0) return laneRank;
      return b.mass - a.mass || a.id.localeCompare(b.id);
    })
    .slice(0, limit)
    .map((entry, index) => ({
      id: entry.id,
      laneKind: entry.laneKind,
      color: entry.laneColor,
      angle: entry.angle,
      radius: entry.radius,
      y: entry.y,
      strength: Number(Math.min(1.45, 0.68 + entry.mass * 0.28 + (entry.attention ? 0.24 : 0) + (entry.group ? 0.14 : 0)).toFixed(4)),
      phase: stableNumber(`${entry.id}:${entry.laneKind}:containment-flow`),
      speed: Number(((entry.laneKind === "attention" ? 0.42 : entry.laneKind === "evidence" ? 0.32 : 0.22) + index * 0.006).toFixed(4)),
      inbound: entry.laneKind !== "gap"
    }));
}

function groupVisualKey(node: LayoutNode, fallbackFamily: string): string {
  if (node.groupKind === "quadrant") return "region";
  return node.groupLabelKey || fallbackFamily || "content";
}

const SEMANTIC_DETAIL_FAMILIES = new Set(["source", "event", "action", "person", "hub", "rule", "decision", "content"]);

export function semanticDetailFamily(pageType: string): string | null {
  const family = pageTypeStyle(pageType).family;
  return SEMANTIC_DETAIL_FAMILIES.has(family) ? family : null;
}

export type SemanticObjectPrimitive = {
  family: string;
  primaryScale: number;
  lift: number;
  streamCount: number;
  isPrimary: boolean;
};

export type SemanticZoomMarkKind = "evidence" | "risk" | "review" | "stale" | "inbound" | "outbound";

export type SemanticZoomMark = {
  key: SemanticZoomMarkKind;
  color: string;
  angle: number;
  lift: number;
  size: number;
  strength: number;
};

export type SemanticRootBodyGeometry = "sphere" | "source_slab" | "person_totem" | "event_ring" | "action_beacon" | "rule_plinth" | "hub_gate" | "decision_crystal" | "content_sheet";

export type SemanticRootBodyPrimitive = {
  family: string;
  geometry: SemanticRootBodyGeometry;
  color: string;
  rotation: [number, number, number];
  emissiveIntensity: number;
  opacity: number;
  roughness: number;
  metalness: number;
};

const SEMANTIC_ROOT_BODY: Record<string, Omit<SemanticRootBodyPrimitive, "family" | "color">> = {
  source: { geometry: "source_slab", rotation: [0, Math.PI / 10, 0], emissiveIntensity: 0.34, opacity: 0.82, roughness: 0.46, metalness: 0.08 },
  person: { geometry: "person_totem", rotation: [0, 0, 0], emissiveIntensity: 0.28, opacity: 0.86, roughness: 0.54, metalness: 0.06 },
  event: { geometry: "event_ring", rotation: [Math.PI / 2, 0, 0], emissiveIntensity: 0.42, opacity: 0.84, roughness: 0.42, metalness: 0.08 },
  action: { geometry: "action_beacon", rotation: [0, Math.PI / 4, 0], emissiveIntensity: 0.48, opacity: 0.86, roughness: 0.5, metalness: 0.05 },
  rule: { geometry: "rule_plinth", rotation: [0, 0, 0], emissiveIntensity: 0.32, opacity: 0.84, roughness: 0.62, metalness: 0.04 },
  hub: { geometry: "hub_gate", rotation: [Math.PI / 2, 0, 0], emissiveIntensity: 0.36, opacity: 0.8, roughness: 0.46, metalness: 0.08 },
  decision: { geometry: "decision_crystal", rotation: [0, Math.PI / 4, 0], emissiveIntensity: 0.4, opacity: 0.9, roughness: 0.4, metalness: 0.1 },
  content: { geometry: "content_sheet", rotation: [0, -Math.PI / 12, 0], emissiveIntensity: 0.2, opacity: 0.76, roughness: 0.66, metalness: 0.02 },
  root: { geometry: "sphere", rotation: [0, 0, 0], emissiveIntensity: TRUST_MATERIALS.root.emissiveIntensity, opacity: 1, roughness: 0.3, metalness: 0 }
};

export function semanticRootBodyPrimitive(pageType: string): SemanticRootBodyPrimitive {
  const family = semanticDetailFamily(pageType) ?? pageTypeStyle(pageType).family;
  const normalized = SEMANTIC_ROOT_BODY[family] ? family : "root";
  const body = SEMANTIC_ROOT_BODY[normalized] ?? SEMANTIC_ROOT_BODY.root;
  const color = normalized === "root" ? trustColor("root") : pageTypeStyle(`visual_group_${normalized}`).accent || pageTypeStyle(pageType).accent || trustColor("root");
  return { family: normalized, color, ...body };
}

export function semanticObjectPrimitive(node: Pick<LayoutNode, "page_type" | "isRoot" | "scale" | "source_ref_count" | "inbound_links">): SemanticObjectPrimitive | null {
  const family = semanticDetailFamily(node.page_type);
  if (!family) return null;
  const isPrimary = Boolean(node.isRoot);
  const linkMass = Math.min(0.28, Math.sqrt(Math.max(node.source_ref_count, node.inbound_links, 0)) * 0.018);
  const sourceBoost = family === "source" ? 1.2 : 1;
  return {
    family,
    primaryScale: Number((node.scale * (isPrimary ? 2.55 : 1.28) * sourceBoost + linkMass).toFixed(4)),
    lift: Number((node.scale * (isPrimary ? 0.68 : 0.46)).toFixed(4)),
    streamCount: Math.min(7, Math.max(3, Math.ceil(Math.sqrt(Math.max(node.source_ref_count, node.inbound_links, 1))))),
    isPrimary
  };
}

export function semanticDetailLimit(quality: SceneQuality | string): number {
  if (quality === "compact") return 28;
  if (quality === "balanced") return 56;
  return 96;
}

const SEMANTIC_DETAIL_FAMILY_WEIGHT: Record<string, number> = {
  source: 42,
  action: 34,
  event: 30,
  decision: 28,
  rule: 25,
  person: 22,
  hub: 20,
  content: 12
};

export function semanticDetailSignalScore(node: Pick<LayoutNode, "page_type" | "risk_flags" | "freshness_state" | "approved_state" | "source_ref_count" | "inbound_links" | "outbound_links" | "isRoot" | "faint">): number {
  const family = semanticDetailFamily(node.page_type) ?? "content";
  const attention = (node.risk_flags.length > 0 ? 500 : 0) + (node.freshness_state === "stale" ? 180 : 0) + (node.approved_state === "proposal" ? 160 : 0);
  const evidence = Math.log2(node.source_ref_count + 1) * 34;
  const links = Math.log2(node.inbound_links + node.outbound_links + 1) * 14;
  const root = node.isRoot ? 1000 : 0;
  const faintPenalty = node.faint ? -80 : 0;
  return root + attention + evidence + links + (SEMANTIC_DETAIL_FAMILY_WEIGHT[family] ?? SEMANTIC_DETAIL_FAMILY_WEIGHT.content) + faintPenalty;
}

export function semanticDetailEligible(node: Pick<LayoutNode, "page_type" | "isGroup" | "risk_flags" | "freshness_state" | "approved_state" | "source_ref_count" | "inbound_links" | "outbound_links">): boolean {
  if (node.isGroup) return false;
  const family = semanticDetailFamily(node.page_type);
  if (!family) return false;
  if (family !== "content") return true;
  return node.risk_flags.length > 0 || node.freshness_state === "stale" || node.approved_state === "proposal" || node.source_ref_count > 0 || node.inbound_links + node.outbound_links > 2;
}

export function semanticDetailNodes(nodes: LayoutNode[], quality: SceneQuality | string): LayoutNode[] {
  const limit = semanticDetailLimit(quality);
  return nodes
    .filter(semanticDetailEligible)
    .map((node, index) => {
      return {
        node,
        index,
        score: semanticDetailSignalScore(node)
      };
    })
    .sort((a, b) => b.score - a.score || a.index - b.index || a.node.id.localeCompare(b.node.id))
    .slice(0, limit)
    .map((entry) => entry.node);
}

function semanticZoomMarkLimit(quality: SceneQuality | string): number {
  if (quality === "compact") return 3;
  if (quality === "balanced") return 5;
  return 6;
}

export function semanticZoomMarks(
  node: Pick<LayoutNode, "id" | "page_type" | "isRoot" | "source_ref_count" | "inbound_links" | "outbound_links" | "risk_flags" | "approved_state" | "freshness_state" | "overdueRatio">,
  quality: SceneQuality | string
): SemanticZoomMark[] {
  const family = semanticDetailFamily(node.page_type);
  if (!family) return [];
  const baseStrength = node.isRoot ? 1.08 : 0.86;
  const marks: SemanticZoomMark[] = [];
  const push = (key: SemanticZoomMarkKind, color: string, rawStrength: number, angle: number, lift: number) => {
    if (marks.some((mark) => mark.key === key)) return;
    const strength = Number(Math.max(0.46, Math.min(1.6, rawStrength * baseStrength)).toFixed(4));
    marks.push({
      key,
      color,
      angle,
      lift,
      strength,
      size: Number((0.055 + strength * 0.052).toFixed(4))
    });
  };

  if (node.source_ref_count > 0 || family === "source") {
    push("evidence", edgeStyle("source_ref").color, 0.78 + Math.log10(node.source_ref_count + 1) * 0.24, -Math.PI * 0.58, 0.04);
  }
  if (node.risk_flags.length > 0) {
    push("risk", trustColor("risk"), 1.34 + Math.min(0.22, node.risk_flags.length * 0.04), -Math.PI * 0.18, 0.12);
  }
  if (node.approved_state === "proposal") {
    push("review", trustColor("proposal"), 1.14, Math.PI * 0.12, 0.1);
  }
  if (node.freshness_state === "stale") {
    push("stale", trustColor("stale"), Math.max(0.92, Math.min(1.34, node.overdueRatio || 1)), Math.PI * 0.48, 0.05);
  }
  if (node.inbound_links > 2) {
    push("inbound", "#9fdcff", 0.62 + Math.log10(node.inbound_links + 1) * 0.16, Math.PI * 0.78, -0.02);
  }
  if (node.outbound_links > 2) {
    push("outbound", "#dff8ff", 0.58 + Math.log10(node.outbound_links + 1) * 0.14, -Math.PI * 0.86, -0.04);
  }

  const priority: Record<SemanticZoomMarkKind, number> = {
    risk: 0,
    stale: 1,
    review: 2,
    evidence: family === "source" ? 0.5 : 3,
    inbound: 4,
    outbound: 5
  };
  return marks
    .sort((a, b) => priority[a.key] - priority[b.key] || b.strength - a.strength || a.key.localeCompare(b.key))
    .slice(0, semanticZoomMarkLimit(quality));
}

function GroupCoreGlyph({ node, radius, color, isCenterGroup }: { node: LayoutNode; radius: number; color: string; isCenterGroup: boolean }) {
  const family = pageTypeStyle(node.page_type).family;
  const key = groupVisualKey(node, family);
  const size = radius * (isCenterGroup ? 0.34 : 0.28);
  const lift = isCenterGroup ? 0.2 : 0.12;
  const opacity = isCenterGroup ? 0.9 : 0.72;
  const ghostOpacity = isCenterGroup ? 0.28 : 0.18;
  const baseMaterial = <meshBasicMaterial color={color} transparent opacity={opacity} toneMapped={false} />;
  const ghostMaterial = <meshBasicMaterial color="#dff8ff" transparent opacity={ghostOpacity} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />;

  if (key === "source") {
    return (
      <group position={[0, lift, 0]} rotation={[0, Math.PI / 5, 0]} renderOrder={4}>
        {[0, 1, 2].map((index) => (
          <mesh key={`source-slab-${node.id}-${index}`} position={[0, index * size * 0.13, (index - 1) * size * 0.16]} scale={[size * 1.05, size * 0.1, size * 0.56]}>
            <boxGeometry args={[1, 1, 1]} />
            {baseMaterial}
          </mesh>
        ))}
        <mesh position={[0, size * 0.5, 0]} scale={[size * 0.52, size * 0.05, size * 0.68]}>
          <boxGeometry args={[1, 1, 1]} />
          {ghostMaterial}
        </mesh>
      </group>
    );
  }

  if (key === "event") {
    return (
      <group position={[0, lift, 0]} rotation={[Math.PI / 2, 0, 0]} renderOrder={4}>
        <mesh>
          <torusGeometry args={[size * 0.52, size * 0.045, 6, 32]} />
          {baseMaterial}
        </mesh>
        <mesh position={[0, size * 0.2, 0]} rotation={[0, 0, -Math.PI / 6]} scale={[size * 0.08, size * 0.52, size * 0.08]}>
          <boxGeometry args={[1, 1, 1]} />
          {ghostMaterial}
        </mesh>
        <mesh position={[size * 0.18, 0, 0]} rotation={[0, 0, Math.PI / 2.8]} scale={[size * 0.07, size * 0.34, size * 0.07]}>
          <boxGeometry args={[1, 1, 1]} />
          {ghostMaterial}
        </mesh>
      </group>
    );
  }

  if (key === "person") {
    return (
      <group position={[0, lift, 0]} renderOrder={4}>
        {[-0.46, 0, 0.46].map((offset, index) => (
          <group key={`person-${node.id}-${index}`} position={[offset * size, index === 1 ? size * 0.08 : 0, 0]}>
            <mesh position={[0, size * 0.34, 0]}>
              <sphereGeometry args={[size * (index === 1 ? 0.18 : 0.14), 12, 10]} />
              {baseMaterial}
            </mesh>
            <mesh position={[0, size * 0.08, 0]}>
              <cylinderGeometry args={[size * (index === 1 ? 0.12 : 0.09), size * (index === 1 ? 0.16 : 0.12), size * 0.42, 10]} />
              {index === 1 ? baseMaterial : ghostMaterial}
            </mesh>
          </group>
        ))}
      </group>
    );
  }

  if (key === "hub") {
    return (
      <group position={[0, lift, 0]} renderOrder={4}>
        <mesh position={[-size * 0.45, 0, 0]} scale={[size * 0.12, size * 0.78, size * 0.14]}>
          <boxGeometry args={[1, 1, 1]} />
          {baseMaterial}
        </mesh>
        <mesh position={[size * 0.45, 0, 0]} scale={[size * 0.12, size * 0.78, size * 0.14]}>
          <boxGeometry args={[1, 1, 1]} />
          {baseMaterial}
        </mesh>
        <mesh position={[0, size * 0.36, 0]} scale={[size * 1.02, size * 0.12, size * 0.14]}>
          <boxGeometry args={[1, 1, 1]} />
          {baseMaterial}
        </mesh>
        <mesh position={[0, -size * 0.05, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[size * 0.36, size * 0.035, 5, 24]} />
          {ghostMaterial}
        </mesh>
      </group>
    );
  }

  if (key === "action") {
    return (
      <group position={[0, lift, 0]} rotation={[0, -Math.PI / 9, 0]} renderOrder={4}>
        <mesh position={[-size * 0.26, 0, 0]} scale={[size * 0.08, size * 0.86, size * 0.08]}>
          <boxGeometry args={[1, 1, 1]} />
          {baseMaterial}
        </mesh>
        <mesh position={[size * 0.18, size * 0.2, 0]} scale={[size * 0.72, size * 0.36, size * 0.06]}>
          <boxGeometry args={[1, 1, 1]} />
          {baseMaterial}
        </mesh>
        <mesh position={[size * 0.44, -size * 0.02, 0]} rotation={[0, 0, Math.PI / 4]} scale={[size * 0.18, size * 0.18, size * 0.05]}>
          <boxGeometry args={[1, 1, 1]} />
          {ghostMaterial}
        </mesh>
      </group>
    );
  }

  if (key === "decision") {
    return (
      <group position={[0, lift, 0]} rotation={[0, Math.PI / 4, 0]} renderOrder={4}>
        <mesh>
          <octahedronGeometry args={[size * 0.5, 0]} />
          {baseMaterial}
        </mesh>
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[size * 0.72, size * 0.025, 4, 28]} />
          {ghostMaterial}
        </mesh>
      </group>
    );
  }

  if (key === "rule") {
    return (
      <group position={[0, lift, 0]} renderOrder={4}>
        {[-0.38, 0, 0.38].map((offset) => (
          <mesh key={`rule-column-${node.id}-${offset}`} position={[offset * size, 0, 0]} scale={[size * 0.12, size * 0.68, size * 0.12]}>
            <boxGeometry args={[1, 1, 1]} />
            {baseMaterial}
          </mesh>
        ))}
        <mesh position={[0, size * 0.4, 0]} scale={[size * 1.0, size * 0.09, size * 0.16]}>
          <boxGeometry args={[1, 1, 1]} />
          {ghostMaterial}
        </mesh>
        <mesh position={[0, -size * 0.38, 0]} scale={[size * 1.08, size * 0.08, size * 0.16]}>
          <boxGeometry args={[1, 1, 1]} />
          {ghostMaterial}
        </mesh>
      </group>
    );
  }

  if (key === "region") {
    return (
      <group position={[0, lift, 0]} renderOrder={4}>
        <mesh rotation={[Math.PI / 2, 0, Math.PI / 4]}>
          <torusGeometry args={[size * 0.56, size * 0.035, 5, 32]} />
          {baseMaterial}
        </mesh>
        <mesh scale={[size * 1.18, size * 0.08, size * 0.08]}>
          <boxGeometry args={[1, 1, 1]} />
          {ghostMaterial}
        </mesh>
        <mesh rotation={[0, Math.PI / 2, 0]} scale={[size * 1.18, size * 0.08, size * 0.08]}>
          <boxGeometry args={[1, 1, 1]} />
          {ghostMaterial}
        </mesh>
      </group>
    );
  }

  return (
    <group position={[0, lift, 0]} rotation={[0, -Math.PI / 8, 0]} renderOrder={4}>
      {[0, 1, 2].map((index) => (
        <mesh key={`content-sheet-${node.id}-${index}`} position={[(index - 1) * size * 0.16, index * size * 0.07, (1 - index) * size * 0.1]} scale={[size * 0.46, size * 0.58, size * 0.04]}>
          <boxGeometry args={[1, 1, 1]} />
          {index === 1 ? baseMaterial : ghostMaterial}
        </mesh>
      ))}
    </group>
  );
}

function MiniFamilyGlyph({
  family,
  color,
  mass,
  center
}: {
  family: string;
  color: string;
  mass: number;
  center: boolean;
}) {
  const size = (center ? 0.16 : 0.12) * (0.76 + mass * 0.38);
  const opacity = center ? 0.9 : 0.76;
  const ghostOpacity = center ? 0.38 : 0.24;
  const body = <meshBasicMaterial color={color} transparent opacity={opacity} toneMapped={false} />;
  const ghost = <meshBasicMaterial color="#dff8ff" transparent opacity={ghostOpacity} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />;

  if (family === "source") {
    return (
      <group rotation={[0, Math.PI / 8, 0]}>
        {[0, 1, 2].map((index) => (
          <mesh key={`mini-source-${index}`} position={[0, index * size * 0.08, (index - 1) * size * 0.22]} scale={[size * 1.18, size * 0.1, size * 0.62]}>
            <boxGeometry args={[1, 1, 1]} />
            {index === 1 ? body : ghost}
          </mesh>
        ))}
      </group>
    );
  }

  if (family === "event") {
    return (
      <group rotation={[Math.PI / 2, 0, 0]}>
        <mesh>
          <torusGeometry args={[size * 0.62, size * 0.07, 5, 24]} />
          {body}
        </mesh>
        <mesh rotation={[0, 0, -Math.PI / 4]} scale={[size * 0.08, size * 0.72, size * 0.08]}>
          <boxGeometry args={[1, 1, 1]} />
          {ghost}
        </mesh>
      </group>
    );
  }

  if (family === "person") {
    return (
      <group>
        {[-0.32, 0.32].map((offset, index) => (
          <group key={`mini-person-${index}`} position={[offset * size, 0, 0]}>
            <mesh position={[0, size * 0.28, 0]}>
              <sphereGeometry args={[size * 0.18, 10, 8]} />
              {index === 0 ? body : ghost}
            </mesh>
            <mesh position={[0, 0, 0]}>
              <cylinderGeometry args={[size * 0.12, size * 0.16, size * 0.36, 8]} />
              {index === 0 ? body : ghost}
            </mesh>
          </group>
        ))}
      </group>
    );
  }

  if (family === "action") {
    return (
      <group rotation={[0, -Math.PI / 9, 0]}>
        <mesh position={[-size * 0.2, 0, 0]} scale={[size * 0.09, size * 0.72, size * 0.09]}>
          <boxGeometry args={[1, 1, 1]} />
          {body}
        </mesh>
        <mesh position={[size * 0.2, size * 0.12, 0]} rotation={[0, 0, Math.PI / 4]} scale={[size * 0.64, size * 0.12, size * 0.09]}>
          <boxGeometry args={[1, 1, 1]} />
          {ghost}
        </mesh>
      </group>
    );
  }

  if (family === "decision") {
    return (
      <group rotation={[0, Math.PI / 4, 0]}>
        <mesh>
          <octahedronGeometry args={[size * 0.56, 0]} />
          {body}
        </mesh>
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[size * 0.74, size * 0.04, 4, 22]} />
          {ghost}
        </mesh>
      </group>
    );
  }

  if (family === "rule") {
    return (
      <group>
        {[-0.38, 0, 0.38].map((offset) => (
          <mesh key={`mini-rule-${offset}`} position={[offset * size, 0, 0]} scale={[size * 0.12, size * 0.68, size * 0.12]}>
            <boxGeometry args={[1, 1, 1]} />
            {offset === 0 ? body : ghost}
          </mesh>
        ))}
        <mesh position={[0, size * 0.38, 0]} scale={[size * 1.0, size * 0.08, size * 0.12]}>
          <boxGeometry args={[1, 1, 1]} />
          {body}
        </mesh>
      </group>
    );
  }

  if (family === "hub") {
    return (
      <group>
        <mesh position={[-size * 0.42, 0, 0]} scale={[size * 0.12, size * 0.72, size * 0.12]}>
          <boxGeometry args={[1, 1, 1]} />
          {body}
        </mesh>
        <mesh position={[size * 0.42, 0, 0]} scale={[size * 0.12, size * 0.72, size * 0.12]}>
          <boxGeometry args={[1, 1, 1]} />
          {body}
        </mesh>
        <mesh position={[0, size * 0.32, 0]} scale={[size * 0.96, size * 0.1, size * 0.12]}>
          <boxGeometry args={[1, 1, 1]} />
          {ghost}
        </mesh>
      </group>
    );
  }

  return (
    <group rotation={[0, -Math.PI / 8, 0]}>
      {[0, 1, 2].map((index) => (
        <mesh key={`mini-content-${index}`} position={[(index - 1) * size * 0.18, index * size * 0.08, (1 - index) * size * 0.1]} scale={[size * 0.46, size * 0.58, size * 0.045]}>
          <boxGeometry args={[1, 1, 1]} />
          {index === 1 ? body : ghost}
        </mesh>
      ))}
    </group>
  );
}

function GroupLandmark({
  profile,
  bodyRadius,
  verticalLift,
  motion
}: {
  profile: GroupLandmarkProfile;
  bodyRadius: number;
  verticalLift: number;
  motion: boolean;
}) {
  const ref = useRef<THREE.Group>(null);
  const crownY = profile.height + 0.06;
  const offset = profile.satellite ? bodyRadius * 0.1 : bodyRadius * 0.18;
  useFrame((state) => {
    if (!motion || !profile.pulse || !ref.current) return;
    const phase = state.clock.elapsedTime * (profile.satellite ? 0.7 : 0.95);
    ref.current.position.y = verticalLift + 0.07 + Math.sin(phase) * (profile.satellite ? 0.01 : 0.024);
    ref.current.rotation.y = Math.sin(phase * 0.55) * 0.08;
    state.invalidate();
  });

  const mastMaterial = (
    <meshBasicMaterial
      color={profile.color}
      transparent
      opacity={profile.opacity}
      blending={THREE.AdditiveBlending}
      depthWrite={false}
      toneMapped={false}
    />
  );
  const ghostMaterial = (
    <meshBasicMaterial
      color="#dff8ff"
      transparent
      opacity={Math.min(profile.opacity * 0.62, 0.42)}
      blending={THREE.AdditiveBlending}
      depthWrite={false}
      toneMapped={false}
    />
  );

  return (
    <group ref={ref} position={[offset, verticalLift + 0.07, -offset * 0.72]} renderOrder={5}>
      <mesh position={[0, profile.height * 0.5, 0]} scale={[profile.radius, profile.height, profile.radius]}>
        <cylinderGeometry args={[1, 0.76, 1, 8]} />
        {mastMaterial}
      </mesh>
      <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, 0.03, 0]}>
        <torusGeometry args={[bodyRadius * (profile.satellite ? 0.1 : 0.13), Math.max(profile.radius * 0.26, 0.006), 5, 24]} />
        {ghostMaterial}
      </mesh>
      {profile.crown === "region" && (
        <group position={[0, crownY, 0]} rotation={[0, Math.PI / 4, 0]}>
          <mesh scale={[bodyRadius * 0.105, profile.radius * 1.15, profile.radius * 1.15]}>
            <boxGeometry args={[1, 1, 1]} />
            {mastMaterial}
          </mesh>
          <mesh rotation={[0, Math.PI / 2, 0]} scale={[bodyRadius * 0.105, profile.radius * 1.15, profile.radius * 1.15]}>
            <boxGeometry args={[1, 1, 1]} />
            {ghostMaterial}
          </mesh>
        </group>
      )}
      {profile.crown === "stack" && (
        <group position={[0, crownY, 0]} rotation={[0, Math.PI / 8, 0]}>
          {[0, 1, 2].map((index) => (
            <mesh key={`landmark-stack-${index}`} position={[0, index * profile.radius * 1.55, (index - 1) * profile.radius * 1.7]} scale={[profile.radius * 4.7, profile.radius * 0.62, profile.radius * 2.2]}>
              <boxGeometry args={[1, 1, 1]} />
              {index === 1 ? mastMaterial : ghostMaterial}
            </mesh>
          ))}
        </group>
      )}
      {profile.crown === "spire" && (
        <mesh position={[0, crownY + profile.radius * 1.9, 0]} rotation={[0, Math.PI / 4, 0]}>
          <coneGeometry args={[profile.radius * 3.2, profile.radius * 5.4, 4]} />
          {mastMaterial}
        </mesh>
      )}
      {profile.crown === "flag" && (
        <group position={[0, crownY + profile.radius * 1.4, 0]}>
          <mesh position={[profile.radius * 2.4, 0, 0]} scale={[profile.radius * 4.2, profile.radius * 2.2, profile.radius * 0.45]}>
            <boxGeometry args={[1, 1, 1]} />
            {mastMaterial}
          </mesh>
          <mesh position={[profile.radius * 4.8, -profile.radius * 1.2, 0]} rotation={[0, 0, Math.PI / 4]} scale={[profile.radius * 1.8, profile.radius * 1.8, profile.radius * 0.4]}>
            <boxGeometry args={[1, 1, 1]} />
            {ghostMaterial}
          </mesh>
        </group>
      )}
      {profile.crown === "node" && (
        <group position={[0, crownY + profile.radius * 1.4, 0]}>
          <mesh>
            <sphereGeometry args={[profile.radius * 2.15, 12, 10]} />
            {mastMaterial}
          </mesh>
          <mesh position={[-profile.radius * 2.8, -profile.radius * 0.92, 0]}>
            <sphereGeometry args={[profile.radius * 1.36, 10, 8]} />
            {ghostMaterial}
          </mesh>
          <mesh position={[profile.radius * 2.8, -profile.radius * 0.92, 0]}>
            <sphereGeometry args={[profile.radius * 1.36, 10, 8]} />
            {ghostMaterial}
          </mesh>
        </group>
      )}
      {profile.crown === "archive" && (
        <group position={[0, crownY + profile.radius * 1.2, 0]} rotation={[0, -Math.PI / 8, 0]}>
          {[0, 1, 2].map((index) => (
            <mesh key={`landmark-archive-${index}`} position={[(index - 1) * profile.radius * 1.65, index * profile.radius * 0.9, 0]} scale={[profile.radius * 2.1, profile.radius * 2.8, profile.radius * 0.42]}>
              <boxGeometry args={[1, 1, 1]} />
              {index === 1 ? mastMaterial : ghostMaterial}
            </mesh>
          ))}
        </group>
      )}
    </group>
  );
}

function GroupShell({
  node,
  overlay,
  motion,
  quality,
  layoutLevel,
  activeGroupId = "",
  morph,
  overlayTransition,
  onSelect,
  onHover
}: {
  node: LayoutNode;
  overlay: OverlayId;
  motion: boolean;
  quality: string;
  layoutLevel: number;
  activeGroupId?: string;
  morph?: RefObject<MorphState>;
  overlayTransition?: RefObject<OverlayTransitionState>;
  onSelect?: (node: LayoutNode) => void;
  onHover?: (node: LayoutNode | null, event?: ThreeEvent<PointerEvent>) => void;
}) {
  const ref = useRef<THREE.Group>(null);
  const overlayMaterialRefs = useRef<Array<THREE.MeshBasicMaterial | null>>([]);
  const { invalidate } = useThree();
  const transition = overlayTransition?.current;
  const fromOverlay = transition?.to === overlay ? transition.from : overlay;
  const fromEncoding = visualEncodingResolver.resolve(node, fromOverlay);
  const encoding = visualEncodingResolver.resolve(node, overlay);
  const color = encoding.color;
  const overlayFromColor = useMemo(() => new THREE.Color(), []);
  const overlayToColor = useMemo(() => new THREE.Color(), []);
  const overlayMixedColor = useMemo(() => new THREE.Color(), []);
  const applyOverlayColor = useCallback(
    (progress: number) => {
      const current = overlayTransition?.current;
      const transitioning = Boolean(current?.active && current.from === fromOverlay && current.to === overlay);
      const weights = transitioning ? overlayCrossfadeWeights(node.id, progress) : { from: 0, to: 1 };
      overlayMixedColor.lerpColors(
        overlayFromColor.set(fromEncoding.color),
        overlayToColor.set(encoding.color),
        weights.to
      );
      overlayMaterialRefs.current.forEach((material) => material?.color.copy(overlayMixedColor));
    },
    [encoding.color, fromEncoding.color, fromOverlay, node.id, overlay, overlayFromColor, overlayMixedColor, overlayToColor, overlayTransition]
  );
  const applyPosition = useCallback(
    (t: number) => {
      if (!ref.current) return;
      const from = morph?.current?.from.get(node.id);
      const sample = entityMotionSample(node.id, t, morph?.current?.intent ?? "view");
      const eased = sample.eased;
      const x = from ? from[0] + (node.position[0] - from[0]) * eased : node.position[0];
      const y = from ? from[1] + (node.position[1] - from[1]) * eased : node.position[1];
      const z = from ? from[2] + (node.position[2] - from[2]) * eased : node.position[2];
      ref.current.position.set(x, y, z);
      morph?.current?.current?.set(node.id, [x, y, z]);
      ref.current.scale.setScalar(groupDrillGrowthScale(node, layoutLevel, Boolean(from), sample.local));
    },
    [layoutLevel, morph, node, node.id, node.position]
  );

  useLayoutEffect(() => {
    applyPosition(morph?.current?.active ? 0 : 1);
    invalidate();
  }, [applyPosition, invalidate, morph]);

  useLayoutEffect(() => {
    const current = overlayTransition?.current;
    const transitioning = Boolean(current?.active && current.from === fromOverlay && current.to === overlay);
    applyOverlayColor(transitioning ? 0 : 1);
    invalidate();
  }, [applyOverlayColor, fromOverlay, invalidate, overlay, overlayTransition]);

  useFrame((state) => {
    const morphState = morph?.current;
    if (!morphState?.active) return;
    if (morphState.start === null) morphState.start = state.clock.elapsedTime;
    const t = Math.min((state.clock.elapsedTime - morphState.start) / morphState.duration, 1);
    applyPosition(t);
    state.invalidate();
  });

  useFrame((state) => {
    const current = overlayTransition?.current;
    if (!current?.active || current.to !== overlay) return;
    if (current.start === null) current.start = state.clock.elapsedTime;
    const progress = current.duration <= 0
      ? 1
      : Math.min((state.clock.elapsedTime - current.start) / current.duration, 1);
    applyOverlayColor(progress);
    state.invalidate();
  });

        const members = node.groupMemberIds?.length ?? 0;
        const profile = groupShellProfile(node, layoutLevel, activeGroupId);
        const isCenterGroup = profile.center;
        const active = profile.active;
        const isRegionGroup = node.groupKind === "quadrant";
        const family = pageTypeStyle(node.page_type).family;
        const visualKey = groupVisualKey(node, family);
        const composition = node.groupComposition ?? [];
        const pips = groupVisualPips(composition, visualKey === "region" ? "hub" : visualKey, members, isCenterGroup);
        const statusBeacons = groupStatusBeacons(node);
        const baseRadius = isCenterGroup ? Math.max(node.scale * 3.25, isRegionGroup ? 1.18 : 0.96) : Math.max(node.scale * (isRegionGroup ? 3.05 : 2.55), isRegionGroup ? 0.76 : 0.58);
        const radius = Math.max(baseRadius * profile.radiusScale, isRegionGroup ? 0.44 : 0.38);
        const tube = Math.max(radius * (active ? 0.05 : isCenterGroup ? 0.038 : 0.028), 0.014);
        const verticalLift = isCenterGroup ? 0.05 : 0;
        const landmark = groupLandmarkProfile(node, profile, visualKey === "region" ? "region" : visualKey, members);
        return (
          <group ref={ref}>
            <mesh
              frustumCulled={false}
              onClick={(event) => {
                event.stopPropagation();
                onSelect?.(node);
              }}
              onPointerMove={(event) => {
                event.stopPropagation();
                onHover?.(node, event);
              }}
              onPointerOut={() => onHover?.(null)}
            >
              <sphereGeometry args={[Math.max(radius * (profile.satellite ? 1.35 : 1.05), 0.44), 10, 10]} />
              <meshBasicMaterial transparent opacity={0} depthWrite={false} colorWrite={false} />
            </mesh>
            <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, verticalLift, 0]} renderOrder={1}>
              <torusGeometry args={[radius, tube, 8, 72]} />
              <meshBasicMaterial ref={(material) => { overlayMaterialRefs.current[0] = material; }} color={color} transparent opacity={profile.ringOpacity} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
            </mesh>
            <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, verticalLift + 0.02, 0]} scale={[1.18, 1.18, 1]}>
              <torusGeometry args={[radius, Math.max(tube * 0.55, 0.009), 6, 72]} />
              <meshBasicMaterial color="#dff8ff" transparent opacity={profile.ghostOpacity} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
            </mesh>
            {active && (
              <>
                <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, verticalLift + 0.24, 0]} scale={[1.36, 1.36, 1]} renderOrder={5}>
                  <torusGeometry args={[radius, Math.max(tube * 0.38, 0.01), 5, 96]} />
                  <meshBasicMaterial color="#dff8ff" transparent opacity={0.32} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
                </mesh>
                <mesh position={[0, verticalLift + 0.16, 0]} scale={[radius * 0.08, 0.7, radius * 0.08]} renderOrder={4}>
                  <cylinderGeometry args={[1, 1, 1, 10]} />
                  <meshBasicMaterial ref={(material) => { overlayMaterialRefs.current[1] = material; }} color={color} transparent opacity={0.22} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
                </mesh>
              </>
            )}
            {isCenterGroup && (
              <mesh rotation={[Math.PI / 2.7, 0, Math.PI / 8]} position={[0, verticalLift + 0.14, 0]} renderOrder={2}>
                <torusGeometry args={[radius * 0.72, Math.max(tube * 0.7, 0.012), 6, 72]} />
                <meshBasicMaterial ref={(material) => { overlayMaterialRefs.current[2] = material; }} color={color} transparent opacity={0.4} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
              </mesh>
            )}
            <GroupCoreGlyph node={node} radius={radius} color={color} isCenterGroup={isCenterGroup} />
            <GroupLandmark profile={landmark} bodyRadius={radius} verticalLift={verticalLift} motion={motion} />
            <GroupOrbitParticles node={node} radius={radius} color={color} enabled={motion && profile.orbitParticles} quality={quality} />
            {pips.slice(0, profile.pipLimit).map((pip, index) => {
              const pipRadius = (isCenterGroup ? radius * (0.65 + pip.lane * 0.07) : radius * (0.8 + pip.lane * 0.06)) * profile.detailScale;
              const pipColor = pageTypeStyle(`visual_group_${pip.family}`).accent || color;
              return (
                <group
                  key={`group-shell-pip-${node.id}-${index}`}
                  position={[Math.cos(pip.angle) * pipRadius, verticalLift + 0.08 + pip.lane * 0.055, Math.sin(pip.angle) * pipRadius]}
                  rotation={[0, -pip.angle, 0]}
                  renderOrder={4}
                >
                  <MiniFamilyGlyph family={pip.family} color={pipColor} mass={pip.mass * profile.detailScale} center={isCenterGroup} />
                </group>
              );
            })}
            {statusBeacons.map((beacon) => {
              const markerRadius = radius * (isCenterGroup ? 1.1 : 1.14) * profile.detailScale;
              const beaconHeight = (0.2 + beacon.strength * 0.18) * (isCenterGroup ? 1.1 : 0.9) * profile.detailScale;
              return (
                <group
                  key={`group-status-${node.id}-${beacon.key}`}
                  position={[Math.cos(beacon.angle) * markerRadius, verticalLift + 0.22, Math.sin(beacon.angle) * markerRadius]}
                  rotation={[0, -beacon.angle, 0]}
                  renderOrder={4}
                >
                  <mesh position={[0, beaconHeight * 0.5, 0]} scale={[0.028, beaconHeight, 0.028]}>
                    <cylinderGeometry args={[1, 1, 1, 8]} />
                    <meshBasicMaterial color={beacon.color} transparent opacity={profile.beaconOpacity} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
                  </mesh>
                  <mesh position={[0, beaconHeight + 0.02, 0]}>
                    <sphereGeometry args={[(0.04 + beacon.strength * 0.025) * profile.detailScale, 10, 8]} />
                    <meshBasicMaterial color={beacon.color} transparent opacity={Math.min(profile.beaconOpacity + 0.18, 0.86)} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
                  </mesh>
                </group>
              );
            })}
          </group>
        );
}

export function GroupShells({
  nodes,
  overlay,
  motion,
  quality,
  layoutLevel,
  activeGroupId = "",
  morph,
  overlayTransition,
  onSelect,
  onHover
}: {
  nodes: LayoutNode[];
  overlay: OverlayId;
  motion: boolean;
  quality: string;
  layoutLevel: number;
  activeGroupId?: string;
  morph?: RefObject<MorphState>;
  overlayTransition?: RefObject<OverlayTransitionState>;
  onSelect?: (node: LayoutNode) => void;
  onHover?: (node: LayoutNode | null, event?: ThreeEvent<PointerEvent>) => void;
}) {
  const groups = useMemo(() => nodes.filter((node) => node.isGroup), [nodes]);
  const instanceKeys = useMemo(() => layoutNodeInstanceKeys(groups), [groups]);
  if (groups.length === 0) return null;
  return (
    <group>
      {groups.map((node, index) => (
        <GroupShell
          key={`group-shell-${instanceKeys[index]}`}
          node={node}
          overlay={overlay}
          motion={motion}
          quality={quality}
          layoutLevel={layoutLevel}
          activeGroupId={activeGroupId}
          morph={morph}
          overlayTransition={overlayTransition}
          onSelect={onSelect}
          onHover={onHover}
        />
      ))}
    </group>
  );
}

function GroupChildOrbitField({
  center,
  entries,
  motion,
  quality,
  nodeById,
  onSelect,
  onHover
}: {
  center: LayoutNode;
  entries: GroupChildOrbitEntry[];
  motion: boolean;
  quality: SceneQuality | string;
  nodeById: Map<string, LayoutNode>;
  onSelect?: (node: LayoutNode) => void;
  onHover?: (node: LayoutNode | null, event?: ThreeEvent<PointerEvent>) => void;
}) {
  const ref = useRef<THREE.Group>(null);
  const { invalidate } = useThree();
  const denseOrbit = groupChildOrbitIsDense(entries, quality);
  const laneSummaries = useMemo(() => groupChildOrbitLaneSummaries(entries, quality), [entries, quality]);
  const compositionArcs = useMemo(() => groupCompositionArcs(entries, quality), [entries, quality]);
  const containmentFlows = useMemo(() => groupContainmentFlows(entries, quality), [entries, quality]);
  const clusterPoses = useMemo(() => groupChildOrbitClusterPoses(entries, quality), [entries, quality]);
  const poseById = useMemo(() => new Map(clusterPoses.map((pose) => [pose.id, pose])), [clusterPoses]);
  const clusterSummaries = useMemo(() => groupChildOrbitClusterSummaries(clusterPoses), [clusterPoses]);
  const laneSpecs = useMemo(() => {
    const byLane = new Map<GroupChildOrbitLane, { laneKind: GroupChildOrbitLane; lane: number; radius: number; color: string }>();
    entries.forEach((entry) => {
      const current = byLane.get(entry.laneKind);
      const next = { laneKind: entry.laneKind, lane: entry.lane, radius: entry.radius, color: entry.laneColor };
      if (!current || entry.radius > current.radius) byLane.set(entry.laneKind, next);
    });
    return [...byLane.values()].sort((a, b) => a.lane - b.lane).slice(0, quality === "compact" ? 2 : 4);
  }, [entries, quality]);
  const lineObjects = useMemo(
    () =>
      laneSpecs.map((lane, index) => {
        const points: THREE.Vector3[] = [];
        const segments = quality === "compact" ? 48 : 84;
        for (let step = 0; step <= segments; step += 1) {
          const angle = (step / segments) * Math.PI * 2;
          points.push(new THREE.Vector3(Math.cos(angle) * lane.radius, 0.06 + index * 0.028, Math.sin(angle) * lane.radius));
        }
        const geometry = new THREE.BufferGeometry().setFromPoints(points);
        const material = new THREE.LineBasicMaterial({
          color: lane.color,
          transparent: true,
          opacity: (lane.laneKind === "attention" ? 0.24 : lane.laneKind === "gap" ? 0.17 : 0.12) * (denseOrbit ? 0.68 : 1),
          blending: THREE.AdditiveBlending,
          depthWrite: false,
          toneMapped: false
        });
        return { line: new THREE.Line(geometry, material), geometry, material };
      }),
    [denseOrbit, laneSpecs, quality]
  );
  useFrame((state) => {
    if (!motion || !ref.current || quality === "compact") return;
    const t = state.clock.elapsedTime;
    ref.current.rotation.y = Math.sin(t * 0.28) * 0.035;
    ref.current.position.y = Math.sin(t * 0.62) * 0.012;
    state.invalidate();
  });
  useEffect(() => {
    invalidate();
    return () => {
      lineObjects.forEach((object) => {
        object.geometry.dispose();
        object.material.dispose();
      });
    };
  }, [invalidate, lineObjects]);
  if (entries.length === 0) return null;
  return (
    <group ref={ref} position={center.position} renderOrder={2}>
      <GroupCompositionCrown arcs={compositionArcs} motion={motion} quality={quality} />
      {lineObjects.map((object, index) => (
        <primitive key={`group-child-orbit-lane-${center.id}-${index}`} object={object.line} />
      ))}
      {denseOrbit && (
        <GroupChildOrbitClusters
          center={center}
          clusters={clusterSummaries}
          nodeById={nodeById}
          quality={quality}
          motion={motion}
          onSelect={onSelect}
          onHover={onHover}
        />
      )}
      {motion && quality !== "compact" && !denseOrbit && <GroupChildOrbitMotes summaries={laneSummaries} />}
      {containmentFlows.map((flow) => (
        <GroupContainmentCurrent key={`group-containment-current-${center.id}-${flow.id}`} flow={flow} quality={quality} motion={motion} />
      ))}
      {entries.map((entry) => {
        const pose = poseById.get(entry.id);
        const point: [number, number, number] =
          pose?.position ?? [
            Math.cos(entry.angle) * entry.radius,
            entry.y,
            Math.sin(entry.angle) * entry.radius
          ];
        const hit = groupChildOrbitEntryHitProfile(entry, entries.length);
        const target = nodeById.get(entry.id);
        return (
          <group
            key={`group-child-orbit-entry-${center.id}-${entry.id}`}
            position={point}
            rotation={[0, pose?.rotationY ?? -entry.angle, 0]}
            scale={groupChildOrbitEntryScale(entry, entries.length)}
            renderOrder={5}
          >
            <mesh
              position={[0, hit.lift, 0]}
              scale={[hit.localRadius, hit.localRadius * 0.78, hit.localRadius]}
              onClick={(event) => {
                event.stopPropagation();
                if (target) onSelect?.(target);
              }}
              onPointerMove={(event) => {
                event.stopPropagation();
                if (target) onHover?.(target, event);
              }}
              onPointerOut={() => onHover?.(null)}
            >
              <sphereGeometry args={[1, 10, 8]} />
              <meshBasicMaterial transparent opacity={0} depthWrite={false} colorWrite={false} />
            </mesh>
            <MiniFamilyGlyph family={entry.family} color={entry.color} mass={entry.mass} center={entry.group} />
            {entry.attention && (
              <mesh position={[0, 0.18, 0]} scale={[0.035, 0.18, 0.035]} renderOrder={6}>
                <cylinderGeometry args={[1, 1, 1, 8]} />
                <meshBasicMaterial color={entry.laneColor} transparent opacity={0.68} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
              </mesh>
            )}
          </group>
        );
      })}
    </group>
  );
}

function GroupChildOrbitClusters({
  center,
  clusters,
  nodeById,
  quality,
  motion,
  onSelect,
  onHover
}: {
  center: LayoutNode;
  clusters: GroupChildOrbitClusterSummary[];
  nodeById: Map<string, LayoutNode>;
  quality: SceneQuality | string;
  motion: boolean;
  onSelect?: (node: LayoutNode) => void;
  onHover?: (node: LayoutNode | null, event?: ThreeEvent<PointerEvent>) => void;
}) {
  const ref = useRef<THREE.Group>(null);
  const hoverNodes = useMemo(() => new Map(clusters.map((cluster) => [cluster.key, groupChildOrbitClusterHoverNode(center, cluster)])), [center, clusters]);
  useFrame((state) => {
    if (!motion || !ref.current || quality === "compact") return;
    ref.current.rotation.y = Math.sin(state.clock.elapsedTime * 0.2) * 0.018;
    state.invalidate();
  });
  if (clusters.length === 0 || (clusters.length === 1 && (clusters[0]?.count ?? 0) < 4)) return null;
  return (
    <group ref={ref} renderOrder={2}>
      {clusters.map((cluster) => {
        const visual = groupChildOrbitClusterVisualProfile(cluster, quality);
        const hoverNode = hoverNodes.get(cluster.key);
        const representative = nodeById.get(cluster.representativeId);
        return (
          <group
            key={`group-child-orbit-cluster-${cluster.key}`}
            position={[Math.cos(cluster.angle) * cluster.radius, Math.max(cluster.y - 0.015, 0.06), Math.sin(cluster.angle) * cluster.radius]}
          >
            <mesh
              position={[0, 0.04, 0]}
              scale={[visual.hitRadius, visual.hitRadius * 0.72, visual.hitRadius]}
              onClick={(event) => {
                event.stopPropagation();
                if (representative) onSelect?.(representative);
              }}
              onPointerMove={(event) => {
                event.stopPropagation();
                if (hoverNode) onHover?.(hoverNode, event);
              }}
              onPointerOut={() => onHover?.(null)}
            >
              <sphereGeometry args={[1, 12, 8]} />
              <meshBasicMaterial transparent opacity={0} depthWrite={false} colorWrite={false} />
            </mesh>
            <mesh rotation={[Math.PI / 2, 0, 0]} scale={[1.35, 0.72, 1]}>
              <torusGeometry args={[visual.ringRadius, 0.008, 5, 36]} />
              <meshBasicMaterial color={visual.laneColor} transparent opacity={0.24} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
            </mesh>
            <group position={[0, 0.075, 0]} renderOrder={5}>
              <MiniFamilyGlyph family={visual.family} color={visual.color} mass={visual.glyphMass} center={false} />
            </group>
            {visual.labelVisible && (
              <Html position={[0, 0.22, 0]} center distanceFactor={8} className="sceneHtmlLabel sceneClusterLabel" occlude={false}>
                <button
                  type="button"
                  title={`${visualFamilyLabel(cluster.family)} · ${cluster.count}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    if (representative) onSelect?.(representative);
                  }}
                  onPointerMove={(event) => {
                    event.stopPropagation();
                    if (hoverNode) onHover?.(hoverNode, event as unknown as ThreeEvent<PointerEvent>);
                  }}
                  onPointerOut={() => onHover?.(null)}
                >
                  <span className="sceneClusterCount">{cluster.count}</span>
                  <span className="sceneClusterDetail">{visualFamilyLabel(cluster.family)}</span>
                </button>
              </Html>
            )}
            {cluster.count >= 4 && (
              <mesh position={[0, 0.035, 0]} scale={[0.035, 0.035, 0.035]}>
                <sphereGeometry args={[1, 8, 6]} />
                <meshBasicMaterial color={visual.laneColor} transparent opacity={0.42} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
              </mesh>
            )}
          </group>
        );
      })}
    </group>
  );
}

function compositionArcPoints(arc: GroupCompositionArc, quality: SceneQuality | string): THREE.Vector3[] {
  const span = Math.max(arc.end - arc.start, 0.08);
  const segments = Math.max(8, Math.ceil((span / (Math.PI * 2)) * (quality === "compact" ? 48 : 96)));
  return Array.from({ length: segments + 1 }, (_, step) => {
    const angle = arc.start + (step / segments) * span;
    const lift = 0.22 + Math.sin((step / segments) * Math.PI) * 0.018;
    return new THREE.Vector3(Math.cos(angle) * arc.radius, lift, Math.sin(angle) * arc.radius);
  });
}

function CompositionArcMarker({ arc, quality }: { arc: GroupCompositionArc; quality: SceneQuality | string }) {
  const angle = (arc.start + arc.end) / 2;
  const scale = quality === "compact" ? 0.72 : 1;
  const height = (0.14 + arc.share * 0.28) * scale;
  const position: [number, number, number] = [Math.cos(angle) * arc.radius, 0.27, Math.sin(angle) * arc.radius];
  const material = (
    <meshBasicMaterial color={arc.color} transparent opacity={0.68} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
  );
  const ghost = (
    <meshBasicMaterial color="#dff8ff" transparent opacity={0.24} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
  );
  return (
    <group position={position} rotation={[0, -angle, 0]} renderOrder={6}>
      {arc.laneKind === "attention" && (
        <>
          <mesh position={[0, height * 0.5, 0]} scale={[0.022 * scale, height, 0.022 * scale]}>
            <cylinderGeometry args={[1, 1, 1, 8]} />
            {material}
          </mesh>
          <mesh position={[0, height + 0.035, 0]}>
            <sphereGeometry args={[0.045 * scale, 10, 8]} />
            {material}
          </mesh>
        </>
      )}
      {arc.laneKind === "evidence" && (
        <group position={[0, height * 0.42, 0]}>
          {[0, 1, 2].map((index) => (
            <mesh key={`composition-evidence-${index}`} position={[0, index * 0.036 * scale, (index - 1) * 0.025 * scale]} scale={[0.12 * scale, 0.014 * scale, 0.052 * scale]}>
              <boxGeometry args={[1, 1, 1]} />
              {index === 1 ? material : ghost}
            </mesh>
          ))}
        </group>
      )}
      {arc.laneKind === "gap" && (
        <group position={[0, height * 0.52, 0]}>
          <mesh position={[-0.05 * scale, 0, 0]} scale={[0.018 * scale, 0.12 * scale, 0.024 * scale]}>
            <boxGeometry args={[1, 1, 1]} />
            {material}
          </mesh>
          <mesh position={[0.05 * scale, 0, 0]} scale={[0.018 * scale, 0.12 * scale, 0.024 * scale]}>
            <boxGeometry args={[1, 1, 1]} />
            {material}
          </mesh>
          <mesh position={[0, 0.052 * scale, 0]} scale={[0.072 * scale, 0.014 * scale, 0.02 * scale]}>
            <boxGeometry args={[1, 1, 1]} />
            {ghost}
          </mesh>
        </group>
      )}
      {arc.laneKind === "context" && (
        <group position={[0, height * 0.48, 0]}>
          <mesh rotation={[Math.PI / 2, 0, 0]}>
            <torusGeometry args={[0.054 * scale, 0.008 * scale, 5, 20]} />
            {material}
          </mesh>
          <mesh>
            <sphereGeometry args={[0.026 * scale, 8, 6]} />
            {ghost}
          </mesh>
        </group>
      )}
    </group>
  );
}

function GroupCompositionCrown({
  arcs,
  motion,
  quality
}: {
  arcs: GroupCompositionArc[];
  motion: boolean;
  quality: SceneQuality | string;
}) {
  const ref = useRef<THREE.Group>(null);
  const { invalidate } = useThree();
  const lineObjects = useMemo(
    () =>
      arcs.map((arc) => {
        const geometry = new THREE.BufferGeometry().setFromPoints(compositionArcPoints(arc, quality));
        const material = new THREE.LineBasicMaterial({
          color: arc.color,
          transparent: true,
          opacity: Math.min(0.34, 0.13 + arc.share * 0.34),
          blending: THREE.AdditiveBlending,
          depthWrite: false,
          toneMapped: false
        });
        return { line: new THREE.Line(geometry, material), geometry, material, arc };
      }),
    [arcs, quality]
  );
  useFrame((state) => {
    if (!motion || !ref.current || quality === "compact") return;
    const elapsed = state.clock.elapsedTime;
    ref.current.rotation.y = Math.sin(elapsed * 0.18) * 0.025;
    lineObjects.forEach((object, index) => {
      object.material.opacity = Math.min(0.38, 0.14 + object.arc.share * 0.3 + Math.sin(elapsed * 1.4 + index) * 0.025);
    });
    state.invalidate();
  });
  useEffect(() => {
    invalidate();
    return () => {
      lineObjects.forEach((object) => {
        object.geometry.dispose();
        object.material.dispose();
      });
    };
  }, [invalidate, lineObjects]);
  if (arcs.length === 0) return null;
  return (
    <group ref={ref} renderOrder={4}>
      {lineObjects.map((object) => (
        <primitive key={`group-composition-crown-${object.arc.laneKind}-${object.arc.count}-${object.arc.start}`} object={object.line} />
      ))}
      {quality !== "compact" && arcs.map((arc) => <CompositionArcMarker key={`group-composition-marker-${arc.laneKind}-${arc.count}`} arc={arc} quality={quality} />)}
    </group>
  );
}

function GroupContainmentCurrent({
  flow,
  quality,
  motion
}: {
  flow: GroupContainmentFlow;
  quality: SceneQuality | string;
  motion: boolean;
}) {
  const materialRef = useRef<THREE.MeshBasicMaterial | null>(null);
  const headRef = useRef<THREE.Mesh | null>(null);
  const object = useMemo(() => {
    const start = new THREE.Vector3(Math.cos(flow.angle) * flow.radius, flow.y + 0.04, Math.sin(flow.angle) * flow.radius);
    const controlAngle = flow.angle + (flow.inbound ? 0.22 : -0.18);
    const middle = new THREE.Vector3(
      Math.cos(controlAngle) * flow.radius * 0.52,
      flow.y + 0.22 + flow.strength * 0.1,
      Math.sin(controlAngle) * flow.radius * 0.52
    );
    const endRadius = flow.inbound ? Math.max(flow.radius * 0.16, 0.34) : flow.radius * 0.84;
    const end = new THREE.Vector3(Math.cos(flow.angle) * endRadius, flow.inbound ? 0.16 : flow.y + 0.02, Math.sin(flow.angle) * endRadius);
    const curve = new THREE.CatmullRomCurve3(flow.inbound ? [start, middle, end] : [end, middle, start], false, "centripetal", 0.35);
    const geometry = new THREE.TubeGeometry(curve, quality === "rich" ? 28 : 18, 0.0075 * flow.strength, 5, false);
    const material = new THREE.MeshBasicMaterial({
      color: flow.color,
      transparent: true,
      opacity: quality === "compact" ? 0.1 : 0.16 + flow.strength * 0.05,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      toneMapped: false
    });
    const headGeometry = new THREE.SphereGeometry(0.035 + flow.strength * 0.01, 8, 6);
    return { curve, geometry, material, headGeometry };
  }, [flow, quality]);

  useEffect(() => {
    return () => {
      object.geometry.dispose();
      object.material.dispose();
      object.headGeometry.dispose();
    };
  }, [object]);

  useFrame((state) => {
    if (!motion) return;
    const elapsed = state.clock.elapsedTime;
    const t = (flow.phase + elapsed * flow.speed) % 1;
    const headT = flow.inbound ? t : 1 - t;
    const point = object.curve.getPoint(headT);
    if (headRef.current) headRef.current.position.copy(point);
    if (materialRef.current) {
      const pulse = Math.sin(elapsed * 2.2 + flow.phase * Math.PI * 2) * 0.035;
      materialRef.current.opacity = (quality === "compact" ? 0.08 : 0.14 + flow.strength * 0.05) + pulse;
    }
    state.invalidate();
  });

  return (
    <group renderOrder={3}>
      <mesh geometry={object.geometry} frustumCulled={false}>
        <meshBasicMaterial
          ref={materialRef}
          color={flow.color}
          transparent
          opacity={object.material.opacity}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
          toneMapped={false}
        />
      </mesh>
      {quality !== "compact" && (
        <mesh ref={headRef} geometry={object.headGeometry} frustumCulled={false} renderOrder={5}>
          <meshBasicMaterial color={flow.color} transparent opacity={0.58} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
        </mesh>
      )}
    </group>
  );
}

function GroupChildOrbitMotes({ summaries }: { summaries: GroupChildOrbitLaneSummary[] }) {
  const geometryRef = useRef<THREE.BufferGeometry>(null);
  const texture = glowTexture();
  const particles = useMemo(() => {
    const built: {
      laneKind: GroupChildOrbitLane;
      radius: number;
      y: number;
      phase: number;
      speed: number;
      bob: number;
      color: THREE.Color;
    }[] = [];
    summaries.forEach((summary) => {
      for (let index = 0; index < summary.moteCount; index += 1) {
        const seed = stableNumber(`${summary.laneKind}:${summary.count}:${index}:state-mote`);
        built.push({
          laneKind: summary.laneKind,
          radius: summary.radius,
          y: 0.12 + summary.lane * 0.05,
          phase: seed,
          speed: summary.speed * (0.85 + seed * 0.3),
          bob: 0.015 + seed * 0.025,
          color: new THREE.Color(summary.color)
        });
      }
    });
    return built;
  }, [summaries]);
  const buffers = useMemo(() => {
    const positions = new Float32Array(particles.length * 3);
    const colors = new Float32Array(particles.length * 3);
    particles.forEach((particle, index) => {
      colors[index * 3] = particle.color.r;
      colors[index * 3 + 1] = particle.color.g;
      colors[index * 3 + 2] = particle.color.b;
    });
    return { positions, colors };
  }, [particles]);
  useFrame((state) => {
    const geometry = geometryRef.current;
    if (!geometry || particles.length === 0) return;
    const elapsed = state.clock.elapsedTime;
    particles.forEach((particle, index) => {
      const direction = particle.laneKind === "gap" ? -1 : 1;
      const angle = particle.phase * Math.PI * 2 + elapsed * particle.speed * direction;
      const pulse = particle.laneKind === "attention" ? Math.sin(elapsed * 2.4 + particle.phase * 7) * 0.05 : 0;
      const radius = particle.radius + pulse;
      buffers.positions[index * 3] = Math.cos(angle) * radius;
      buffers.positions[index * 3 + 1] = particle.y + Math.sin(angle * 2 + particle.phase * 5) * particle.bob;
      buffers.positions[index * 3 + 2] = Math.sin(angle) * radius;
    });
    geometry.attributes.position.needsUpdate = true;
    state.invalidate();
  });
  if (!texture || particles.length === 0) return null;
  return (
    <points frustumCulled={false} renderOrder={4}>
      <bufferGeometry ref={geometryRef}>
        <bufferAttribute attach="attributes-position" args={[buffers.positions, 3]} />
        <bufferAttribute attach="attributes-color" args={[buffers.colors, 3]} />
      </bufferGeometry>
      <pointsMaterial
        map={texture}
        size={0.16}
        sizeAttenuation
        vertexColors
        transparent
        opacity={0.58}
        alphaTest={0.03}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        toneMapped={false}
      />
    </points>
  );
}

export function GroupChildOrbits({
  nodes,
  layoutLevel,
  quality,
  motion,
  onSelect,
  onHover
}: {
  nodes: LayoutNode[];
  layoutLevel: number;
  quality: SceneQuality | string;
  motion: boolean;
  onSelect?: (node: LayoutNode) => void;
  onHover?: (node: LayoutNode | null, event?: ThreeEvent<PointerEvent>) => void;
}) {
  const center = useMemo(() => nodes.find((node) => node.isRoot && node.isGroup) ?? null, [nodes]);
  const entries = useMemo(() => groupChildOrbitEntries(nodes, layoutLevel, quality), [layoutLevel, nodes, quality]);
  const nodeById = useMemo(() => new Map(nodes.flatMap((node) => [[node.id, node], [node.path, node]])), [nodes]);
  if (!center || entries.length < 2) return null;
  return <GroupChildOrbitField center={center} entries={entries} motion={motion} quality={quality} nodeById={nodeById} onSelect={onSelect} onHover={onHover} />;
}

function SemanticZoomMarkObject({ mark, scale }: { mark: SemanticZoomMark; scale: number }) {
  const material = <meshBasicMaterial color={mark.color} transparent opacity={0.78} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />;
  const ghost = <meshBasicMaterial color="#dff8ff" transparent opacity={0.22} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />;

  if (mark.key === "evidence") {
    return (
      <group rotation={[0, Math.PI / 9, 0]}>
        {[0, 1, 2].map((index) => (
          <mesh key={`semantic-evidence-${index}`} position={[0, index * scale * 0.18, (index - 1) * scale * 0.2]} scale={[scale * 1.12, scale * 0.12, scale * 0.5]}>
            <boxGeometry args={[1, 1, 1]} />
            {index === 1 ? material : ghost}
          </mesh>
        ))}
      </group>
    );
  }

  if (mark.key === "risk") {
    return (
      <group rotation={[0.22, Math.PI / 4, 0]}>
        <mesh scale={[scale * 0.72, scale * 0.92, scale * 0.72]}>
          <tetrahedronGeometry args={[1, 0]} />
          {material}
        </mesh>
        <mesh position={[0, scale * 0.08, 0]} scale={[scale * 0.92, scale * 0.08, scale * 0.92]}>
          <boxGeometry args={[1, 1, 1]} />
          {ghost}
        </mesh>
      </group>
    );
  }

  if (mark.key === "review") {
    return (
      <group rotation={[Math.PI / 2, 0, 0]}>
        <mesh>
          <torusGeometry args={[scale * 0.58, scale * 0.07, 5, 28]} />
          {material}
        </mesh>
        <mesh rotation={[0, 0, Math.PI / 4]}>
          <torusGeometry args={[scale * 0.25, scale * 0.04, 5, 18]} />
          {ghost}
        </mesh>
      </group>
    );
  }

  if (mark.key === "stale") {
    return (
      <group rotation={[0, -Math.PI / 10, 0]}>
        <mesh position={[-scale * 0.24, 0, 0]} scale={[scale * 0.12, scale * 0.9, scale * 0.12]}>
          <boxGeometry args={[1, 1, 1]} />
          {material}
        </mesh>
        <mesh position={[scale * 0.24, 0, 0]} scale={[scale * 0.12, scale * 0.9, scale * 0.12]}>
          <boxGeometry args={[1, 1, 1]} />
          {material}
        </mesh>
        <mesh scale={[scale * 0.68, scale * 0.08, scale * 0.08]}>
          <boxGeometry args={[1, 1, 1]} />
          {ghost}
        </mesh>
      </group>
    );
  }

  if (mark.key === "inbound") {
    return (
      <group>
        <mesh>
          <sphereGeometry args={[scale * 0.42, 10, 8]} />
          {material}
        </mesh>
        <mesh position={[scale * 0.36, 0, 0]} rotation={[0, 0, Math.PI / 2]} scale={[scale * 0.08, scale * 0.72, scale * 0.08]}>
          <cylinderGeometry args={[1, 1, 1, 8]} />
          {ghost}
        </mesh>
      </group>
    );
  }

  return (
    <group rotation={[0, 0, -Math.PI / 2]}>
      <mesh position={[0, scale * 0.18, 0]} scale={[scale * 0.38, scale * 0.62, scale * 0.1]}>
        <coneGeometry args={[1, 1, 3]} />
        {material}
      </mesh>
      <mesh position={[0, -scale * 0.18, 0]} scale={[scale * 0.08, scale * 0.56, scale * 0.08]}>
        <cylinderGeometry args={[1, 1, 1, 6]} />
        {ghost}
      </mesh>
    </group>
  );
}

function SemanticZoomMarkLayer({
  node,
  quality,
  radius,
  lift
}: {
  node: LayoutNode;
  quality: SceneQuality | string;
  radius: number;
  lift: number;
}) {
  const marks = useMemo(() => semanticZoomMarks(node, quality), [node, quality]);
  if (marks.length === 0) return null;
  return (
    <group renderOrder={7}>
      {marks.map((mark) => {
        const orbit = Math.max(radius * 0.74, 0.22);
        const position: [number, number, number] = [Math.cos(mark.angle) * orbit, lift + mark.lift + radius * 0.1, Math.sin(mark.angle) * orbit];
        const scale = Math.max(radius * mark.size, 0.026);
        return (
          <group key={`semantic-zoom-mark-${node.id}-${mark.key}`} position={position} rotation={[0, -mark.angle + Math.PI / 2, 0]}>
            <SemanticZoomMarkObject mark={mark} scale={scale} />
          </group>
        );
      })}
    </group>
  );
}

function SourceRecordGlyph({ node, bodyColor, stateColor, quality, motion }: { node: LayoutNode; bodyColor: string; stateColor: string; quality: SceneQuality | string; motion: boolean }) {
  const primitive = semanticObjectPrimitive(node);
  const scale = primitive?.primaryScale ?? node.scale;
  const lift = primitive?.lift ?? node.scale * 0.46;
  const streamCount = primitive?.streamCount ?? 3;
  const primary = Boolean(primitive?.isPrimary);
  const plateOpacity = primary ? 0.92 : 0.82;
  const glowOpacity = primary ? 0.68 : 0.5;
  const familyColor = pageTypeStyle("visual_group_source").accent || "#57d9a0";
  return (
    <group position={node.position} rotation={[0, Math.PI / 10, 0]} renderOrder={6}>
      <mesh position={[0, lift * 0.7, 0]} rotation={[Math.PI / 2, 0, 0]} frustumCulled={false}>
        <torusGeometry args={[scale * 0.58, Math.max(scale * 0.018, 0.006), 6, 46]} />
        <meshBasicMaterial color={stateColor} transparent opacity={primary ? 0.48 : 0.32} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
      </mesh>
      <mesh position={[-scale * 0.45, lift + scale * 0.05, 0]} scale={[scale * 0.12, scale * 0.28, scale * 0.66]} frustumCulled={false}>
        <boxGeometry args={[1, 1, 1]} />
        <meshBasicMaterial color={bodyColor} transparent opacity={plateOpacity} toneMapped={false} />
      </mesh>
      {[0, 1, 2, 3].map((index) => (
        <mesh
          key={`source-record-plate-${node.id}-${index}`}
          position={[scale * (0.02 + index * 0.035), lift + scale * (0.03 + index * 0.065), scale * ((index - 1.5) * 0.16)]}
          scale={[scale * (0.88 - index * 0.035), scale * 0.044, scale * 0.54]}
          frustumCulled={false}
        >
          <boxGeometry args={[1, 1, 1]} />
          <meshBasicMaterial color={index === 2 ? stateColor : familyColor} transparent opacity={index === 2 ? 0.82 : plateOpacity} toneMapped={false} />
        </mesh>
      ))}
      <mesh position={[scale * 0.42, lift + scale * 0.34, 0]} rotation={[0, 0, Math.PI / 2]} frustumCulled={false}>
        <cylinderGeometry args={[scale * 0.09, scale * 0.09, scale * 0.62, 16]} />
        <meshBasicMaterial color="#dff8ff" transparent opacity={glowOpacity} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
      </mesh>
      <mesh position={[scale * 0.1, lift - scale * 0.02, 0]} rotation={[Math.PI / 2, 0, 0]} frustumCulled={false}>
        <cylinderGeometry args={[scale * 0.18, scale * 0.24, scale * 0.82, 18]} />
        <meshBasicMaterial color={familyColor} transparent opacity={primary ? 0.34 : 0.22} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
      </mesh>
      {Array.from({ length: streamCount }).map((_, index) => {
        const angle = (index / streamCount) * Math.PI * 2;
        const radius = scale * (0.52 + (index % 2) * 0.12);
        return (
          <mesh
            key={`source-record-stream-${node.id}-${index}`}
            position={[Math.cos(angle) * radius, lift + scale * (0.24 + (index % 3) * 0.05), Math.sin(angle) * radius * 0.58]}
            frustumCulled={false}
          >
            <sphereGeometry args={[Math.max(scale * 0.035, 0.012), 8, 6]} />
            <meshBasicMaterial color={index % 2 === 0 ? stateColor : "#dff8ff"} transparent opacity={primary ? 0.76 : 0.52} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
          </mesh>
        );
      })}
      {primitive && (
        <SemanticObjectConstellation
          seedKey={node.id}
          primitive={primitive}
          color={familyColor}
          stateColor={stateColor}
          radius={scale * 0.72}
          lift={lift + scale * 0.16}
          quality={quality}
          motion={motion}
        />
      )}
      <SemanticZoomMarkLayer node={node} quality={quality} radius={scale * 0.72} lift={lift + scale * 0.34} />
    </group>
  );
}

function SemanticObjectConstellation({
  seedKey,
  primitive,
  color,
  stateColor,
  radius,
  lift,
  quality,
  motion
}: {
  seedKey: string;
  primitive: SemanticObjectPrimitive;
  color: string;
  stateColor: string;
  radius: number;
  lift: number;
  quality: SceneQuality | string;
  motion: boolean;
}) {
  const texture = glowTexture();
  const geometryRef = useRef<THREE.BufferGeometry>(null);
  const count = quality === "compact" ? 0 : Math.min(primitive.isPrimary ? 11 : 7, Math.max(3, primitive.streamCount + (primitive.isPrimary ? 2 : 0)));
  const buffers = useMemo(() => {
    const positions = new Float32Array(count * 3);
    const seeds = Array.from({ length: count }, (_, index) => {
      const seed = stableNumber(`${seedKey}:${primitive.family}:semantic-constellation:${index}`);
      const lane = index % 3;
      return {
        angle: seed * Math.PI * 2,
        lane,
        speed: 0.1 + seed * 0.18 + (primitive.isPrimary ? 0.06 : 0),
        bob: 0.012 + seed * 0.028
      };
    });
    seeds.forEach((seed, index) => {
      const orbit = radius * (0.54 + seed.lane * 0.14);
      positions[index * 3] = Math.cos(seed.angle) * orbit;
      positions[index * 3 + 1] = lift + seed.lane * radius * 0.055 + Math.sin(seed.angle * 1.4) * seed.bob;
      positions[index * 3 + 2] = Math.sin(seed.angle) * orbit * 0.72;
    });
    return { positions, seeds };
  }, [count, lift, primitive.family, primitive.isPrimary, radius, seedKey]);

  useFrame((state) => {
    if (!motion || quality === "compact" || !geometryRef.current || count === 0) return;
    const t = state.clock.elapsedTime;
    buffers.seeds.forEach((seed, index) => {
      const orbit = radius * (0.54 + seed.lane * 0.14);
      const angle = seed.angle + t * seed.speed;
      buffers.positions[index * 3] = Math.cos(angle) * orbit;
      buffers.positions[index * 3 + 1] = lift + seed.lane * radius * 0.055 + Math.sin(t * 1.1 + seed.angle) * seed.bob;
      buffers.positions[index * 3 + 2] = Math.sin(angle) * orbit * 0.72;
    });
    geometryRef.current.attributes.position.needsUpdate = true;
    state.invalidate();
  });

  if (!texture || count === 0) return null;
  return (
    <points frustumCulled={false} renderOrder={6}>
      <bufferGeometry ref={geometryRef}>
        <bufferAttribute attach="attributes-position" args={[buffers.positions, 3]} />
      </bufferGeometry>
      <pointsMaterial
        map={texture}
        color={primitive.family === "source" ? stateColor : color}
        size={primitive.isPrimary ? 0.095 : 0.065}
        sizeAttenuation
        transparent
        opacity={primitive.isPrimary ? 0.5 : 0.34}
        alphaTest={0.04}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        toneMapped={false}
      />
    </points>
  );
}

export function SemanticPageDetails({ nodes, overlay, quality, motion }: { nodes: LayoutNode[]; overlay: OverlayId; quality: SceneQuality | string; motion: boolean }) {
  const detailNodes = useMemo(() => semanticDetailNodes(nodes, quality), [nodes, quality]);

  if (detailNodes.length === 0) return null;

  return (
    <group>
      {detailNodes.map((node) => {
        const family = semanticDetailFamily(node.page_type);
        const bodyColor = visualEncodingResolver.resolve(node, overlay).color;
        const stateColor = trustDisplayColor(node);
        const primitive = semanticObjectPrimitive(node);
        if (family === "source") {
          return <SourceRecordGlyph key={`source-record-detail-${node.id}`} node={node} bodyColor={bodyColor} stateColor={stateColor} quality={quality} motion={motion} />;
        }
        const radius = Math.max(primitive?.primaryScale ?? node.scale * 1.65, 0.18);
        const crestPosition: [number, number, number] = [node.position[0], node.position[1] + Math.max(primitive?.lift ?? node.scale * 0.82, 0.16), node.position[2]];
        return (
          <group key={`semantic-page-detail-${node.id}`} position={crestPosition} renderOrder={5}>
            <GroupCoreGlyph node={node} radius={radius} color={bodyColor} isCenterGroup={false} />
            <SemanticZoomMarkLayer node={node} quality={quality} radius={radius * 0.72} lift={radius * 0.04} />
            {motion && primitive && (
              <SemanticObjectConstellation
                seedKey={node.id}
                primitive={primitive}
                color={bodyColor}
                stateColor={stateColor}
                radius={radius * 0.62}
                lift={radius * 0.16}
                quality={quality}
                motion={motion}
              />
            )}
            <mesh position={[0, radius * 0.08, 0]} rotation={[Math.PI / 2, 0, 0]}>
              <torusGeometry args={[radius * 0.3, Math.max(radius * 0.015, 0.006), 5, 24]} />
              <meshBasicMaterial color={stateColor} transparent opacity={0.42} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
            </mesh>
          </group>
        );
      })}
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
