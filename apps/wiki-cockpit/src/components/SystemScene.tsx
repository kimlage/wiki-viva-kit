// SystemScene: the navigable 3D knowledge world. The space itself is the
// navigation — drill level is camera altitude bound to the URL, perspectives
// re-arrange the same node identities (MORPH), and reading happens in-world.
// Honest encodings are non-negotiable: active overlay = body color + ring +
// symbol/text, context = position/label, shape = kind and line = typed relation;
// hidden pages are always countable cluster-stars.
//
// The scene's self-contained layers live in src/scene/parts/*; this file keeps
// the shell — route/patch types, Canvas wiring, the keyboard scheme, layout
// requests, morph bookkeeping and the SceneContent composition. Symbols that
// moved are re-exported below so existing import paths keep working.

import { Canvas, useFrame, useThree } from "@react-three/fiber";
import type { ThreeEvent } from "@react-three/fiber";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import type { AnchorRecord, GitState, GraphEdge, GraphNode } from "../types";
import { t } from "../data/i18n";
import { contextStyle, edgeStyle, isRawData, pageTypeStyle, trustColor, worldGroupLabel } from "../data/presentation";
import { regionPayloadByKey } from "../data/visualPrimitives";
import { SEMANTIC_VISUAL_TOKENS_VERSION, strongAttentionNodeIds, visualEncodingResolver } from "../data/visualEncoding";
import { nodeQuadrant, SCENE_FACETS } from "../scene/facets";
import type { QuadrantHomes, SceneFacet } from "../scene/facets";
import { scenePerformanceProfile } from "../scene/layout";
import type { LayoutNode, ScenePerformanceProfile } from "../scene/layout";
import { computeWorldLayout } from "../scene/perspectives";
import type { ClusterStar, PerspectiveId, WorldGroup, WorldLayout, WorldRequest } from "../scene/perspectives";
import { FoundingRite, GuideBeacon, SeedFlow, WorldPlate } from "../renderers/scene/spatial";
import type { FoundingSpec, GuideSpec, SeedSpec } from "../renderers/scene/spatial";
import { CameraDirector } from "../renderers/scene/parts/camera";
import { FallbackPlanView, SceneFallback } from "../renderers/scene/parts/fallback";
import { AggregateStateRim, DensityPressureField, DensityReliefField, DrillContextTethers, DrillOriginEcho, DrillWaypoints, FocusContextField, GateRing, HiddenDepthHalo, InspectionBeams, ParentDrillGate, ParentDrillPath, ProposalStems, QuadrantPlanes, RelationLanes, TravelWake, travelWakeLevel, WorldGuides } from "../renderers/scene/parts/guides";
import { HoverTooltip, sceneCensus, StatusStrip } from "../renderers/scene/parts/hud";
import type { AnchorHoverInfo, SceneFilter } from "../renderers/scene/parts/hud";
import { buildLabelSet, GroupRimPills, labelsForActivePlate, NodeLabels } from "../renderers/scene/parts/labels";
import { BirthBursts, QuestMarkers } from "../renderers/scene/parts/markers";
import type { MissionMarker } from "../renderers/scene/parts/markers";
import {
  allowAmbientMotion,
  edgeControlPointForLayout,
  freshnessLabel,
  layoutNodeIndex,
  nodeTrustKey,
  prefersReducedMotion,
  relationLanesForLayout,
  groupRelationBundlesForLayout,
  sceneFallbackReason,
  selectEvidenceFlowEdges,
  selectSceneEdges
} from "../renderers/scene/parts/materials";
import type { SceneEdge, SceneFallbackReason, TrustKey } from "../renderers/scene/parts/materials";
import { CenterSignalSprites, ClusterStars, GlowSprites, GroupChildOrbits, GroupShells, HorizonBeacons, NodeInstances, RingSprites, SemanticPageDetails, StarField, morphAttachmentOpacity, overlayCrossfadeWeights, semanticRootBodyPrimitive } from "../renderers/scene/parts/nodes";
import type { MorphState, OverlayTransitionState, SemanticRootBodyPrimitive } from "../renderers/scene/parts/nodes";
import { AmbientDriver, isEvidenceGap, SceneParticles } from "../renderers/scene/parts/particles-layer";
import { DEFAULT_VISUAL_CONTROL_CONFIG } from "./visualControl";
import type { VisualControlConfig } from "./visualControl";
import {
  latchRuntimePerformanceFallback,
  RUNTIME_PERFORMANCE_RESET_EVENT,
  RuntimePerformanceTelemetry,
  runtimePerformanceFallbackLatched,
  sustainedPerformanceFallbackRequired
} from "../world/performance";
import type { RuntimePerformanceEvidence } from "../world/performance";
import type { OverlayId, RuntimeMode, ViewId } from "../world/contracts";
import { motionDurationSeconds, overlayResolveDurationMs } from "../world/visual/motionGrammar";
import type { MotionIntent } from "../world/visual/motionGrammar";

// Moved symbols that other files import from this module (WorldView, tests,
// the visual-test mock) stay reachable at their old path via re-exports.
export { canUseWebGL, sceneFallbackPreferred } from "../renderers/scene/parts/materials";
export { FallbackPlanView };
export type { AnchorHoverInfo, MissionMarker };

// The guide beacon from the shell's side: WHERE it anchors is a page id — the
// scene resolves it to a live position (fallback: the root, then the void).
export type SceneGuide = Omit<GuideSpec, "anchor"> & { anchorId: string | null };
// The seed flow from the shell's side: the scene supplies the layout radius.
export type SceneSeed = Omit<SeedSpec, "rOuter">;

export type SceneRoute = {
  perspective: PerspectiveId;
  runtimeMode?: RuntimeMode;
  view?: ViewId;
  context?: string;
  group?: string;
  pageId?: string;
  centerId?: string;
  reader: boolean;
  filter: string;
  lens?: string;
  quadrant?: string;
};

export type ScenePatch = {
  perspective?: PerspectiveId;
  view?: ViewId | null;
  context?: string | null;
  group?: string | null;
  worldGroup?: string | null;
  pageId?: string | null;
  reader?: boolean;
  filter?: string | null;
  lens?: string | null;
  quadrant?: string | null;
  dock?: string | null;
};

export type SceneMotionSnapshot = {
  key: string;
  view: string;
  lens: string;
  overlay: OverlayId;
  group: string;
  level: number;
  center: string;
  page: string;
};

export type SceneMotionTransaction = SceneMotionSnapshot & {
  sequence: number;
  intent: MotionIntent;
  duration: number;
};

type SceneTransitionBookkeeping = {
  transaction: SceneMotionTransaction;
  overlay: OverlayTransitionState;
};

type PendingTravelOrigin = {
  point: [number, number, number];
  token: number;
};

type LayoutMotionBookkeeping = {
  layout: WorldLayout;
  morph: MorphState;
  cameraTravelVia: [number, number, number] | null;
  consumedTravelToken: number;
};

/** One semantic decision feeds the canvas morph, camera and DOM settle cue. */
export function sceneMotionIntent(
  previous: SceneMotionSnapshot | null,
  next: SceneMotionSnapshot
): MotionIntent {
  if (!previous || previous.view !== next.view) return "view";
  if (next.level < previous.level || (Boolean(previous.group) && !next.group)) return "retreat";
  if (
    next.level > previous.level ||
    previous.group !== next.group ||
    previous.center !== next.center
  ) {
    return "travel";
  }
  if (previous.page !== next.page) return previous.page && !next.page ? "retreat" : "control";
  if (previous.lens !== next.lens) return "lens";
  if (previous.overlay !== next.overlay) return "overlay";
  return "control";
}

export function sceneMotionDurationSeconds(intent: MotionIntent, speed: number, reduced = false): number {
  return intent === "overlay"
    ? overlayResolveDurationMs(speed, reduced) / 1_000
    : motionDurationSeconds(intent, speed, reduced);
}

export type RelationIsolation = "hierarquia" | "evidencia" | "links" | "citado-por";

// Global scene shortcuts must never operate underneath a primary interaction
// surface. `inert` removes DOM controls from pointer/focus navigation, but it
// cannot suspend this window-level listener by itself. Keep in-world summary
// plates out of this list: their Q/W/Enter shortcuts are part of the scene.
const GLOBAL_SHORTCUT_BLOCKING_SURFACES = [
  "[aria-modal='true']",
  ".worldNavigatorPanel",
  ".worldDock",
  ".pageReader",
  ".briefStudio",
  ".createSheet",
  ".visualControlPanel",
  ".packetTray",
  ".missionsPanel",
  ".templateInspector",
  ".genesisCard",
  ".genesisVoid"
].join(", ");

function globalSceneShortcutsBlocked(): boolean {
  return Boolean(document.querySelector(GLOBAL_SHORTCUT_BLOCKING_SURFACES));
}

function viewportSnapshot() {
  if (typeof window === "undefined") {
    return { width: 1200, pixelRatio: 1, hardwareConcurrency: 4, reducedMotion: false };
  }
  return {
    width: window.innerWidth,
    pixelRatio: window.devicePixelRatio || 1,
    hardwareConcurrency: navigator.hardwareConcurrency || 4,
    reducedMotion: prefersReducedMotion()
  };
}

function sceneVisualTuning(config: VisualControlConfig | undefined): VisualControlConfig {
  return config ?? DEFAULT_VISUAL_CONTROL_CONFIG;
}

function spacedPoint(point: [number, number, number], center: [number, number, number], spacing: number): [number, number, number] {
  return [
    center[0] + (point[0] - center[0]) * spacing,
    center[1] + (point[1] - center[1]) * (0.75 + spacing * 0.25),
    center[2] + (point[2] - center[2]) * spacing
  ];
}

function applyVisualSpacing(layout: WorldLayout, spacing: number): WorldLayout {
  if (Math.abs(spacing - 1) < 0.01) return layout;
  const center = layout.nodes.find((node) => node.isRoot)?.position ?? ([0, 0, 0] as [number, number, number]);
  const scaleRadius = (value: number | null) => value === null ? null : value * spacing;
  return {
    ...layout,
    nodes: layout.nodes.map((node) => ({
      ...node,
      position: node.isRoot ? node.position : spacedPoint(node.position, center, spacing)
    })),
    wedges: layout.wedges.map((wedge) => ({
      ...wedge,
      rimPosition: spacedPoint(wedge.rimPosition, center, spacing)
    })),
    guides: layout.guides.map((guide) => {
      if (guide.kind === "circle") return { ...guide, radius: guide.radius * spacing };
      if (guide.kind === "arc") return { ...guide, radius: guide.radius * spacing };
      return { ...guide, r0: guide.r0 * spacing, r1: guide.r1 * spacing };
    }),
    groups: layout.groups.map((group) => ({
      ...group,
      anchor: spacedPoint(group.anchor, center, spacing)
    })),
    clusterStars: layout.clusterStars.map((star) => ({
      ...star,
      position: spacedPoint(star.position, center, spacing)
    })),
    beacons: layout.beacons.map((beacon) => ({
      ...beacon,
      position: spacedPoint(beacon.position, center, spacing)
    })),
    rInner: layout.rInner * spacing,
    rOuter: layout.rOuter * spacing,
    unknownR: scaleRadius(layout.unknownR),
    cameraTarget: layout.cameraTarget ? spacedPoint(layout.cameraTarget, center, spacing) : undefined,
    drillOrigin: layout.drillOrigin ? spacedPoint(layout.drillOrigin, center, spacing) : undefined
  };
}

function useSceneProfile(nodeCount: number): ScenePerformanceProfile {
  const [snapshot, setSnapshot] = useState(viewportSnapshot);
  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const update = () => setSnapshot(viewportSnapshot());
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    window.addEventListener("resize", update);
    media?.addEventListener?.("change", update);
    return () => {
      window.removeEventListener("resize", update);
      media?.removeEventListener?.("change", update);
    };
  }, []);
  return useMemo(() => scenePerformanceProfile(nodeCount, snapshot), [nodeCount, snapshot]);
}

// Level-scoped deterministic layout, computed off the main thread when
// workers exist. requestId guards against out-of-order worker replies.
function useWorldLayout(request: WorldRequest): WorldLayout {
  const [layout, setLayout] = useState<WorldLayout>(() => { const l = computeWorldLayout(request); return l; });
  const requestRef = useRef(0);
  useEffect(() => {
    let active = true;
    requestRef.current += 1;
    const requestId = requestRef.current;
    const sync = () => {
      const next = computeWorldLayout(request);
      if (active && requestRef.current === requestId) setLayout(next);
    };
    // Real browsers only: test DOMs (happy-dom) expose a Worker that spins on
    // module workers, so anything with a Node `process` computes in-line.
    const canUseWorker = typeof Worker !== "undefined" && typeof process === "undefined";
    if (!canUseWorker) {
      sync();
      return () => {
        active = false;
      };
    }
    const worker = new Worker(new URL("../scene/layout.worker.ts", import.meta.url), { type: "module" });
    worker.onmessage = (event: MessageEvent<{ requestId?: number; layout: WorldLayout }>) => {
      if (active && event.data.requestId === requestId) setLayout(event.data.layout);
    };
    worker.onerror = () => sync();
    worker.postMessage({ ...request, requestId });
    return () => {
      active = false;
      worker.terminate();
    };
  }, [request]);
  return layout;
}

function EdgeArcs({ edges, layout, quality, morph }: { edges: SceneEdge[]; layout: WorldLayout; quality: string; morph: React.RefObject<MorphState> }) {
  const { invalidate } = useThree();
  const object = useMemo(() => {
    if (edges.length === 0) return null;
    const segments = quality === "compact" ? 1 : 12;
    const positions: number[] = [];
    const colors: number[] = [];
    const color = new THREE.Color();
    const from = new THREE.Vector3();
    const to = new THREE.Vector3();
    const control = new THREE.Vector3();
    for (const edge of edges) {
      from.set(...edge.from.position);
      to.set(...edge.to.position);
      control.set(...edgeControlPointForLayout(edge, layout));
      const curve = new THREE.QuadraticBezierCurve3(from.clone(), control.clone(), to.clone());
      const points = curve.getPoints(segments);
      color.set(edgeStyle(edge.type).color).multiplyScalar(edge.emphasis);
      for (let index = 0; index < points.length - 1; index += 1) {
        positions.push(points[index].x, points[index].y, points[index].z);
        positions.push(points[index + 1].x, points[index + 1].y, points[index + 1].z);
        colors.push(color.r, color.g, color.b, color.r, color.g, color.b);
      }
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(positions), 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(colors), 3));
    const material = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: morph.current?.active ? 0 : 0.95,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      toneMapped: false
    });
    return { lines: new THREE.LineSegments(geometry, material), geometry, material };
  }, [edges, layout, morph, quality]);
  useFrame((state) => {
    if (!object) return;
    object.material.opacity = morphAttachmentOpacity(morph.current, state.clock.elapsedTime, 0.95);
  });
  useEffect(() => {
    invalidate();
    return () => {
      object?.geometry.dispose();
      object?.material.dispose();
    };
  }, [invalidate, object]);
  if (!object) return null;
  return <primitive object={object.lines} />;
}

function mocParentRoute(edges: GraphEdge[], layout: WorldLayout, selectedId: string): LayoutNode[] {
  if (!selectedId) return [];
  const index = layoutNodeIndex(layout);
  const start = index.get(selectedId);
  if (!start) return [];
  const parentByChild = new Map<string, string>();
  edges.forEach((edge) => {
    if (edge.type === "moc_parent") parentByChild.set(edge.source, edge.target);
  });
  const route = [start];
  const seen = new Set([start.id]);
  let cursor: LayoutNode | undefined = start;
  while (cursor) {
    const parentKey: string | undefined = parentByChild.get(cursor.id) || parentByChild.get(cursor.path);
    const parent: LayoutNode | undefined = parentKey ? index.get(parentKey) : undefined;
    if (!parent || seen.has(parent.id)) break;
    route.push(parent);
    seen.add(parent.id);
    cursor = parent;
  }
  return route;
}

function RouteLine({ route, morph, color = "#dff8ff" }: { route: LayoutNode[]; morph: React.RefObject<MorphState>; color?: string }) {
  const { invalidate } = useThree();
  const object = useMemo(() => {
    if (route.length < 2) return null;
    const points = route.map((node) => new THREE.Vector3(...node.position));
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({ color, transparent: true, opacity: morph.current?.active ? 0 : 0.9, toneMapped: false });
    return { line: new THREE.Line(geometry, material), geometry, material };
  }, [color, morph, route]);
  useFrame((state) => {
    if (!object) return;
    object.material.opacity = morphAttachmentOpacity(morph.current, state.clock.elapsedTime, 0.9);
  });
  useEffect(() => {
    invalidate();
    return () => {
      object?.geometry.dispose();
      object?.material.dispose();
    };
  }, [invalidate, object]);
  if (!object) return null;
  return <primitive object={object.line} />;
}

function groupNodeMatchesId(node: LayoutNode, id: string): boolean {
  if (!id) return false;
  return node.id === id || node.path === id || node.groupKey === id || node.groupDrill?.group === id;
}

function GroupTethers({
  nodes,
  quality,
  motion,
  morph,
  activeGroupId = ""
}: {
  nodes: LayoutNode[];
  quality: string;
  motion: boolean;
  morph: React.RefObject<MorphState>;
  activeGroupId?: string;
}) {
  const { invalidate } = useThree();
  const materialRef = useRef<THREE.LineBasicMaterial | null>(null);
  const object = useMemo(() => {
    const center = nodes.find((node) => node.isRoot && node.isGroup) ?? nodes.find((node) => node.isRoot);
    if (!center) return null;
    const centerPoint = new THREE.Vector3(...center.position);
    const centerGroupMembers = new Set(center.groupMemberIds ?? []);
    const rootOverview = !center.isGroup;
    const limit = rootOverview ? (quality === "rich" ? 16 : quality === "balanced" ? 12 : 8) : quality === "rich" ? 30 : quality === "balanced" ? 22 : 12;
    const candidates = nodes
      .filter((node) => {
        if (node.id === center.id) return false;
        if (rootOverview) return node.isGroup && (node.groupKind === "quadrant" || node.groupKind === "region_family");
        if (node.isGroup) return true;
        return centerGroupMembers.has(node.id) || center.groupPreviewIds?.includes(node.id) || node.faint;
      })
      .sort((a, b) => {
        if (rootOverview) {
          const quadrantRank = Number(b.groupKind === "quadrant") - Number(a.groupKind === "quadrant");
          if (quadrantRank !== 0) return quadrantRank;
        }
        const groupRank = Number(b.isGroup) - Number(a.isGroup);
        if (groupRank !== 0) return groupRank;
        return centerPoint.distanceTo(new THREE.Vector3(...a.position)) - centerPoint.distanceTo(new THREE.Vector3(...b.position));
      })
      .slice(0, limit);
    if (candidates.length === 0) return null;
    const positions: number[] = [];
    const colors: number[] = [];
    const color = new THREE.Color();
    for (const node of candidates) {
      const target = new THREE.Vector3(...node.position);
      const distance = centerPoint.distanceTo(target);
      if (distance < 0.04) continue;
      const active = groupNodeMatchesId(node, activeGroupId) || groupNodeMatchesId(center, activeGroupId);
      const midpoint = centerPoint.clone().lerp(target, 0.5);
      midpoint.y += Math.min(Math.max(distance * 0.16, 0.18), 0.82);
      const curve = new THREE.QuadraticBezierCurve3(centerPoint.clone(), midpoint, target.clone());
      const points = curve.getPoints(quality === "compact" ? 5 : 10);
      const baseColor = node.isGroup ? pageTypeStyle(node.page_type).accent : contextStyle(node.context).accent;
      color.set(baseColor).multiplyScalar(active ? 1.18 : node.faint ? 0.62 : 0.86);
      for (let index = 0; index < points.length - 1; index += 1) {
        const fade = active ? 0.74 + (index / Math.max(points.length - 2, 1)) * 0.42 : 0.45 + (index / Math.max(points.length - 2, 1)) * 0.55;
        positions.push(points[index].x, points[index].y, points[index].z);
        positions.push(points[index + 1].x, points[index + 1].y, points[index + 1].z);
        colors.push(color.r * fade, color.g * fade, color.b * fade, color.r, color.g, color.b);
      }
    }
    if (positions.length === 0) return null;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(positions), 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(colors), 3));
    const material = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: morph.current?.active ? 0 : quality === "compact" ? 0.2 : 0.34,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      toneMapped: false
    });
    materialRef.current = material;
    return { lines: new THREE.LineSegments(geometry, material), geometry, material };
  }, [activeGroupId, morph, nodes, quality]);
  useFrame((state) => {
    if (!materialRef.current) return;
    const morphing = Boolean(morph.current?.active);
    const baseOpacity =
      (quality === "compact" ? 0.18 : activeGroupId ? 0.46 : 0.3) +
      (motion ? Math.sin(state.clock.elapsedTime * 1.8) * (activeGroupId ? 0.065 : 0.04) : 0);
    materialRef.current.opacity = morphAttachmentOpacity(morph.current, state.clock.elapsedTime, baseOpacity);
    if (motion || morphing) state.invalidate();
  });
  useEffect(() => {
    invalidate();
    return () => {
      object?.geometry.dispose();
      object?.material.dispose();
      if (materialRef.current === object?.material) materialRef.current = null;
    };
  }, [invalidate, object]);
  if (!object) return null;
  return <primitive object={object.lines} />;
}

// The target-lock ring was replaced by the WorldPlate (scene/spatial.tsx): the
// first reading level is an anchored SUMMARY at the node — the full reader is
// a chosen second step. Q/W/E/R keys keep working via the keyboard scheme.

// ---------------------------------------------------------------------------

function RuntimeFrameProbe({
  telemetry,
  width,
  onEvidence
}: {
  telemetry: RuntimePerformanceTelemetry;
  width: number;
  onEvidence: (evidence: RuntimePerformanceEvidence) => void;
}) {
  useFrame((_state, delta) => {
    const evidence = telemetry.recordFrame(delta * 1_000, width, document.visibilityState);
    if (evidence) onEvidence(evidence);
  });
  return null;
}

// The shared morph stays active until every registered layer has sampled its
// final frame. Keeping completion here prevents the instanced body from ending
// the transaction before labels, rings and halos reach the same coordinate.
function MorphCompletion({ morph }: { morph: React.RefObject<MorphState> }) {
  useFrame((state) => {
    const current = morph.current;
    if (!current?.active || current.start === null) return;
    if (state.clock.elapsedTime - current.start < current.duration) return;
    current.active = false;
    state.invalidate();
  });
  return null;
}

function OverlayTransitionCompletion({ transition }: { transition: React.RefObject<OverlayTransitionState> }) {
  useFrame((state) => {
    const current = transition.current;
    if (!current?.active) return;
    if (current.start === null) {
      current.start = state.clock.elapsedTime;
      state.invalidate();
      return;
    }
    if (current.duration > 0 && state.clock.elapsedTime - current.start < current.duration) return;
    current.active = false;
    state.invalidate();
  });
  return null;
}

function SceneContent({
  layout,
  overlay,
  edges,
  git,
  profile,
  selectedId,
  highlightedIds,
  approvalIds,
  focusedGroupKey,
  isolateRelation,
  walk,
  morph,
  transition,
  overlayTransition,
  cameraTravelVia,
  filter,
  motion,
  visualTuning,
  activityLevel,
  weather,
  activeAnchorRecord,
  activeQuadrant,
  quadrantHomes,
  bornIds,
  missionMarkers,
  flyToId,
  readerOpen,
  sourceNodeCount,
  performanceWidth,
  routeUsabilityMs,
  performanceTelemetry,
  onPerformanceEvidence,
  onMarkerAct,
  onMarkerResolve,
  onMarkerDismiss,
  onSelect,
  onHover,
  onGroupSelect,
  onStarDrill,
  onBeaconJump,
  onLockRead,
  onLockPacket,
  onLockTrails,
  onLockClose,
  onRetreat
}: {
  layout: WorldLayout;
  overlay: OverlayId;
  edges: GraphEdge[];
  git: GitState;
  profile: ScenePerformanceProfile;
  selectedId: string;
  highlightedIds: Set<string>;
  approvalIds: Set<string>;
  focusedGroupKey: string;
  isolateRelation: RelationIsolation | null;
  walk: { ids: string[]; step: number } | null;
  morph: React.RefObject<MorphState>;
  transition: SceneMotionTransaction;
  overlayTransition: React.RefObject<OverlayTransitionState>;
  cameraTravelVia: [number, number, number] | null;
  filter: SceneFilter | null;
  motion: boolean;
  visualTuning: VisualControlConfig;
  activityLevel: number;
  weather?: string;
  activeAnchorRecord?: AnchorRecord | null;
  activeQuadrant?: string;
  quadrantHomes?: QuadrantHomes;
  bornIds?: string[];
  missionMarkers?: MissionMarker[];
  flyToId?: string;
  readerOpen: boolean;
  sourceNodeCount: number;
  performanceWidth: number;
  routeUsabilityMs: number;
  performanceTelemetry: RuntimePerformanceTelemetry;
  onPerformanceEvidence: (evidence: RuntimePerformanceEvidence) => void;
  onMarkerAct?: (pageId: string) => void;
  onMarkerResolve?: (pageId: string) => void;
  onMarkerDismiss?: (pageId: string) => void;
  onSelect: (node: LayoutNode) => void;
  onHover: (node: LayoutNode | null, event?: ThreeEvent<PointerEvent>) => void;
  onGroupSelect: (group: WorldGroup) => void;
  onStarDrill: (star: ClusterStar) => void;
  onBeaconJump: (context: string) => void;
  onLockRead: () => void;
  onLockPacket: () => void;
  onLockTrails: () => void;
  onLockClose: () => void;
  onRetreat: () => void;
}) {
  const [hoveredId, setHoveredId] = useState("");
  // First-frame kick: in `frameloop="demand"` a freshly mounted scene can sit
  // UNPAINTED until some event invalidates (seen as a black world on fresh
  // loads/stage swaps). Invalidate deterministically on mount and on every new
  // layout — twice, so drei Html children that attach a beat later paint too.
  const { invalidate: invalidateScene } = useThree();
  useEffect(() => {
    invalidateScene();
    const raf = requestAnimationFrame(() => invalidateScene());
    const timer = window.setTimeout(() => invalidateScene(), 350);
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(timer);
    };
  }, [invalidateScene, layout]);
  const rootRef = useRef<THREE.Mesh | null>(null);
  const pulses = useRef<{ stale: THREE.SpriteMaterial[]; highlight: THREE.SpriteMaterial[]; staleMaterials: THREE.MeshStandardMaterial[] }>({
    stale: [],
    highlight: [],
    staleMaterials: []
  });
  pulses.current.stale = [];
  pulses.current.highlight = [];
  pulses.current.staleMaterials = [];

  const focusIds = useMemo(() => {
    const ids = new Set<string>();
    if (selectedId) ids.add(selectedId);
    if (hoveredId) ids.add(hoveredId);
    return ids;
  }, [hoveredId, selectedId]);

  const selectedKeys = useMemo(() => {
    const keys = new Set<string>();
    if (!selectedId) return keys;
    const index = layoutNodeIndex(layout);
    const node = index.get(selectedId);
    if (node) {
      keys.add(node.id);
      keys.add(node.path);
    } else {
      keys.add(selectedId);
    }
    return keys;
  }, [layout, selectedId]);

  const perspectiveEdges = useMemo(() => {
    if (layout.perspective === "sources") {
      return edges.filter((edge) => /source_ref|source_emission|ingestion_chain|evidence|emitt/i.test(edge.type));
    }
    if (layout.perspective === "work") {
      return edges.filter((edge) => /impact|proposal_transition|source_ref|ingestion_chain|assignment|owner/i.test(edge.type));
    }
    return edges;
  }, [edges, layout.perspective]);
  const sceneEdges = useMemo(
    () => selectSceneEdges(perspectiveEdges, layout, focusIds, highlightedIds, profile, isolateRelation, selectedKeys),
    [focusIds, highlightedIds, isolateRelation, layout, perspectiveEdges, profile, selectedKeys]
  );
  const relationLanes = useMemo(() => relationLanesForLayout(perspectiveEdges, layout), [layout, perspectiveEdges]);
  const groupRelationBundles = useMemo(() => groupRelationBundlesForLayout(perspectiveEdges, layout), [layout, perspectiveEdges]);
  const flowEdges = useMemo(() => {
    const attention = (node: LayoutNode) =>
      node.freshness_state === "stale" || node.approved_state === "proposal" || node.risk_flags.length > 0;
    const attentionFlows = sceneEdges.filter((edge) => {
      if (edge.type === "markdown_link") return edge.emphasis >= 1;
      if (edge.emphasis >= 1) return true;
      if (edge.type === "ingestion_chain" || edge.type === "pr_impact") return attention(edge.from) || attention(edge.to);
      return false;
    });
    const evidenceFlows = selectEvidenceFlowEdges(sceneEdges, layout, profile.quality);
    const byKey = new Map<string, SceneEdge>();
    for (const edge of [...attentionFlows, ...evidenceFlows]) {
      byKey.set(`${edge.from.id}->${edge.to.id}:${edge.type}`, edge);
    }
    return [...byKey.values()];
  }, [layout, profile.quality, sceneEdges]);
  const route = useMemo(() => mocParentRoute(edges, layout, selectedId), [edges, layout, selectedId]);
  const labelModeFactor = visualTuning.labels === "dense" ? 1.45 : visualTuning.labels === "quiet" ? 0.68 : 1;
  const labelDensityFactor = Math.max(0.6, Math.min(1.5, visualTuning.density));
  const baseLabelBudget = layout.perspective === "quadrants" ? (layout.level === 0 ? 6 : layout.level >= 2 ? 6 : 8) : 14;
  const labelBudget = Math.max(3, Math.round(baseLabelBudget * labelModeFactor * labelDensityFactor));
  const labels = useMemo(() => buildLabelSet(layout, highlightedIds, selectedId, labelBudget), [highlightedIds, labelBudget, layout, selectedId]);

  // Evidence walk: highlight the current hop and draw the walked chain.
  const walkRoute = useMemo(() => {
    if (!walk || walk.step < 0) return [];
    const index = layoutNodeIndex(layout);
    return walk.ids.slice(0, walk.step + 1).flatMap((id) => {
      const node = index.get(id);
      return node ? [node] : [];
    });
  }, [layout, walk]);
  const walkTargetId = walk && walk.step >= 0 ? walk.ids[walk.step] ?? "" : "";

  const dimTest = useCallback(
    (node: LayoutNode) => {
      // A4 — a selected AQAL quadrant scopes the SPATIAL views (radar/districts)
      // by dimming everything outside it (the quadrants map already separates
      // them spatially, so it is exempt). Honest: nothing is hidden, just muted.
      // The root/hubs stay lit as anchors.
      const outsideQuadrant =
        Boolean(activeQuadrant) &&
        layout.perspective !== "quadrants" &&
        !node.isRoot &&
        !node.isHub &&
        nodeQuadrant(node.id, node.page_type, quadrantHomes) !== activeQuadrant;
      if (filter === "raw") return outsideQuadrant || (!isRawData(node.page_type) && !node.isRoot);
      if (filter === "unsourced") return outsideQuadrant || (!isEvidenceGap(node.page_type, node.source_ref_count) && !node.isRoot);
      if (filter) return outsideQuadrant || (nodeTrustKey(node) !== filter && !node.isRoot);
      if (highlightedIds.size > 0) {
        return outsideQuadrant || (!highlightedIds.has(node.id) && !highlightedIds.has(node.path) && !node.isRoot && !node.isHub);
      }
      return outsideQuadrant;
    },
    [filter, highlightedIds, activeQuadrant, quadrantHomes, layout.perspective]
  );

  const registerMaterial = useCallback((trust: TrustKey | "root", dimmed: boolean, material: THREE.MeshStandardMaterial | null) => {
    if (material && trust === "stale" && !dimmed) pulses.current.staleMaterials.push(material);
  }, []);
  const registerPulse = useCallback((kind: "stale" | "highlight", material: THREE.SpriteMaterial | null) => {
    if (material) pulses.current[kind].push(material);
  }, []);

  const handleHover = useCallback(
    (node: LayoutNode | null, event?: ThreeEvent<PointerEvent>) => {
      setHoveredId(node ? node.id : "");
      onHover(node, event);
    },
    [onHover]
  );

  const rootNode = layout.nodes.find((node) => node.isRoot);
  const centerNode = layout.nodes.find((node) => node.isRoot && node.isGroup) ?? rootNode;
  const rootBody = rootNode ? semanticRootBodyPrimitive(rootNode.page_type) : null;
  const physicalDrillOrigin = cameraTravelVia ?? layout.drillOrigin ?? null;
  const hoveredNode = hoveredId ? layoutNodeIndex(layout).get(hoveredId) ?? null : null;
  const lockedNode = useMemo(() => {
    if (!selectedId) return null;
    const index = layoutNodeIndex(layout);
    return index.get(selectedId) ?? null;
  }, [layout, selectedId]);
  const plateNode = lockedNode && !readerOpen ? lockedNode : null;
  const visibleLabels = useMemo(() => labelsForActivePlate(labels, plateNode), [labels, plateNode]);
  const relationLineCount =
    sceneEdges.length +
    relationLanes.length +
    groupRelationBundles.length +
    (route.length > 1 ? 1 : 0) +
    (walkRoute.length > 1 ? 1 : 0);
  const labelCount =
    visibleLabels.length +
    (layout.perspective === "quadrants" && layout.level >= 1 ? 0 : layout.groups.length) +
    layout.clusterStars.length +
    layout.beacons.length +
    (missionMarkers?.length ?? 0) +
    (plateNode ? 1 : 0);
  const interactiveNodeCount = layout.nodes.length + layout.clusterStars.length + layout.beacons.length;
  useEffect(() => {
    onPerformanceEvidence(
      performanceTelemetry.updateCounters(
        {
          sourceNodes: sourceNodeCount,
          interactiveNodes: interactiveNodeCount,
          relationLines: relationLineCount,
          labels: labelCount,
          fallbackReason: null,
          routeUsabilityMs
        },
        performanceWidth
      )
    );
  }, [
    interactiveNodeCount,
    labelCount,
    onPerformanceEvidence,
    performanceTelemetry,
    performanceWidth,
    relationLineCount,
    routeUsabilityMs,
    sourceNodeCount
  ]);
  const publishParticleCount = useCallback(
    (particles: number) =>
      onPerformanceEvidence(performanceTelemetry.updateCounters({ particles }, performanceWidth)),
    [onPerformanceEvidence, performanceTelemetry, performanceWidth]
  );
  const travelWakeTarget = lockedNode ?? centerNode ?? null;
  const travelWakeColor = travelWakeTarget
    ? pageTypeStyle(travelWakeTarget.page_type).accent || contextStyle(travelWakeTarget.context).accent
    : "#dff8ff";
  const navigationWakeLevel = travelWakeLevel(layout.level, Boolean(lockedNode));

  // Weather atmosphere — a SUBTLE tint of the base void, driven by the same
  // honest computeCondition() signal the Condition strip prints in exact counts
  // (so it implies no data the strip doesn't already name). Clear = neutral.
  const sky = WEATHER_SKY[weather ?? "clear"] ?? WEATHER_SKY.clear;
  return (
    <>
      <color attach="background" args={[sky]} />
      <fogExp2 attach="fog" args={[sky, 0.032]} />
      <hemisphereLight args={["#1a3040", "#05080c", 0.45 + visualTuning.contrast * 0.08]} />
      <directionalLight position={[4, 6, 3]} intensity={1.02 + visualTuning.contrast * 0.18} color="#cfeaff" />
      <StarField quality={profile.quality} />
      {/* No data, no instrument: the EMPTY world is a pure void — no rings,
          no wedges, no gate torus. The founding rite is its only interface. */}
      {layout.nodes.length > 0 && <WorldGuides layout={layout} />}
      {layout.nodes.length > 0 && layout.level === 0 && <GateRing git={git} />}
      <DensityReliefField layout={layout} motion={motion} />
      <ProposalStems nodes={layout.nodes} morph={morph} />
      <EdgeArcs edges={sceneEdges} layout={layout} quality={profile.quality} morph={morph} />
      <RouteLine route={route} morph={morph} />
      {walkRoute.length > 1 && <RouteLine route={walkRoute} morph={morph} color={edgeStyle("source_ref").color} />}
      <GroupTethers nodes={layout.nodes} quality={profile.quality} motion={motion} morph={morph} activeGroupId={hoveredId} />
      <FocusContextField node={hoveredNode && hoveredNode.id !== lockedNode?.id ? hoveredNode : null} mode="hover" motion={motion} />
      <InspectionBeams node={hoveredNode && hoveredNode.id !== lockedNode?.id ? hoveredNode : null} motion={motion} />
      <FocusContextField node={lockedNode} mode="lock" motion={motion} />
      <HiddenDepthHalo layout={layout} motion={motion} />
      {physicalDrillOrigin && travelWakeTarget && (
        <TravelWake from={physicalDrillOrigin} to={travelWakeTarget.position} level={navigationWakeLevel} color={travelWakeColor} motion={motion} />
      )}
      <DensityPressureField layout={layout} motion={motion} />
      <AggregateStateRim layout={layout} motion={motion} />
      {layout.perspective === "quadrants" && layout.level >= 1 && centerNode?.isGroup && (
        <DrillOriginEcho layout={layout} origin={physicalDrillOrigin} motion={motion} onRetreat={onRetreat} />
      )}
      {layout.perspective === "quadrants" && layout.level >= 1 && centerNode?.isGroup && (
        <DrillContextTethers layout={layout} motion={motion} />
      )}
      {layout.perspective === "quadrants" && layout.level >= 1 && centerNode?.isGroup && (
        <DrillWaypoints layout={layout} motion={motion} />
      )}
      {layout.perspective === "quadrants" && layout.level >= 1 && centerNode?.isGroup && (
        <ParentDrillPath layout={layout} travelVia={physicalDrillOrigin} motion={motion} />
      )}
      {layout.perspective === "quadrants" && layout.level >= 1 && centerNode?.isGroup && (
        <ParentDrillGate layout={layout} travelVia={physicalDrillOrigin} motion={motion} onRetreat={onRetreat} />
      )}
      {!(layout.perspective === "quadrants" && layout.level >= 3 && !centerNode?.isGroup) && (
        <RelationLanes lanes={relationLanes} bundles={groupRelationBundles} layout={layout} motion={motion} />
      )}
      {/* Ambient pulse samples first; semantic overlay interpolation then owns
          the material for the short transaction and yields when it completes. */}
      <AmbientDriver enabled={motion && visualTuning.motion > 0.01} rootRef={rootRef} pulses={pulses} motionScale={visualTuning.motion} glow={visualTuning.glow} />
      <NodeInstances
        nodes={layout.nodes.filter((node) => !node.isRoot)}
        overlay={overlay}
        profile={profile}
        selectedId={selectedId}
        morph={morph}
        overlayTransition={overlayTransition}
        dimTest={dimTest}
        onSelect={onSelect}
        onHover={handleHover}
        registerMaterial={registerMaterial}
      />
      <SemanticPageDetails nodes={layout.nodes} overlay={overlay} quality={profile.quality} motion={motion} />
      {rootNode && rootBody && !rootNode.isGroup && (
        <mesh
          ref={rootRef}
          position={rootNode.position}
          scale={rootNode.scale}
          rotation={rootBody.rotation}
          frustumCulled={false}
          onClick={(event) => {
            event.stopPropagation();
            onSelect(rootNode);
          }}
          onPointerMove={(event) => handleHover(rootNode, event)}
          onPointerOut={() => handleHover(null)}
        >
          <RootBodyGeometry body={rootBody} segments={profile.geometrySegments} />
          <RootOverlayMaterial
            node={rootNode}
            overlay={overlay}
            body={rootBody}
            transition={overlayTransition}
          />
        </mesh>
      )}
      <CenterSignalSprites node={rootNode && !rootNode.isGroup ? rootNode : null} record={activeAnchorRecord} quality={profile.quality} motion={motion} />
      {layout.perspective === "quadrants" && (layout.level < 3 || layout.groups.some((group) => group.kind === "quadrant")) && (
        <QuadrantPlanes rOuter={layout.rOuter} activeQuadrant={activeQuadrant} />
      )}
      {missionMarkers && missionMarkers.length > 0 && onMarkerAct && (
        <QuestMarkers
          nodes={layout.nodes}
          markers={missionMarkers}
          selectedId={selectedId}
          onAct={onMarkerAct}
          onResolve={onMarkerResolve}
          onDismiss={onMarkerDismiss}
        />
      )}
      <GlowSprites nodes={layout.nodes} highlightedIds={highlightedIds} approvalIds={approvalIds} selectedId={selectedId} walkTargetId={walkTargetId} registerPulse={registerPulse} morph={morph} />
      {bornIds && bornIds.length > 0 && <BirthBursts nodes={layout.nodes} bornIds={bornIds} />}
      {layout.perspective === "quadrants" && (
        <GroupChildOrbits nodes={layout.nodes} layoutLevel={layout.level} quality={profile.quality} motion={motion} onSelect={onSelect} onHover={handleHover} />
      )}
      <GroupShells nodes={layout.nodes} overlay={overlay} motion={motion} quality={profile.quality} layoutLevel={layout.level} activeGroupId={hoveredId} morph={morph} overlayTransition={overlayTransition} onSelect={onSelect} onHover={handleHover} />
      <RingSprites nodes={layout.nodes} overlay={overlay} morph={morph} overlayTransition={overlayTransition} />
      <SceneParticles
        layout={layout}
        flowEdges={flowEdges}
        activityLevel={activityLevel}
        quality={profile.quality}
        motion={motion}
        showGaps={filter === "unsourced"}
        density={visualTuning.density}
        glow={visualTuning.glow}
        motionScale={visualTuning.motion}
        enabled={visualTuning.particles}
        onCount={publishParticleCount}
      />
      <NodeLabels labels={visibleLabels} overlay={overlay} selectedId={selectedId} morph={morph} groups={layout.groups} onGroupSelect={onGroupSelect} />
      {!(layout.perspective === "quadrants" && layout.level >= 1) && (
        <GroupRimPills groups={layout.groups} focusedGroupKey={focusedGroupKey} onGroupSelect={onGroupSelect} />
      )}
      <ClusterStars stars={layout.clusterStars} onDrill={onStarDrill} />
      <HorizonBeacons beacons={layout.beacons} onJump={onBeaconJump} />
      {/* R7 — two-level reading: the locked node shows its SUMMARY plate in
          place; the full reader (a dock) is the chosen second step and hides
          the plate while open. */}
      {plateNode && (
        <WorldPlate node={plateNode} onOpen={onLockRead} onTrails={onLockTrails} onPacket={onLockPacket} onClose={onLockClose} />
      )}
      <CameraDirector
        layout={layout}
        lockedNode={lockedNode}
        flyToNode={flyToId ? layoutNodeIndex(layout).get(flyToId) ?? null : null}
        travelVia={physicalDrillOrigin}
        enableIntro={profile.enableIntro}
        motion={motion}
        motionScale={visualTuning.motion}
        transition={transition}
      />
      <RuntimeFrameProbe telemetry={performanceTelemetry} width={performanceWidth} onEvidence={onPerformanceEvidence} />
      <MorphCompletion morph={morph} />
      <OverlayTransitionCompletion transition={overlayTransition} />
    </>
  );
}

// ---------------------------------------------------------------------------

const NO_EDGES: GraphEdge[] = [];
const NO_IDS: string[] = [];

function RootOverlayMaterial({
  node,
  overlay,
  body,
  transition
}: {
  node: LayoutNode;
  overlay: OverlayId;
  body: SemanticRootBodyPrimitive;
  transition: React.RefObject<OverlayTransitionState>;
}) {
  const ref = useRef<THREE.MeshStandardMaterial | null>(null);
  const { invalidate } = useThree();
  const current = transition.current;
  const fromOverlay = current?.to === overlay ? current.from : overlay;
  const fromEncoding = useMemo(() => visualEncodingResolver.resolve(node, fromOverlay), [fromOverlay, node]);
  const encoding = useMemo(() => visualEncodingResolver.resolve(node, overlay), [node, overlay]);
  const fromColor = useMemo(() => new THREE.Color(), []);
  const toColor = useMemo(() => new THREE.Color(), []);
  const mixedColor = useMemo(() => new THREE.Color(), []);
  const applyEncoding = useCallback(
    (progress: number) => {
      const material = ref.current;
      if (!material) return;
      const active = transition.current;
      const transitioning = Boolean(active?.active && active.from === fromOverlay && active.to === overlay);
      const weights = transitioning ? overlayCrossfadeWeights(node.id, progress) : { from: 0, to: 1 };
      mixedColor.lerpColors(fromColor.set(fromEncoding.color), toColor.set(encoding.color), weights.to);
      material.color.copy(mixedColor);
      material.emissive.copy(mixedColor);
      material.emissiveIntensity = THREE.MathUtils.lerp(
        Math.max(fromEncoding.emissive, body.emissiveIntensity * 0.35),
        Math.max(encoding.emissive, body.emissiveIntensity * 0.35),
        weights.to
      );
      material.opacity = body.opacity * THREE.MathUtils.lerp(fromEncoding.opacity, encoding.opacity, weights.to);
    },
    [body.emissiveIntensity, body.opacity, encoding, fromColor, fromEncoding, fromOverlay, mixedColor, node.id, overlay, toColor, transition]
  );

  useLayoutEffect(() => {
    const active = transition.current;
    applyEncoding(active?.active && active.from === fromOverlay && active.to === overlay ? 0 : 1);
    invalidate();
  }, [applyEncoding, fromOverlay, invalidate, overlay, transition]);

  useFrame((state) => {
    const active = transition.current;
    if (!active?.active || active.to !== overlay) return;
    if (active.start === null) active.start = state.clock.elapsedTime;
    const progress = active.duration <= 0
      ? 1
      : Math.min((state.clock.elapsedTime - active.start) / active.duration, 1);
    applyEncoding(progress);
    state.invalidate();
  });

  return (
    <meshStandardMaterial
      ref={ref}
      color={encoding.color ?? body.color}
      emissive={encoding.color ?? body.color}
      emissiveIntensity={Math.max(encoding.emissive, body.emissiveIntensity * 0.35)}
      roughness={body.roughness}
      metalness={body.metalness}
      transparent={body.opacity < 1 || fromEncoding.opacity < 1 || encoding.opacity < 1}
      opacity={body.opacity * encoding.opacity}
      toneMapped={false}
    />
  );
}

function RootBodyGeometry({ body, segments }: { body: SemanticRootBodyPrimitive; segments: number }) {
  if (body.geometry === "source_slab") return <boxGeometry args={[1.35, 0.22, 0.82]} />;
  if (body.geometry === "person_totem") return <cylinderGeometry args={[0.52, 0.7, 1.05, 16]} />;
  if (body.geometry === "event_ring") return <torusGeometry args={[0.68, 0.08, 8, 42]} />;
  if (body.geometry === "action_beacon") return <coneGeometry args={[0.72, 1.18, 4]} />;
  if (body.geometry === "rule_plinth") return <boxGeometry args={[1.2, 0.32, 0.55]} />;
  if (body.geometry === "hub_gate") return <torusGeometry args={[0.72, 0.09, 6, 42]} />;
  if (body.geometry === "decision_crystal") return <octahedronGeometry args={[0.86, 0]} />;
  if (body.geometry === "content_sheet") return <boxGeometry args={[0.78, 0.16, 1.02]} />;
  return <sphereGeometry args={[1, segments + 8, segments + 8]} />;
}

// Weather → the void's sky/fog color. Kept very dark and near-neutral so it
// reads as atmosphere, never as a colored data layer. blocked=ember, aging=amber,
// unverified=cool violet, clear=the base void.
const WEATHER_SKY: Record<string, string> = {
  clear: "#05090e",
  aging: "#0b0a07",
  unverified: "#08080e",
  blocked: "#0d0708"
};

export function SystemScene({
  nodes,
  overlay = "attention",
  sourceNodeCount: sourceNodeCountInput,
  edges = NO_EDGES,
  git,
  route,
  packetIds = NO_IDS,
  highlightedPageIds = NO_IDS,
  approvalPageIds = NO_IDS,
  isolateRelation = null,
  walk = null,
  snapshotAt,
  activityLevel = 0,
  weather = "clear",
  visualTuning: visualTuningInput,
  bornPageIds,
  missionMarkers,
  flyToPageId,
  anchorInfo,
  activeAnchorRecord,
  centerHasQuadrants = false,
  quadrantHomes,
  founding = null,
  seed = null,
  guide = null,
  onMarkerResolve,
  onMarkerDismiss,
  onNavigate,
  onRetreat,
  onHistoryBack,
  onFocusSearch,
  onTogglePacket,
  onRunRefresh,
  makeHref,
  children
}: {
  nodes: GraphNode[];
  overlay?: OverlayId;
  sourceNodeCount?: number;
  edges?: GraphEdge[];
  git: GitState;
  route: SceneRoute;
  packetIds?: string[];
  highlightedPageIds?: string[];
  approvalPageIds?: string[];
  isolateRelation?: RelationIsolation | null;
  walk?: { ids: string[]; step: number } | null;
  snapshotAt?: string;
  activityLevel?: number;
  weather?: string;
  visualTuning?: VisualControlConfig;
  bornPageIds?: string[];
  missionMarkers?: MissionMarker[];
  flyToPageId?: string;
  anchorInfo?: Record<string, AnchorHoverInfo>;
  activeAnchorRecord?: AnchorRecord | null;
  centerHasQuadrants?: boolean;
  // Per-page quadrant classification from the interpretation layer — the
  // scene never re-derives what the compiler already decided.
  quadrantHomes?: QuadrantHomes;
  // Spatial surfaces (R1/R4/R5): the founding rite of an empty world, the
  // in-world create flow, the tutorial guide beacon.
  founding?: FoundingSpec | null;
  seed?: SceneSeed | null;
  guide?: SceneGuide | null;
  onMarkerResolve?: (pageId: string) => void;
  onMarkerDismiss?: (pageId: string) => void;
  onNavigate?: (patch: ScenePatch) => void;
  onRetreat?: () => void;
  onHistoryBack?: () => void;
  onFocusSearch?: () => void;
  onTogglePacket?: (nodeId: string) => void;
  onRunRefresh?: () => void;
  makeHref?: (patch: ScenePatch) => string;
  children?: React.ReactNode;
}) {
  const [environmentFallbackReason, setEnvironmentFallbackReason] = useState<SceneFallbackReason | null>(sceneFallbackReason);
  const [performanceFallbackLatched, setPerformanceFallbackLatched] = useState(runtimePerformanceFallbackLatched);
  const performanceFallbackLatchedRef = useRef(performanceFallbackLatched);
  const fallbackReason: SceneFallbackReason | null = performanceFallbackLatched
    ? "performance_budget"
    : environmentFallbackReason;
  const fallback = fallbackReason !== null;
  const [motion, setMotion] = useState(allowAmbientMotion);
  const profile = useSceneProfile(nodes.length);
  const visualTuning = sceneVisualTuning(visualTuningInput);
  const visualMotion = motion && visualTuning.motion > 0.01;
  const sourceNodeCount = sourceNodeCountInput ?? nodes.length;
  const performanceTelemetry = useMemo(() => new RuntimePerformanceTelemetry(), []);
  const performanceOutputRef = useRef<HTMLOutputElement>(null);
  const sceneShellRef = useRef<HTMLDivElement>(null);
  const performanceRouteKey = [route.perspective, route.context, route.group, route.pageId, route.filter, route.lens, route.quadrant].join("|");
  const performanceRouteRef = useRef({ key: performanceRouteKey, startedAt: typeof performance === "undefined" ? 0 : performance.now() });
  if (performanceRouteRef.current.key !== performanceRouteKey) {
    performanceRouteRef.current = {
      key: performanceRouteKey,
      startedAt: typeof performance === "undefined" ? 0 : performance.now()
    };
    performanceTelemetry.resetFrames();
  }
  const publishPerformanceEvidence = useCallback((evidence: RuntimePerformanceEvidence) => {
    const output = performanceOutputRef.current;
    if (!output) return;
    const active = evidence.evaluations[evidence.activeDevice]!.normal;
    const serialized = JSON.stringify(evidence);
    output.value = serialized;
    output.textContent = serialized;
    output.dataset.performanceReady = "true";
    output.dataset.performanceDevice = evidence.activeDevice;
    output.dataset.performanceStatus = active.status;
    output.dataset.performanceSamples = String(evidence.sampleCount);
    output.dataset.performanceInteractiveNodes = String(evidence.counters.interactiveNodes);
    output.dataset.performanceRelationLines = String(evidence.counters.relationLines);
    output.dataset.performanceLabels = String(evidence.counters.labels);
    output.dataset.performanceParticles = String(evidence.counters.particles);
    output.dataset.performanceFallbackReason = evidence.counters.fallbackReason ?? "";
    output.dataset.performanceFrameMedian = evidence.counters.frameTimeMedianMs?.toFixed(2) ?? "";
    output.dataset.performanceFrameP95 = evidence.counters.frameTimeP95Ms?.toFixed(2) ?? "";
    if (sustainedPerformanceFallbackRequired(evidence) && !performanceFallbackLatchedRef.current) {
      performanceFallbackLatchedRef.current = true;
      latchRuntimePerformanceFallback();
      setPerformanceFallbackLatched(true);
    }
  }, []);
  useEffect(() => {
    const resetMeasurementWindow = () => {
      // A fallback verdict is session-latched and has no live renderer left to
      // remeasure. Preserve its published proof across tab visibility changes.
      if (fallback || performanceFallbackLatchedRef.current) return;
      performanceTelemetry.resetFrames();
      const output = performanceOutputRef.current;
      if (!output) return;
      output.value = "";
      output.textContent = "";
      output.dataset.performanceReady = "false";
      output.dataset.performanceSamples = "0";
      output.dataset.performanceFrameMedian = "";
      output.dataset.performanceFrameP95 = "";
    };
    window.addEventListener(RUNTIME_PERFORMANCE_RESET_EVENT, resetMeasurementWindow);
    document.addEventListener("visibilitychange", resetMeasurementWindow);
    return () => {
      window.removeEventListener(RUNTIME_PERFORMANCE_RESET_EVENT, resetMeasurementWindow);
      document.removeEventListener("visibilitychange", resetMeasurementWindow);
    };
  }, [fallback, performanceTelemetry]);
  // Cluster-stars with nothing deeper to open reveal in place by raising the
  // node budget for the current level; any route change resets it.
  const [revealBoost, setRevealBoost] = useState(0);
  useEffect(() => {
    setRevealBoost(0);
  }, [route.perspective, route.context, route.group, route.pageId]);
  const request = useMemo<WorldRequest>(
    () => ({
      perspective: route.perspective,
      context: route.context,
      group: route.group,
      pageId: route.pageId,
      centerId: route.centerId,
      quadrant: (route.lens || route.quadrant || undefined) as WorldRequest["quadrant"],
      quadrantHomes,
      centerHasQuadrants,
      nodes,
      edges,
      maxNodes: Math.min(Math.max(24, Math.round(profile.maxNodes * visualTuning.density)) + revealBoost, 480),
      snapshotAt
    }),
    [
      edges,
      nodes,
      profile.maxNodes,
      visualTuning.density,
      quadrantHomes,
      centerHasQuadrants,
      revealBoost,
      route.centerId,
      route.context,
      route.group,
      route.pageId,
      route.perspective,
      route.lens,
      route.quadrant,
      snapshotAt
    ]
  );
  const rawLayout = useWorldLayout(request);
  const enrichedLayout = useMemo<WorldLayout>(() => {
    const regions = regionPayloadByKey(activeAnchorRecord);
    if (regions.size === 0) return rawLayout;
    return {
      ...rawLayout,
      groups: rawLayout.groups.map((group) => {
        const region = regions.get(group.labelKey) ?? regions.get(group.key);
        if (!region) return group;
        return {
          ...group,
          // The region payload may cover only the compiler-classified slice of
          // a larger canonical view. It enriches the group with evidence and
          // actions, but can never replace the layout's honest page census.
          region
        };
      })
    };
  }, [activeAnchorRecord, rawLayout]);
  const layout = useMemo<WorldLayout>(
    () => applyVisualSpacing(enrichedLayout, visualTuning.spacing),
    [enrichedLayout, visualTuning.spacing]
  );
  const presentationParts = {
    view: layout.perspective,
    lens: route.lens || route.quadrant || "",
    overlay,
    group: layout.group || "",
    level: layout.level,
    center: layout.nodes.find((node) => node.isRoot)?.id || route.centerId || "",
    page: route.pageId || ""
  };
  const presentation: SceneMotionSnapshot = {
    ...presentationParts,
    key: [
      presentationParts.view,
      presentationParts.lens,
      presentationParts.overlay,
      presentationParts.group,
      presentationParts.level,
      presentationParts.center,
      presentationParts.page
    ].join("|")
  };
  const [sceneTransitionState, setSceneTransitionState] = useState<SceneTransitionBookkeeping>(() => {
    const intent: MotionIntent = "view";
    return {
      transaction: {
        ...presentation,
        sequence: 1,
        intent,
        duration: sceneMotionDurationSeconds(intent, visualTuning.motion, !visualMotion || fallback)
      },
      overlay: {
        from: overlay,
        to: overlay,
        start: null,
        duration: 0,
        active: false
      }
    };
  });
  let activeSceneTransitionState = sceneTransitionState;
  const presentationChanged = sceneTransitionState.transaction.key !== presentation.key;
  const mustCutActiveMotion =
    (!visualMotion || fallback) &&
    (sceneTransitionState.transaction.duration > 0 || sceneTransitionState.overlay.active);
  if (presentationChanged || mustCutActiveMotion) {
    const previous = sceneTransitionState.transaction;
    if (presentationChanged) {
      const intent = sceneMotionIntent(previous, presentation);
      const requestedDuration = sceneMotionDurationSeconds(intent, visualTuning.motion, !visualMotion || fallback);
      // The navigator treats an overlay resolve as one atomic 300–400 ms
      // operation. If an external route nevertheless retargets it mid-flight,
      // cut directly to the latest truth instead of replaying the old target
      // as a visibly incorrect origin.
      const interruptedOverlay = intent === "overlay" && sceneTransitionState.overlay.active;
      const duration = interruptedOverlay ? 0 : requestedDuration;
      activeSceneTransitionState = {
        transaction: {
          ...presentation,
          sequence: previous.sequence + 1,
          intent,
          duration
        },
        overlay:
          intent === "overlay" && previous.overlay !== overlay && duration > 0
            ? {
                from: previous.overlay,
                to: overlay,
                start: null,
                duration,
                active: true
              }
            : {
                from: overlay,
                to: overlay,
                start: null,
                duration: 0,
                active: false
              }
      };
    } else {
      activeSceneTransitionState = {
        transaction: {
          ...previous,
          sequence: previous.sequence + 1,
          duration: 0
        },
        overlay: {
          from: overlay,
          to: overlay,
          start: null,
          duration: 0,
          active: false
        }
      };
    }
    // Render-phase state adjustment is intentional: React discards it with an
    // aborted render, unlike mutating a ref during render. The guarded second
    // render commits one coherent transaction to every WebGL layer.
    setSceneTransitionState(activeSceneTransitionState);
  }
  const sceneTransition = activeSceneTransitionState.transaction;
  const overlayTransition = useMemo<React.RefObject<OverlayTransitionState>>(
    () => ({ current: activeSceneTransitionState.overlay }),
    [activeSceneTransitionState.overlay]
  );
  const activeMotionIntent = sceneTransition.intent;
  const activeMotionDurationMs = !visualMotion || fallback ? 0 : Math.round(sceneTransition.duration * 1_000);
  const performanceWidth = typeof window === "undefined" ? 1200 : window.innerWidth;
  const routeUsabilityMs = useMemo(
    () => Math.max(0, (typeof performance === "undefined" ? 0 : performance.now()) - performanceRouteRef.current.startedAt),
    [layout, performanceRouteKey]
  );
  const [hover, setHover] = useState<{ node: LayoutNode; x: number; y: number } | null>(null);
  const [focusedGroupIndex, setFocusedGroupIndex] = useState<number>(-1);
  const [focusedNodeIndex, setFocusedNodeIndex] = useState<number>(-1);
  const [minimapExpanded, setMinimapExpanded] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const highlightedIds = useMemo(() => new Set(highlightedPageIds), [highlightedPageIds]);
  const approvalIds = useMemo(() => new Set(approvalPageIds), [approvalPageIds]);
  const census = useMemo(() => sceneCensus(nodes, edges, layout, overlay), [edges, layout, nodes, overlay]);
  const layoutPositionSignature = useMemo(
    () => layout.nodes.map((node) => `${node.id}@${node.position.join(",")}`).sort().join("|"),
    [layout]
  );
  const strongAttentionCount = useMemo(() => strongAttentionNodeIds(layout.nodes).size, [layout.nodes]);
  const nodeIndex = useMemo(() => layoutNodeIndex(layout), [layout]);
  const selectedId = route.pageId ?? "";
  const filter: SceneFilter | null =
    route.filter === "raw"
      ? "raw"
      : route.filter === "unsourced"
        ? "unsourced"
        : (["fresh", "stale", "unknown", "proposal"] as TrustKey[]).includes(route.filter as TrustKey)
          ? (route.filter as TrustKey)
          : null;

  useEffect(() => {
    if (!fallback) return;
    // Preserve the complete 120-frame proof that caused an adaptive fallback.
    // Environment fallbacks never sampled a usable renderer, so their empty
    // window remains the truthful representation.
    if (fallbackReason !== "performance_budget") performanceTelemetry.resetFrames();
    const visible = new Set(layout.nodes.flatMap((node) => [node.id, node.path]));
    const visibleRelations = edges.filter((edge) => visible.has(edge.source) && visible.has(edge.target)).length;
    publishPerformanceEvidence(
      performanceTelemetry.updateCounters(
        {
          sourceNodes: sourceNodeCount,
          interactiveNodes: layout.nodes.length + layout.clusterStars.length + layout.beacons.length,
          relationLines: visibleRelations,
          labels: layout.nodes.length + layout.groups.length + layout.clusterStars.length + layout.beacons.length,
          particles: 0,
          fallbackReason: fallbackReason ?? sceneFallbackReason() ?? "runtime_fallback",
          ...(fallbackReason === "performance_budget"
            ? {}
            : { frameTimeMedianMs: null, frameTimeP95Ms: null }),
          routeUsabilityMs
        },
        performanceWidth
      )
    );
  }, [
    edges,
    fallback,
    fallbackReason,
    layout,
    sourceNodeCount,
    performanceTelemetry,
    performanceWidth,
    publishPerformanceEvidence,
    routeUsabilityMs
  ]);

  const navigate = useCallback((patch: ScenePatch) => onNavigate?.(patch), [onNavigate]);
  const hrefFor = useCallback((patch: ScenePatch) => (makeHref ? makeHref(patch) : "#"), [makeHref]);

  // MORPH bookkeeping: remember the previous layout's positions so nodes keep
  // identity and glide between perspectives/levels; cut under reduced motion.
  const [pendingTravelOrigin, setPendingTravelOrigin] = useState<PendingTravelOrigin | null>(null);
  const nextTravelToken = useRef(0);
  const queueTravelOrigin = useCallback((point: [number, number, number]) => {
    nextTravelToken.current += 1;
    setPendingTravelOrigin({ point, token: nextTravelToken.current });
  }, []);
  const [layoutMotionState, setLayoutMotionState] = useState<LayoutMotionBookkeeping>(() => ({
    layout,
    morph: {
      from: new Map(),
      current: new Map(layout.nodes.map((node) => [node.id, node.position] as const)),
      start: null,
      duration: sceneTransition.duration,
      active: false,
      intent: sceneTransition.intent,
      sequence: sceneTransition.sequence
    },
    cameraTravelVia: null,
    consumedTravelToken: 0
  }));
  let activeLayoutMotionState = layoutMotionState;
  const layoutChanged = layoutMotionState.layout !== layout;
  const mustCutActiveMorph = (!visualMotion || fallback) && layoutMotionState.morph.active;
  if (layoutChanged || mustCutActiveMorph) {
    const previous = layoutMotionState.layout;
    let nextTravelVia: [number, number, number] | null = null;
    const hasPendingTravel =
      layoutChanged &&
      pendingTravelOrigin !== null &&
      pendingTravelOrigin.token > layoutMotionState.consumedTravelToken;
    const explicitOrigin = hasPendingTravel ? pendingTravelOrigin.point : null;
    if (layoutChanged && visualMotion && !fallback) {
      const from = new Map<string, [number, number, number]>();
      previous.nodes.forEach((node) => from.set(node.id, layoutMotionState.morph.current?.get(node.id) ?? node.position));
      const changedShape = previous.perspective !== layout.perspective || previous.level !== layout.level;
      const physicalQuadrantDrill =
        previous.perspective === "quadrants" &&
        layout.perspective === "quadrants" &&
        (Boolean(explicitOrigin) || (changedShape && previous.group !== layout.group));
      if (physicalQuadrantDrill) {
        const nextCenterGroup = layout.nodes.find((node) => node.isRoot && node.isGroup);
        const previousCenterPosition = nextCenterGroup ? previous.nodes.find((node) => node.id === nextCenterGroup.id)?.position : null;
        nextTravelVia = explicitOrigin ?? previousCenterPosition ?? null;
        if (nextTravelVia) {
          layout.nodes.forEach((node) => {
            if (!from.has(node.id) && (node.isGroup || (node.ring ?? 0) <= 2)) from.set(node.id, nextTravelVia!);
          });
        }
      } else if (explicitOrigin) {
        nextTravelVia = explicitOrigin;
      }

      // A native view can reveal many entities that the previous LOD did not
      // render. They still belong to the same world: let them unfold from the
      // closest prior semantic context instead of teleporting to final slots.
      if (changedShape || explicitOrigin) {
        const previousRoot = previous.nodes.find((node) => node.isRoot)?.position ?? ([0, 0, 0] as [number, number, number]);
        const contextOrigins = new Map<string, [number, number, number]>();
        previous.nodes.forEach((node) => {
          if (!contextOrigins.has(node.context) && (node.isGroup || node.isHub)) {
            contextOrigins.set(node.context, node.position);
          }
        });
        layout.nodes.forEach((node) => {
          if (!from.has(node.id)) {
            from.set(node.id, explicitOrigin ?? contextOrigins.get(node.context) ?? previousRoot);
          }
        });
      }
      const fallbackIntent: MotionIntent =
        previous.level > layout.level || (Boolean(previous.group) && !layout.group)
          ? "retreat"
          : physicalQuadrantDrill
            ? "travel"
            : changedShape
              ? "view"
              : "lens";
      const sharedTransaction =
        sceneTransition.sequence !== layoutMotionState.morph.sequence && sceneTransition.intent !== "overlay";
      const morphIntent = sharedTransaction ? sceneTransition.intent : fallbackIntent;
      activeLayoutMotionState = {
        layout,
        morph: {
          from,
          current: new Map(layoutMotionState.morph.current ?? []),
          start: null,
          duration: sharedTransaction
            ? sceneTransition.duration
            : motionDurationSeconds(morphIntent, visualTuning.motion),
          active: from.size > 0,
          intent: morphIntent,
          sequence: sceneTransition.sequence
        },
        cameraTravelVia: nextTravelVia,
        consumedTravelToken: hasPendingTravel
          ? pendingTravelOrigin!.token
          : layoutMotionState.consumedTravelToken
      };
    } else {
      activeLayoutMotionState = {
        layout,
        morph: {
          from: new Map(),
          current: new Map(layout.nodes.map((node) => [node.id, node.position] as const)),
          start: null,
          duration: 0,
          active: false,
          intent: sceneTransition.intent,
          sequence: sceneTransition.sequence
        },
        cameraTravelVia: null,
        consumedTravelToken: hasPendingTravel
          ? pendingTravelOrigin!.token
          : layoutMotionState.consumedTravelToken
      };
    }
    setLayoutMotionState(activeLayoutMotionState);
  }
  const morph = useMemo<React.RefObject<MorphState>>(
    () => ({ current: activeLayoutMotionState.morph }),
    [activeLayoutMotionState.morph]
  );
  const cameraTravelVia = activeLayoutMotionState.cameraTravelVia;

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => {
      setEnvironmentFallbackReason(sceneFallbackReason());
      setMotion(allowAmbientMotion());
    };
    update();
    media.addEventListener?.("change", update);
    window.addEventListener("popstate", update);
    document.addEventListener("visibilitychange", update);
    return () => {
      media.removeEventListener?.("change", update);
      window.removeEventListener("popstate", update);
      document.removeEventListener("visibilitychange", update);
    };
  }, []);

  const announce = useCallback((text: string) => setAnnouncement(text), []);

  useEffect(() => {
    setFocusedGroupIndex(-1);
    setFocusedNodeIndex(-1);
  }, [layout.perspective, layout.level, layout.context, layout.group]);

  const selectNode = useCallback(
    (node: LayoutNode) => {
      if (node.isGroup) {
        if (node.groupKind === "quadrant" && SCENE_FACETS.includes(node.groupLabelKey as SceneFacet)) {
          navigate({
            perspective: "quadrants",
            lens: node.groupLabelKey,
            reader: false
          });
          announce(t("scene.groupFocus", { label: node.title, n: node.groupMemberIds?.length ?? 0, shown: node.groupPreviewIds?.length ?? 0 }));
          return;
        }
        if (!node.groupDrill) {
          announce(t("scene.opening", { label: node.title, n: node.groupMemberIds?.length ?? 0 }));
          return;
        }
        queueTravelOrigin(node.position);
        navigate({
          context: node.groupDrill?.context ?? null,
          group: node.groupDrill?.group ?? null,
          pageId: null,
          reader: false
        });
        announce(t("scene.opening", { label: node.title, n: node.groupMemberIds?.length ?? 0 }));
        return;
      }
      // R7: a click LOCKS the node and shows its summary plate in place — the
      // full reader is a chosen second step (Enter/Q or the plate's Open).
      // The 2D fallback has no plates, so there a click opens the reader
      // directly — otherwise selecting would show nothing at all.
      queueTravelOrigin(node.position);
      navigate(fallback ? { pageId: node.id, reader: true } : { pageId: node.id });
      announce(`${node.title}, ${contextStyle(node.context).label}, ${freshnessLabel(node.freshness_state)}`);
    },
    [announce, fallback, navigate, queueTravelOrigin]
  );

  const handleHover = useCallback((node: LayoutNode | null, event?: ThreeEvent<PointerEvent>) => {
    if (!node || !event) {
      setHover(null);
      return;
    }
    const native = event.nativeEvent as PointerEvent;
    const shell = (native.target as HTMLElement | null)?.closest?.(".sceneShell") as HTMLElement | null;
    const bounds = shell?.getBoundingClientRect();
    setHover({
      node,
      x: bounds ? native.clientX - bounds.left : native.offsetX,
      y: bounds ? native.clientY - bounds.top : native.offsetY
    });
  }, []);

  const handleGroupSelect = useCallback(
    (group: WorldGroup) => {
      if (group.kind === "quadrant" && SCENE_FACETS.includes(group.labelKey as SceneFacet)) {
        navigate({
          perspective: "quadrants",
          lens: group.labelKey,
          reader: false
        });
        announce(t("scene.groupFocus", { label: worldGroupLabel(group.kind, group.labelKey), n: group.count, shown: group.shown }));
        return;
      }
      if (group.drill) {
        const origin =
          layout.nodes.find((node) => groupNodeMatchesId(node, group.key)) ??
          layout.nodes.find((node) => node.groupKind === group.kind && node.groupLabelKey === group.labelKey);
        queueTravelOrigin(origin?.position ?? group.anchor);
        navigate({ context: group.drill.context ?? null, group: group.drill.group ?? null, worldGroup: group.drill.group ?? null, pageId: null, reader: false });
        announce(t("scene.opening", { label: worldGroupLabel(group.kind, group.labelKey), n: group.count }));
        return;
      }
      const groupIndex = layout.groups.findIndex((item) => item.key === group.key);
      setFocusedGroupIndex(groupIndex);
      setFocusedNodeIndex(-1);
      announce(t("scene.groupFocus", { label: worldGroupLabel(group.kind, group.labelKey), n: group.count, shown: group.shown }));
    },
    [announce, layout.groups, navigate, queueTravelOrigin]
  );

  const handleStarDrill = useCallback(
    (star: ClusterStar) => {
      if (!star.drill) {
        // Deepest level: nothing to open — reveal the hidden pages here.
        const extra = Math.min(star.count, 160);
        setRevealBoost((current) => Math.min(current + extra, 480));
        announce(t("scene.showingMore", { n: extra, label: worldGroupLabel(star.kind, star.labelKey) }));
        return;
      }
      queueTravelOrigin(star.position);
      navigate({
        context: star.drill.context ?? route.context ?? null,
        group: star.drill.group ?? null,
        worldGroup: star.drill.group ?? null,
        pageId: null,
        reader: false
      });
      announce(t("scene.openingHidden", { n: star.count, label: worldGroupLabel(star.kind, star.labelKey) }));
    },
    [announce, navigate, queueTravelOrigin, route.context]
  );

  const handleBeaconJump = useCallback(
    (context: string) => {
      navigate({ context, group: null, pageId: null, reader: false });
      announce(t("scene.lateralJump", { label: contextStyle(context).label }));
    },
    [announce, navigate]
  );

  // Full keyboard scheme — the accessibility requirement and the game-feel
  // backbone. Global keys guard against typing contexts.
  useEffect(() => {
    const isTypingTarget = (target: EventTarget | null) => {
      const element = target as HTMLElement | null;
      if (!element) return false;
      if (element.tagName === "INPUT" || element.tagName === "TEXTAREA" || element.tagName === "SELECT") return true;
      return Boolean(element.isContentEditable || element.closest?.(".pageReader"));
    };
    const onKey = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) return;
      if (globalSceneShortcutsBlocked()) return;
      // Browser/system shortcuts stay untouched (Cmd/Ctrl+R, Cmd+1..9, Cmd+W).
      if (event.metaKey || event.ctrlKey) return;
      if (event.altKey && !(event.key === "ArrowLeft")) return;
      const nativeViewKeys: Partial<Record<string, ViewId>> = {
        "1": "quadrants",
        "2": "radar",
        "3": "sources",
        "4": "work"
      };
      const perspectiveKeys: Partial<Record<string, PerspectiveId>> = {
        "1": "radar",
        "2": "atlas",
        "3": "districts",
        "4": "trails",
        "5": "quadrants"
      };
      const nativeView = route.runtimeMode === "v8" ? nativeViewKeys[event.key] : undefined;
      const compatibilityPerspective = route.runtimeMode !== "v8" ? perspectiveKeys[event.key] : undefined;
      if (nativeView || compatibilityPerspective) {
        event.preventDefault();
        if (nativeView) navigate({ view: nativeView });
        else if (compatibilityPerspective) navigate({ perspective: compatibilityPerspective });
        return;
      }
      if (event.key === "/") {
        event.preventDefault();
        onFocusSearch?.();
        return;
      }
      if (event.key === "Escape") {
        // Universal exit, one layer at a time: reader → plate/lock → level up.
        // (Open docks are closed earlier by the shell's capture handler; the
        // Brief Studio modal owns its own closing — never act under it.)
        if (document.querySelector(".briefStudio")) return;
        if (route.reader) {
          navigate({ reader: false });
          announce(t("scene.readerClosed"));
        } else if (route.pageId) {
          navigate({ pageId: null, reader: false });
          announce(t("scene.selectionReleased"));
        } else {
          onRetreat?.();
          announce(t("scene.levelUp"));
        }
        return;
      }
      if (event.key === "Backspace" || (event.altKey && event.key === "ArrowLeft")) {
        event.preventDefault();
        onHistoryBack?.();
        return;
      }
      if (event.key === "m" || event.key === "M") {
        setMinimapExpanded((value) => !value);
        return;
      }
      if (event.key === "Tab") {
        // Group cycling only owns Tab while the scene itself has focus —
        // HUD buttons, the reader and the 2D fallback keep native tab order.
        const activeElement = document.activeElement as HTMLElement | null;
        const inDom =
          activeElement &&
          activeElement !== document.body &&
          !activeElement.closest?.(".sceneCanvasFrame");
        if (fallback || inDom || layout.groups.length === 0) return;
        event.preventDefault();
        const direction = event.shiftKey ? -1 : 1;
        const next = (focusedGroupIndex + direction + layout.groups.length) % layout.groups.length;
        setFocusedGroupIndex(next);
        setFocusedNodeIndex(-1);
        const group = layout.groups[next];
        announce(t("scene.groupFocus", { label: worldGroupLabel(group.kind, group.labelKey), n: group.count, shown: group.shown }));
        return;
      }
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        const group = layout.groups[focusedGroupIndex] ?? layout.groups[0];
        const members = group?.memberIds?.length ? group.memberIds : layout.nodes.map((node) => node.id);
        if (members.length === 0) return;
        event.preventDefault();
        if (focusedGroupIndex < 0 && layout.groups.length > 0) setFocusedGroupIndex(0);
        const direction = event.key === "ArrowRight" ? 1 : -1;
        const next = (focusedNodeIndex + direction + members.length) % members.length;
        setFocusedNodeIndex(next);
        const node = nodeIndex.get(members[next]);
        if (node) {
          navigate({ pageId: node.id });
          announce(`${node.title}, ${contextStyle(node.context).label}, ${freshnessLabel(node.freshness_state)}`);
        }
        return;
      }
      if ((event.key === "ArrowUp" || event.key === "ArrowDown") && route.perspective === "atlas" && route.pageId) {
        event.preventDefault();
        const parentByChild = new Map<string, string>();
        const childByParent = new Map<string, string>();
        edges.forEach((edge) => {
          if (edge.type !== "moc_parent") return;
          parentByChild.set(edge.source, edge.target);
          if (!childByParent.has(edge.target)) childByParent.set(edge.target, edge.source);
        });
        const key = event.key === "ArrowUp" ? parentByChild.get(route.pageId) : childByParent.get(route.pageId);
        const node = key ? nodeIndex.get(key) : undefined;
        if (node) {
          navigate({ pageId: node.id });
          announce(`${event.key === "ArrowUp" ? t("scene.above") : t("scene.below")}: ${node.title}`);
        }
        return;
      }
      if (event.key === "Enter") {
        if (route.pageId) {
          navigate({ reader: true });
          return;
        }
        const group = layout.groups[focusedGroupIndex];
        if (group) {
          if (focusedNodeIndex >= 0 && group.memberIds[focusedNodeIndex]) {
            const node = nodeIndex.get(group.memberIds[focusedNodeIndex]);
            if (node) selectNode(node);
          } else {
            handleGroupSelect(group);
          }
        }
        return;
      }
      if (route.pageId) {
        if (event.key === "q" || event.key === "Q") navigate({ reader: true });
        if (event.key === "w" || event.key === "W") onTogglePacket?.(route.pageId);
        if ((event.key === "e" || event.key === "E") && route.runtimeMode !== "v8") navigate({ perspective: "trails" });
        if ((event.key === "f" || event.key === "F") && route.runtimeMode !== "v8") navigate({ perspective: "focus" });
        if (event.key === "r" || event.key === "R") onRunRefresh?.();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [
    announce,
    edges,
    fallback,
    focusedGroupIndex,
    focusedNodeIndex,
    handleGroupSelect,
    layout.groups,
    layout.nodes,
    navigate,
    nodeIndex,
    onFocusSearch,
    onHistoryBack,
    onRetreat,
    onRunRefresh,
    onTogglePacket,
    route.pageId,
    route.perspective,
    route.runtimeMode,
    route.reader,
    selectNode
  ]);
  const focusedGroupKey = layout.groups[focusedGroupIndex]?.key ?? "";
  const shellCenterNode = layout.nodes.find((node) => node.isRoot && node.isGroup) ?? layout.nodes.find((node) => node.isRoot);
  const shellVisualGroup =
    shellCenterNode?.isGroup ? shellCenterNode.groupKey || shellCenterNode.groupDrill?.group || shellCenterNode.id : layout.group;
  // Selection is an inspection plate, not a recenter operation. The shell
  // contract must report the explicit world center even while another page is
  // selected/read; otherwise diagnostics and tests reintroduce the old
  // selection-as-center model that the layout no longer uses.
  const shellRealCenter = route.centerId || "";

  // Guide beacon anchor: the step's subject if it exists in this layout, else
  // the root, else a spot in the void above the founding cards. Anchored at
  // the node's TOP POLE — the beacon's CSS raises it in screen space so the
  // pointer arrow touches the subject at every camera angle.
  const guideAnchor = useMemo<[number, number, number]>(() => {
    if (guide?.anchorId) {
      const node = nodeIndex.get(guide.anchorId);
      if (node) return [node.position[0], node.position[1] + Math.max(node.scale, 0.1), node.position[2]];
    }
    const root = layout.nodes.find((node) => node.isRoot);
    if (root) return [root.position[0], root.position[1] + Math.max(root.scale, 0.1), root.position[2]];
    return [0, 2.5, 0.2];
  }, [guide?.anchorId, layout, nodeIndex]);


  return (
    <div
      ref={sceneShellRef}
      className={fallback ? "sceneShell radarShell fallbackMode" : "sceneShell radarShell"}
      data-scene-perspective={layout.perspective}
      data-scene-center={shellRealCenter}
      data-scene-group={shellVisualGroup ?? ""}
      data-scene-level={layout.level}
      data-scene-lens={route.lens ?? ""}
      data-scene-overlay={overlay}
      data-overlay-token-version={SEMANTIC_VISUAL_TOKENS_VERSION}
      data-layout-position-signature={layoutPositionSignature}
      data-strong-attention-count={strongAttentionCount}
      data-scene-quadrant={route.lens ?? route.quadrant ?? ""}
      data-scene-center-has-quadrants={centerHasQuadrants ? "true" : "false"}
      data-scene-source-node-count={sourceNodeCount}
      data-scene-input-node-count={nodes.length}
      data-scene-fallback-reason={fallbackReason ?? ""}
      data-visual-density={visualTuning.density.toFixed(2)}
      data-visual-spacing={visualTuning.spacing.toFixed(2)}
      data-visual-glow={visualTuning.glow.toFixed(2)}
      data-visual-motion={visualTuning.motion.toFixed(2)}
      data-visual-particles={visualTuning.particles ? "on" : "off"}
      data-motion-intent={activeMotionIntent}
      data-motion-duration-ms={activeMotionDurationMs}
      data-motion-sequence={sceneTransition.sequence}
      aria-label={t("scene.relationshipMapAria")}
    >
      <div className="visuallyHidden" aria-live="polite" role="status">
        {announcement}
      </div>
      <output
        ref={performanceOutputRef}
        className="runtimePerformanceOutput visuallyHidden"
        data-testid="runtime-performance"
        data-performance-ready="false"
        aria-hidden="true"
      />
      {fallback ? (
        <>
          {children}
          <SceneFallback
            layout={layout}
            overlay={overlay}
            git={git}
            fallbackReason={fallbackReason!}
            selectedPageId={selectedId}
            highlightedIds={highlightedIds}
            census={census}
            makeHref={hrefFor}
            onNodeSelect={(id) => {
              const node = nodeIndex.get(id);
              if (node) selectNode(node);
              else navigate({ pageId: id, reader: true });
            }}
            onGroupSelect={handleGroupSelect}
            onStarDrill={handleStarDrill}
          />
        </>
      ) : (
        <>
          <div className="sceneCanvasFrame">
            <Canvas
              camera={{ position: [0, 5.2, 8.6], fov: 40 }}
              dpr={profile.dpr}
              frameloop={visualMotion ? "always" : "demand"}
              // Zero-debounce measuring: shrink the window where a late CSS
              // layout could leave the canvas committed at 0×0 (black world).
              resize={{ scroll: false, debounce: 0 }}
              gl={{
                antialias: profile.antialias,
                powerPreference: "high-performance",
                toneMapping: THREE.ACESFilmicToneMapping,
                toneMappingExposure: 1 + visualTuning.contrast * 0.15
              }}
              onPointerMissed={(event) => {
                const target = event.target as HTMLElement | null;
                if (
                  target?.closest?.(
                    ".sceneHtmlLabel, .worldTopStrip, .quadrantCompass, .focusLegend, .worldCommandBar, .worldMissionCard, .pageReader, .packetTray, .worldMinimap, .radarStatusStrip"
                  )
                ) {
                  return;
                }
                if (route.pageId) navigate({ pageId: null, reader: false });
              }}
            >
              <SceneContent
                layout={layout}
                overlay={overlay}
                edges={edges}
                git={git}
                profile={profile}
                selectedId={selectedId}
                highlightedIds={highlightedIds}
                approvalIds={approvalIds}
                focusedGroupKey={focusedGroupKey}
                isolateRelation={isolateRelation}
                walk={walk}
                morph={morph}
                transition={sceneTransition}
                overlayTransition={overlayTransition}
                cameraTravelVia={cameraTravelVia}
                filter={filter}
                motion={visualMotion}
                visualTuning={visualTuning}
                activityLevel={activityLevel}
                weather={weather}
                activeAnchorRecord={activeAnchorRecord}
                activeQuadrant={route.lens || route.quadrant || ""}
                quadrantHomes={quadrantHomes}
                bornIds={bornPageIds}
                missionMarkers={missionMarkers}
                flyToId={flyToPageId}
                readerOpen={route.reader}
                sourceNodeCount={sourceNodeCount}
                performanceWidth={performanceWidth}
                routeUsabilityMs={routeUsabilityMs}
                performanceTelemetry={performanceTelemetry}
                onPerformanceEvidence={publishPerformanceEvidence}
                onMarkerAct={(pageId) => navigate({ pageId, reader: true })}
                onMarkerResolve={onMarkerResolve}
                onMarkerDismiss={onMarkerDismiss}
                onSelect={selectNode}
                onHover={handleHover}
                onGroupSelect={handleGroupSelect}
                onStarDrill={handleStarDrill}
                onBeaconJump={handleBeaconJump}
                onLockRead={() => navigate({ reader: true })}
                onLockPacket={() => route.pageId && onTogglePacket?.(route.pageId)}
                onLockTrails={() => navigate({ perspective: "trails" })}
                onLockClose={() => navigate({ pageId: null, reader: false })}
                onRetreat={() => {
                  onRetreat?.();
                  announce(t("scene.levelUp"));
                }}
              />
              {/* Spatial surfaces — the interface IN the world (R1/R4/R5). */}
              {founding && <FoundingRite {...founding} />}
              {seed && <SeedFlow {...seed} portal={sceneShellRef} rOuter={layout.rOuter} />}
              {guide && <GuideBeacon {...guide} anchor={guideAnchor} />}
            </Canvas>
            <div
              key={`scene-transition-${sceneTransition.sequence}`}
              className={`sceneTransitionCue sceneTransitionCue-${activeMotionIntent}`}
              style={{ animationDuration: `${activeMotionDurationMs}ms` }}
              data-motion-intent={activeMotionIntent}
              data-motion-duration-ms={activeMotionDurationMs}
              data-motion-sequence={sceneTransition.sequence}
              aria-hidden="true"
            />
          </div>
          {children}
          <HoverTooltip hover={hover} anchorInfo={anchorInfo} groups={layout.groups} />
          {/* No data, no instrument: a filter strip over a 1-2 node world is
              noise — census chips earn their place only when there is a crowd
              to filter. */}
          {census.total >= 3 && (
            <StatusStrip census={census} filter={filter} onFilter={(key) => navigate({ filter: key })} />
          )}
          {/* Minimap: persistent overview disc; M or click expands it as an
              instant, motion-free zoom-to-galaxy. Hidden while the reader dock
              is open (the dock would fully cover the disc); M still expands it
              fullscreen over the dock. Suppressed for tiny worlds (no data, no
              instrument). */}
          {layout.nodes.length >= 3 && (!route.reader || minimapExpanded) && (
          <div className={minimapExpanded ? "worldMinimap expanded" : "worldMinimap"} aria-label={t("scene.minimap")}>
            <FallbackPlanView
              layout={layout}
              overlay={overlay}
              selectedPageId={selectedId}
              highlightedIds={highlightedIds}
              onNodeSelect={(id) => {
                const node = nodeIndex.get(id);
                if (node) selectNode(node);
              }}
              onGroupSelect={(group) => {
                setMinimapExpanded(false);
                handleGroupSelect(group);
              }}
              onStarDrill={handleStarDrill}
            />
            <button
              className="minimapToggle"
              onClick={() => setMinimapExpanded((value) => !value)}
              title={minimapExpanded ? t("scene.minimapClose") : t("scene.minimapExpand")}
              type="button"
            >
              {minimapExpanded ? "×" : "M"}
            </button>
          </div>
          )}
        </>
      )}
    </div>
  );
}
