// SystemScene: the navigable 3D knowledge world. The space itself is the
// navigation — drill level is camera altitude bound to the URL, perspectives
// re-arrange the same node identities (MORPH), and reading happens in-world.
// Honest encodings are non-negotiable: hue = context (area), tone = state
// (aging: bleached draft > calm fresh > aged stale > veiled unknown, with
// attention riding on amber emissive/glow/embers), shape = kind, line = typed
// relation; hidden pages are always countable cluster-stars.
//
// The scene's self-contained layers live in src/scene/parts/*; this file keeps
// the shell — route/patch types, Canvas wiring, the keyboard scheme, layout
// requests, morph bookkeeping and the SceneContent composition. Symbols that
// moved are re-exported below so existing import paths keep working.

import { Canvas, useThree } from "@react-three/fiber";
import type { ThreeEvent } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import type { AnchorRecord, GitState, GraphEdge, GraphNode } from "../types";
import { t } from "../data/i18n";
import { contextStyle, edgeStyle, isRawData, trustColor, worldGroupLabel } from "../data/presentation";
import { regionPayloadByKey } from "../data/visualPrimitives";
import { nodeQuadrant, SCENE_FACETS } from "../scene/facets";
import type { QuadrantHomes, SceneFacet } from "../scene/facets";
import { scenePerformanceProfile } from "../scene/layout";
import type { LayoutNode, ScenePerformanceProfile } from "../scene/layout";
import { computeWorldLayout } from "../scene/perspectives";
import type { ClusterStar, PerspectiveId, WorldGroup, WorldLayout, WorldRequest } from "../scene/perspectives";
import { FoundingRite, GuideBeacon, SeedFlow, WorldPlate } from "../scene/spatial";
import type { FoundingSpec, GuideSpec, SeedSpec } from "../scene/spatial";
import { CameraDirector } from "../scene/parts/camera";
import { FallbackPlanView, SceneFallback } from "../scene/parts/fallback";
import { GateRing, ProposalStems, QuadrantPlanes, WorldGuides } from "../scene/parts/guides";
import { HoverTooltip, sceneCensus, StatusStrip } from "../scene/parts/hud";
import type { AnchorHoverInfo, SceneFilter } from "../scene/parts/hud";
import { buildLabelSet, GroupRimPills, NodeLabels } from "../scene/parts/labels";
import { BirthBursts, QuestMarkers } from "../scene/parts/markers";
import type { MissionMarker } from "../scene/parts/markers";
import {
  allowAmbientMotion,
  edgeControlPoint,
  freshnessLabel,
  layoutNodeIndex,
  nodeTrustKey,
  prefersReducedMotion,
  selectSceneEdges,
  shouldUseFallback,
  TRUST_MATERIALS
} from "../scene/parts/materials";
import type { SceneEdge, TrustKey } from "../scene/parts/materials";
import { ClusterStars, GlowSprites, HorizonBeacons, NodeInstances, RingSprites, StarField } from "../scene/parts/nodes";
import type { MorphState } from "../scene/parts/nodes";
import { AmbientDriver, isEvidenceGap, SceneParticles } from "../scene/parts/particles-layer";

// Moved symbols that other files import from this module (WorldView, tests,
// the visual-test mock) stay reachable at their old path via re-exports.
export { canUseWebGL, sceneFallbackPreferred } from "../scene/parts/materials";
export { FallbackPlanView };
export type { AnchorHoverInfo, MissionMarker };

// The guide beacon from the shell's side: WHERE it anchors is a page id — the
// scene resolves it to a live position (fallback: the root, then the void).
export type SceneGuide = Omit<GuideSpec, "anchor"> & { anchorId: string | null };
// The seed flow from the shell's side: the scene supplies the layout radius.
export type SceneSeed = Omit<SeedSpec, "rOuter">;

export type SceneRoute = {
  perspective: PerspectiveId;
  context?: string;
  group?: string;
  pageId?: string;
  centerId?: string;
  reader: boolean;
  filter: string;
  quadrant?: string;
};

export type ScenePatch = {
  perspective?: PerspectiveId;
  context?: string | null;
  group?: string | null;
  pageId?: string | null;
  reader?: boolean;
  filter?: string | null;
  quadrant?: string | null;
};

export type RelationIsolation = "hierarquia" | "evidencia" | "links" | "citado-por";

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

function EdgeArcs({ edges, quality }: { edges: SceneEdge[]; quality: string }) {
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
      control.set(...edgeControlPoint(edge.from.position, edge.to.position, edge.type));
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
      opacity: 0.95,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      toneMapped: false
    });
    return { lines: new THREE.LineSegments(geometry, material), geometry, material };
  }, [edges, quality]);
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

function RouteLine({ route, color = "#dff8ff" }: { route: LayoutNode[]; color?: string }) {
  const { invalidate } = useThree();
  const object = useMemo(() => {
    if (route.length < 2) return null;
    const points = route.map((node) => new THREE.Vector3(...node.position));
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.9, toneMapped: false });
    return { line: new THREE.Line(geometry, material), geometry, material };
  }, [color, route]);
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

// The target-lock ring was replaced by the WorldPlate (scene/spatial.tsx): the
// first reading level is an anchored SUMMARY at the node — the full reader is
// a chosen second step. Q/W/E/R keys keep working via the keyboard scheme.

// ---------------------------------------------------------------------------

function SceneContent({
  layout,
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
  filter,
  motion,
  activityLevel,
  weather,
  activeQuadrant,
  quadrantHomes,
  bornIds,
  missionMarkers,
  flyToId,
  readerOpen,
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
  onLockClose
}: {
  layout: WorldLayout;
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
  filter: SceneFilter | null;
  motion: boolean;
  activityLevel: number;
  weather?: string;
  activeQuadrant?: string;
  quadrantHomes?: QuadrantHomes;
  bornIds?: string[];
  missionMarkers?: MissionMarker[];
  flyToId?: string;
  readerOpen: boolean;
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

  const sceneEdges = useMemo(
    () => selectSceneEdges(edges, layout, focusIds, highlightedIds, profile, isolateRelation, selectedKeys),
    [edges, focusIds, highlightedIds, isolateRelation, layout, profile, selectedKeys]
  );
  const flowEdges = useMemo(() => {
    const attention = (node: LayoutNode) =>
      node.freshness_state === "stale" || node.approved_state === "proposal" || node.risk_flags.length > 0;
    return sceneEdges.filter((edge) => {
      if (edge.type === "markdown_link") return edge.emphasis >= 1;
      if (edge.emphasis >= 1) return true;
      if (edge.type === "ingestion_chain" || edge.type === "pr_impact") return attention(edge.from) || attention(edge.to);
      return false;
    });
  }, [sceneEdges]);
  const route = useMemo(() => mocParentRoute(edges, layout, selectedId), [edges, layout, selectedId]);
  const labels = useMemo(() => buildLabelSet(layout, highlightedIds, selectedId, 14), [highlightedIds, layout, selectedId]);

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
  const lockedNode = useMemo(() => {
    if (!selectedId) return null;
    const index = layoutNodeIndex(layout);
    return index.get(selectedId) ?? null;
  }, [layout, selectedId]);

  // Weather atmosphere — a SUBTLE tint of the base void, driven by the same
  // honest computeCondition() signal the Condition strip prints in exact counts
  // (so it implies no data the strip doesn't already name). Clear = neutral.
  const sky = WEATHER_SKY[weather ?? "clear"] ?? WEATHER_SKY.clear;
  return (
    <>
      <color attach="background" args={[sky]} />
      <fogExp2 attach="fog" args={[sky, 0.032]} />
      <hemisphereLight args={["#1a3040", "#05080c", 0.5]} />
      <directionalLight position={[4, 6, 3]} intensity={1.2} color="#cfeaff" />
      <StarField quality={profile.quality} />
      {/* No data, no instrument: the EMPTY world is a pure void — no rings,
          no wedges, no gate torus. The founding rite is its only interface. */}
      {layout.nodes.length > 0 && <WorldGuides layout={layout} />}
      {layout.nodes.length > 0 && layout.level === 0 && <GateRing git={git} />}
      <ProposalStems nodes={layout.nodes} />
      <EdgeArcs edges={sceneEdges} quality={profile.quality} />
      <RouteLine route={route} />
      {walkRoute.length > 1 && <RouteLine route={walkRoute} color={edgeStyle("source_ref").color} />}
      <NodeInstances
        nodes={layout.nodes.filter((node) => !node.isRoot)}
        profile={profile}
        selectedId={selectedId}
        morph={morph}
        dimTest={dimTest}
        onSelect={onSelect}
        onHover={handleHover}
        registerMaterial={registerMaterial}
      />
      {rootNode && (
        <mesh
          ref={rootRef}
          position={rootNode.position}
          scale={rootNode.scale}
          frustumCulled={false}
          onClick={(event) => {
            event.stopPropagation();
            onSelect(rootNode);
          }}
          onPointerMove={(event) => handleHover(rootNode, event)}
          onPointerOut={() => handleHover(null)}
        >
          <sphereGeometry args={[1, profile.geometrySegments + 8, profile.geometrySegments + 8]} />
          <meshStandardMaterial
            color={trustColor("root")}
            emissive={trustColor("root")}
            emissiveIntensity={TRUST_MATERIALS.root.emissiveIntensity}
            roughness={0.3}
            toneMapped={false}
          />
        </mesh>
      )}
      {layout.perspective === "quadrants" && (
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
      <GlowSprites nodes={layout.nodes} highlightedIds={highlightedIds} approvalIds={approvalIds} selectedId={selectedId} walkTargetId={walkTargetId} registerPulse={registerPulse} />
      {bornIds && bornIds.length > 0 && <BirthBursts nodes={layout.nodes} bornIds={bornIds} />}
      <RingSprites nodes={layout.nodes} />
      <SceneParticles layout={layout} flowEdges={flowEdges} activityLevel={activityLevel} quality={profile.quality} motion={motion} showGaps={filter === "unsourced"} />
      <NodeLabels labels={labels} selectedId={selectedId} />
      <GroupRimPills groups={layout.groups} focusedGroupKey={focusedGroupKey} onGroupSelect={onGroupSelect} />
      <ClusterStars stars={layout.clusterStars} onDrill={onStarDrill} />
      <HorizonBeacons beacons={layout.beacons} onJump={onBeaconJump} />
      {/* R7 — two-level reading: the locked node shows its SUMMARY plate in
          place; the full reader (a dock) is the chosen second step and hides
          the plate while open. */}
      {lockedNode && !readerOpen && (
        <WorldPlate node={lockedNode} onOpen={onLockRead} onTrails={onLockTrails} onPacket={onLockPacket} onClose={onLockClose} />
      )}
      <CameraDirector
        layout={layout}
        lockedNode={lockedNode}
        flyToNode={flyToId ? layoutNodeIndex(layout).get(flyToId) ?? null : null}
        enableIntro={profile.enableIntro}
        motion={motion}
      />
      <AmbientDriver enabled={motion} rootRef={rootRef} pulses={pulses} />
    </>
  );
}

// ---------------------------------------------------------------------------

const NO_EDGES: GraphEdge[] = [];
const NO_IDS: string[] = [];

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
  bornPageIds,
  missionMarkers,
  flyToPageId,
  anchorInfo,
  activeAnchorRecord,
  quadrantHomes,
  founding = null,
  seed = null,
  guide = null,
  onMarkerResolve,
  onMarkerDismiss,
  onNavigate,
  onRetreat,
  onFocusSearch,
  onTogglePacket,
  onRunRefresh,
  makeHref,
  children
}: {
  nodes: GraphNode[];
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
  bornPageIds?: string[];
  missionMarkers?: MissionMarker[];
  flyToPageId?: string;
  anchorInfo?: Record<string, AnchorHoverInfo>;
  activeAnchorRecord?: AnchorRecord | null;
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
  onFocusSearch?: () => void;
  onTogglePacket?: (nodeId: string) => void;
  onRunRefresh?: () => void;
  makeHref?: (patch: ScenePatch) => string;
  children?: React.ReactNode;
}) {
  const [fallback, setFallback] = useState(shouldUseFallback);
  const [motion, setMotion] = useState(allowAmbientMotion);
  const profile = useSceneProfile(nodes.length);
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
      quadrant: (route.quadrant || undefined) as WorldRequest["quadrant"],
      quadrantHomes,
      nodes,
      edges,
      maxNodes: Math.min(profile.maxNodes + revealBoost, 480),
      snapshotAt
    }),
    [
      edges,
      nodes,
      profile.maxNodes,
      quadrantHomes,
      revealBoost,
      route.centerId,
      route.context,
      route.group,
      route.pageId,
      route.perspective,
      route.quadrant,
      snapshotAt
    ]
  );
  const rawLayout = useWorldLayout(request);
  const layout = useMemo<WorldLayout>(() => {
    const regions = regionPayloadByKey(activeAnchorRecord);
    if (regions.size === 0) return rawLayout;
    return {
      ...rawLayout,
      groups: rawLayout.groups.map((group) => {
        const region = regions.get(group.labelKey) ?? regions.get(group.key);
        if (!region) return group;
        return {
          ...group,
          count: region.summary.total,
          shown: Math.min(group.shown, region.summary.total),
          memberIds: region.member_ids,
          region
        };
      })
    };
  }, [activeAnchorRecord, rawLayout]);
  const [hover, setHover] = useState<{ node: LayoutNode; x: number; y: number } | null>(null);
  const [focusedGroupIndex, setFocusedGroupIndex] = useState<number>(-1);
  const [focusedNodeIndex, setFocusedNodeIndex] = useState<number>(-1);
  const [minimapExpanded, setMinimapExpanded] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const highlightedIds = useMemo(() => new Set(highlightedPageIds), [highlightedPageIds]);
  const approvalIds = useMemo(() => new Set(approvalPageIds), [approvalPageIds]);
  const census = useMemo(() => sceneCensus(nodes, edges, layout), [edges, layout, nodes]);
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

  const navigate = useCallback((patch: ScenePatch) => onNavigate?.(patch), [onNavigate]);
  const hrefFor = useCallback((patch: ScenePatch) => (makeHref ? makeHref(patch) : "#"), [makeHref]);

  // MORPH bookkeeping: remember the previous layout's positions so nodes keep
  // identity and glide between perspectives/levels; cut under reduced motion.
  const morph = useRef<MorphState>({ from: new Map(), start: null, duration: 0.8, active: false });
  const previousLayout = useRef<WorldLayout | null>(null);
  useMemo(() => {
    // Idempotent under StrictMode double-invoke: same layout = no-op.
    if (previousLayout.current === layout) return null;
    const previous = previousLayout.current;
    if (previous && previous !== layout && motion) {
      const from = new Map<string, [number, number, number]>();
      previous.nodes.forEach((node) => from.set(node.id, node.position));
      const changedShape = previous.perspective !== layout.perspective || previous.level !== layout.level;
      morph.current = {
        from,
        start: null,
        duration: changedShape ? 0.8 : 0.45,
        active: from.size > 0
      };
    } else {
      morph.current = { from: new Map(), start: null, duration: 0.8, active: false };
    }
    previousLayout.current = layout;
    return null;
  }, [layout, motion]);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => {
      setFallback(shouldUseFallback());
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
      // R7: a click LOCKS the node and shows its summary plate in place — the
      // full reader is a chosen second step (Enter/Q or the plate's Open).
      // The 2D fallback has no plates, so there a click opens the reader
      // directly — otherwise selecting would show nothing at all.
      navigate(fallback ? { pageId: node.id, reader: true } : { pageId: node.id });
      announce(`${node.title}, ${contextStyle(node.context).label}, ${freshnessLabel(node.freshness_state)}`);
    },
    [announce, fallback, navigate]
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
          context: null,
          group: null,
          quadrant: group.labelKey,
          pageId: null,
          reader: false
        });
        announce(t("scene.groupFocus", { label: worldGroupLabel(group.kind, group.labelKey), n: group.count, shown: group.shown }));
        return;
      }
      if (group.drill) {
        navigate({ context: group.drill.context ?? null, group: group.drill.group ?? null, pageId: null, reader: false });
        announce(t("scene.opening", { label: worldGroupLabel(group.kind, group.labelKey), n: group.count }));
        return;
      }
      const groupIndex = layout.groups.findIndex((item) => item.key === group.key);
      setFocusedGroupIndex(groupIndex);
      setFocusedNodeIndex(-1);
      announce(t("scene.groupFocus", { label: worldGroupLabel(group.kind, group.labelKey), n: group.count, shown: group.shown }));
    },
    [announce, layout.groups, navigate]
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
      navigate({
        context: star.drill.context ?? route.context ?? null,
        group: star.drill.group ?? null,
        pageId: null,
        reader: false
      });
      announce(t("scene.openingHidden", { n: star.count, label: worldGroupLabel(star.kind, star.labelKey) }));
    },
    [announce, navigate, route.context]
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
      // Browser/system shortcuts stay untouched (Cmd/Ctrl+R, Cmd+1..9, Cmd+W).
      if (event.metaKey || event.ctrlKey) return;
      if (event.altKey && !(event.key === "ArrowLeft")) return;
      const perspectiveKeys: Record<string, PerspectiveId> = { "1": "radar", "2": "atlas", "3": "districts", "4": "trails", "5": "quadrants" };
      if (perspectiveKeys[event.key]) {
        navigate({ perspective: perspectiveKeys[event.key] });
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
        window.history.back();
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
          } else if (group.drill) {
            handleGroupSelect(group);
          }
        }
        return;
      }
      if (route.pageId) {
        if (event.key === "q" || event.key === "Q") navigate({ reader: true });
        if (event.key === "w" || event.key === "W") onTogglePacket?.(route.pageId);
        if (event.key === "e" || event.key === "E") navigate({ perspective: "trails" });
        if (event.key === "f" || event.key === "F") navigate({ perspective: "focus" });
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
    onRetreat,
    onRunRefresh,
    onTogglePacket,
    route.pageId,
    route.perspective,
    route.reader,
    selectNode
  ]);
  const focusedGroupKey = layout.groups[focusedGroupIndex]?.key ?? "";

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
    <div className={fallback ? "sceneShell radarShell fallbackMode" : "sceneShell radarShell"} aria-label="Content relationship map">
      <div className="visuallyHidden" aria-live="polite" role="status">
        {announcement}
      </div>
      {fallback ? (
        <>
          {children}
          <SceneFallback
            layout={layout}
            git={git}
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
              frameloop={motion ? "always" : "demand"}
              // Zero-debounce measuring: shrink the window where a late CSS
              // layout could leave the canvas committed at 0×0 (black world).
              resize={{ scroll: false, debounce: 0 }}
              gl={{
                antialias: profile.quality !== "compact",
                powerPreference: "high-performance",
                toneMapping: THREE.ACESFilmicToneMapping,
                toneMappingExposure: 1.15
              }}
              onPointerMissed={(event) => {
                const target = event.target as HTMLElement | null;
                if (
                  target?.closest?.(
                    ".sceneHtmlLabel, .worldTopStrip, .worldCommandBar, .worldMissionCard, .pageReader, .packetTray, .worldMinimap, .radarStatusStrip"
                  )
                ) {
                  return;
                }
                if (route.pageId) navigate({ pageId: null, reader: false });
              }}
            >
              <SceneContent
                layout={layout}
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
                filter={filter}
                motion={motion}
                activityLevel={activityLevel}
                weather={weather}
                activeQuadrant={route.quadrant || ""}
                quadrantHomes={quadrantHomes}
                bornIds={bornPageIds}
                missionMarkers={missionMarkers}
                flyToId={flyToPageId}
                readerOpen={route.reader}
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
              />
              {/* Spatial surfaces — the interface IN the world (R1/R4/R5). */}
              {founding && <FoundingRite {...founding} />}
              {seed && <SeedFlow {...seed} rOuter={layout.rOuter} />}
              {guide && <GuideBeacon {...guide} anchor={guideAnchor} />}
            </Canvas>
          </div>
          {children}
          <HoverTooltip hover={hover} anchorInfo={anchorInfo} />
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
              selectedPageId={selectedId}
              highlightedIds={highlightedIds}
              onNodeSelect={(id) => {
                const node = nodeIndex.get(id);
                if (node) selectNode(node);
              }}
              onContextSelect={(context) => {
                setMinimapExpanded(false);
                navigate({ context, group: null, pageId: null, reader: false });
              }}
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
