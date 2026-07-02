// SystemScene: the navigable 3D knowledge world. The space itself is the
// navigation — drill level is camera altitude bound to the URL, perspectives
// re-arrange the same node identities (MORPH), and reading happens in-world.
// Honest encodings are non-negotiable: color = trust, shape = kind,
// line = typed relation; hidden pages are always countable cluster-stars.

import { Html, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import type { ThreeEvent } from "@react-three/fiber";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type { GraphEdge, GraphNode, GitState } from "../types";
import { t } from "../data/i18n";
import { agedColor, contextStyle, edgeStyle, isRawData, pageTypeLabel, pageTypeStyle, trustColor, worldGroupLabel } from "../data/presentation";
import { glowTexture, ringTexture } from "../scene/glow";
import { scenePerformanceProfile } from "../scene/layout";
import type { LayoutNode, ScenePerformanceProfile } from "../scene/layout";
import { computeWorldLayout, worldLevel } from "../scene/perspectives";
import type { Beacon, ClusterStar, PerspectiveId, WorldGroup, WorldLayout, WorldRequest } from "../scene/perspectives";
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
} from "../scene/particles";
import type { FlowEdgeInput } from "../scene/particles";

export function canUseWebGL(): boolean {
  if (typeof document === "undefined") return false;
  const canvas = document.createElement("canvas");
  try {
    return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function isVisualTestMode(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("visual") === "1";
}

function shouldUseFallback(): boolean {
  return isVisualTestMode() || prefersReducedMotion() || !canUseWebGL();
}

function allowAmbientMotion(): boolean {
  if (isVisualTestMode() || prefersReducedMotion()) return false;
  if (typeof document !== "undefined" && document.visibilityState === "hidden") return false;
  return true;
}

function freshnessLabel(state: string): string {
  if (state === "fresh") return t("trust.ok");
  if (state === "stale") return t("trust.needsRefresh");
  return t("trust.notChecked");
}

function workspaceLabel(git: GitState): string {
  if (git.proposal.is_proposal_branch) return git.proposal.theme ? `review: ${git.proposal.theme}` : "review workspace";
  if (git.current_branch === git.default_branch) return "approved workspace";
  return "current workspace";
}

export type SceneRoute = {
  perspective: PerspectiveId;
  context?: string;
  group?: string;
  pageId?: string;
  reader: boolean;
  filter: string;
};

export type ScenePatch = {
  perspective?: PerspectiveId;
  context?: string | null;
  group?: string | null;
  pageId?: string | null;
  reader?: boolean;
  filter?: string | null;
};

export type RelationIsolation = "hierarquia" | "evidencia" | "links" | "citado-por";

type TrustKey = "fresh" | "stale" | "unknown" | "proposal";

function nodeTrustKey(node: Pick<LayoutNode, "approved_state" | "freshness_state">): TrustKey {
  if (node.approved_state === "proposal") return "proposal";
  if (node.freshness_state === "fresh") return "fresh";
  if (node.freshness_state === "stale") return "stale";
  return "unknown";
}

// State → material treatment. Since the re-encoding, the node BODY hue is the
// context identity (per-instance colors, see InstancedNodeMesh); this table
// keeps what per-instance attributes cannot express: per-state emissive
// (attention glows — amber heat for stale, purple for drafts), opacity (the
// unknown veil) and the glow-sprite gate. Salience inversion survives: fresh
// bodies sit in a calm lightness band with no emissive; problems radiate.
const TRUST_MATERIALS: Record<TrustKey | "root", { emissiveIntensity: number; opacity: number; glows: boolean }> = {
  fresh: { emissiveIntensity: 0.05, opacity: 1, glows: false },
  stale: { emissiveIntensity: 1.1, opacity: 1, glows: true },
  proposal: { emissiveIntensity: 1.0, opacity: 1, glows: true },
  unknown: { emissiveIntensity: 0, opacity: 0.6, glows: false },
  root: { emissiveIntensity: 0.9, opacity: 1, glows: true }
};

function trustMaterial(node: LayoutNode) {
  if (node.isRoot) return TRUST_MATERIALS.root;
  return TRUST_MATERIALS[nodeTrustKey(node)];
}

// Hue = context (who the node is), tone = state (how it is): the aged context
// accent. Used by every 2D twin of the 3D body (minimap dots, fallback chips).
function nodeDisplayColor(node: LayoutNode): string {
  if (node.isRoot) return trustColor("root");
  return agedColor(contextStyle(node.context).accent, nodeTrustKey(node));
}

// State ANNOTATION color (glow sprites, chips, guides): the trust palette
// survives as the state accent language even though it no longer paints
// node bodies.
function trustDisplayColor(node: LayoutNode): string {
  if (node.isRoot) return trustColor("root");
  return trustColor(nodeTrustKey(node));
}

type SuperShape = "sphere" | "crystal" | "hub";

function superShape(pageType: string): SuperShape {
  const style = pageTypeStyle(pageType);
  if (style.shape === "crystal" || style.shape === "diamond") return "crystal";
  if (style.shape === "hub") return "hub";
  if (style.family === "source") return "crystal";
  if (style.family === "hub" || style.family === "root") return "hub";
  return "sphere";
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

function layoutNodeIndex(layout: WorldLayout): Map<string, LayoutNode> {
  const index = new Map<string, LayoutNode>();
  layout.nodes.forEach((node) => {
    index.set(node.id, node);
    index.set(node.path, node);
  });
  return index;
}

// ---------------------------------------------------------------------------
// Edges

const EDGE_PRIORITY: Record<string, number> = {
  pr_impact: 5,
  ingestion_chain: 4,
  source_ref: 3,
  moc_parent: 2,
  markdown_link: 1
};

const EDGE_REST_OPACITY: Record<string, number> = {
  pr_impact: 0.9,
  ingestion_chain: 0.8,
  source_ref: 0.42,
  moc_parent: 0.18,
  markdown_link: 0
};

type SceneEdge = {
  from: LayoutNode;
  to: LayoutNode;
  type: string;
  emphasis: number;
};

function edgeEmphasis(
  edge: { from: LayoutNode; to: LayoutNode; type: string },
  focusIds: Set<string>,
  highlightedIds: Set<string>,
  quality: string,
  mocEmphasis: boolean
): number {
  const touchesFocus =
    focusIds.size > 0 && [edge.from.id, edge.from.path, edge.to.id, edge.to.path].some((key) => focusIds.has(key));
  const insideHighlight =
    highlightedIds.size > 0 &&
    (highlightedIds.has(edge.from.id) || highlightedIds.has(edge.from.path)) &&
    (highlightedIds.has(edge.to.id) || highlightedIds.has(edge.to.path));
  if (touchesFocus) return edge.type === "markdown_link" ? 0.65 : 1;
  if (insideHighlight && edge.type === "pr_impact") return 1;
  let rest = EDGE_REST_OPACITY[edge.type] ?? 0.3;
  // Atlas raises the solid hierarchy web — it IS the perspective.
  if (mocEmphasis && edge.type === "moc_parent") rest = 0.55;
  const ambient = edge.type === "markdown_link" ? (quality === "rich" ? 0.08 : 0) : rest;
  return focusIds.size > 0 ? ambient * 0.25 : ambient;
}

function relationEdgeMatch(relation: RelationIsolation, edge: GraphEdge, selectedKeys: Set<string>): boolean {
  const fromSelected = selectedKeys.has(edge.source);
  const toSelected = selectedKeys.has(edge.target);
  if (!fromSelected && !toSelected) return false;
  if (relation === "hierarquia") return edge.type === "moc_parent";
  if (relation === "evidencia") return edge.type === "source_ref" || edge.type === "ingestion_chain";
  if (relation === "links") return edge.type === "markdown_link" && fromSelected;
  return edge.type === "markdown_link" && toSelected;
}

function selectSceneEdges(
  edges: GraphEdge[],
  layout: WorldLayout,
  focusIds: Set<string>,
  highlightedIds: Set<string>,
  profile: ScenePerformanceProfile,
  isolateRelation: RelationIsolation | null,
  selectedKeys: Set<string>
): SceneEdge[] {
  const index = layoutNodeIndex(layout);
  const mapped: (SceneEdge & { sortKey: string })[] = [];
  for (const edge of edges) {
    const from = index.get(edge.source);
    const to = index.get(edge.target);
    if (!from || !to || from.id === to.id) continue;
    if (isolateRelation && selectedKeys.size > 0) {
      if (!relationEdgeMatch(isolateRelation, edge, selectedKeys)) continue;
      mapped.push({ from, to, type: edge.type, emphasis: 1, sortKey: `${edge.source}->${edge.target}:${edge.type}` });
      continue;
    }
    const emphasis = edgeEmphasis(
      { from, to, type: edge.type },
      focusIds,
      highlightedIds,
      profile.quality,
      layout.perspective === "atlas"
    );
    if (emphasis <= 0.01) continue;
    mapped.push({ from, to, type: edge.type, emphasis, sortKey: `${edge.source}->${edge.target}:${edge.type}` });
  }
  return mapped
    .sort(
      (a, b) =>
        Number(b.emphasis >= 1) - Number(a.emphasis >= 1) ||
        (EDGE_PRIORITY[b.type] ?? 0) - (EDGE_PRIORITY[a.type] ?? 0) ||
        b.from.inbound_links + b.to.inbound_links - (a.from.inbound_links + a.to.inbound_links) ||
        a.sortKey.localeCompare(b.sortKey)
    )
    .slice(0, profile.maxEdges);
}

function edgeControlPoint(fromPos: [number, number, number], toPos: [number, number, number], type: string): [number, number, number] {
  const midX = (fromPos[0] + toPos[0]) / 2;
  const midY = (fromPos[1] + toPos[1]) / 2;
  const midZ = (fromPos[2] + toPos[2]) / 2;
  if (type === "markdown_link") {
    return [midX, Math.min(fromPos[1], toPos[1]) - 0.35, midZ];
  }
  const distance = Math.hypot(fromPos[0] - toPos[0], fromPos[1] - toPos[1], fromPos[2] - toPos[2]);
  return [midX, midY + 0.12 + distance * 0.05, midZ];
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

// ---------------------------------------------------------------------------
// Reference geometry

function circlePoints(radius: number, segments = 96, y = 0): THREE.Vector3[] {
  const points: THREE.Vector3[] = [];
  for (let index = 0; index <= segments; index += 1) {
    const angle = (index / segments) * Math.PI * 2;
    points.push(new THREE.Vector3(Math.cos(angle) * radius, y, Math.sin(angle) * radius));
  }
  return points;
}

function arcPoints(radius: number, start: number, end: number, segments = 32, y = 0): THREE.Vector3[] {
  const points: THREE.Vector3[] = [];
  for (let index = 0; index <= segments; index += 1) {
    const angle = start + ((end - start) * index) / segments;
    points.push(new THREE.Vector3(Math.cos(angle) * radius, y, Math.sin(angle) * radius));
  }
  return points;
}

function StaticLine({ points, color, opacity }: { points: THREE.Vector3[]; color: string; opacity: number }) {
  const object = useMemo(() => {
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({ color, transparent: true, opacity, toneMapped: false });
    return { line: new THREE.Line(geometry, material), geometry, material };
  }, [color, opacity, points]);
  useEffect(() => {
    return () => {
      object.geometry.dispose();
      object.material.dispose();
    };
  }, [object]);
  return <primitive object={object.line} />;
}

function WorldGuides({ layout }: { layout: WorldLayout }) {
  const freshness = layout.radial === "freshness";
  const band = layout.rOuter - layout.rInner;
  const deadlineRadius = layout.rInner + band * layout.deadlineF;
  const captionWedge = [...layout.wedges].sort(
    (a, b) => b.endAngle - b.startAngle - (a.endAngle - a.startAngle) || a.context.localeCompare(b.context)
  )[0];
  return (
    <group>
      {layout.guides.map((guide, index) => {
        if (guide.kind === "circle") {
          return <StaticLine key={`guide-${index}`} points={circlePoints(guide.radius)} color={guide.color} opacity={guide.opacity} />;
        }
        if (guide.kind === "arc") {
          return (
            <StaticLine
              key={`guide-${index}`}
              points={arcPoints(guide.radius, guide.start, guide.end, 28)}
              color={guide.color}
              opacity={guide.opacity}
            />
          );
        }
        return (
          <StaticLine
            key={`guide-${index}`}
            points={[
              new THREE.Vector3(Math.cos(guide.angle) * guide.r0, 0, Math.sin(guide.angle) * guide.r0),
              new THREE.Vector3(Math.cos(guide.angle) * guide.r1, 0, Math.sin(guide.angle) * guide.r1)
            ]}
            color={guide.color}
            opacity={guide.opacity}
          />
        );
      })}
      {freshness && (
        <>
          {/* Danger zone: translucent amber past the deadline arc. */}
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.03, 0]}>
            <ringGeometry args={[deadlineRadius, layout.rOuter, 96]} />
            <meshBasicMaterial
              color={trustColor("stale")}
              transparent
              opacity={0.045}
              blending={THREE.AdditiveBlending}
              depthWrite={false}
              toneMapped={false}
              side={THREE.DoubleSide}
            />
          </mesh>
          {[layout.rInner, layout.rInner + band * 0.33, layout.rInner + band, layout.rOuter + 0.02].map((radius) => (
            <StaticLine key={`grid-${radius}`} points={circlePoints(radius)} color="#22303a" opacity={0.28} />
          ))}
          {/* Discrete "sem dados" band: unknown freshness lives here — radius
              never fakes a date that does not exist. */}
          {layout.unknownR !== null && (
            <>
              <StaticLine points={circlePoints(layout.unknownR)} color={trustColor("unknown")} opacity={0.3} />
              <Html
                position={[Math.cos(0.35) * (layout.unknownR + 0.1), 0.04, Math.sin(0.35) * (layout.unknownR + 0.1)]}
                center
                distanceFactor={5.2}
                wrapperClass="sceneHtmlLabel"
                className="radarDeadlineCaption"
                zIndexRange={[20, 0]}
              >
                <span>{t("scene.unknownBand")}</span>
              </Html>
            </>
          )}
          {captionWedge && (
            <Html
              position={[
                Math.cos(captionWedge.centerAngle) * (deadlineRadius + 0.12),
                0.04,
                Math.sin(captionWedge.centerAngle) * (deadlineRadius + 0.12)
              ]}
              center
              distanceFactor={5.2}
              wrapperClass="sceneHtmlLabel"
              className="radarDeadlineCaption"
              zIndexRange={[20, 0]}
            >
              <span>{t("scene.deadlineCaption")}</span>
            </Html>
          )}
        </>
      )}
      {layout.wedges.map((wedge) => (
        <group key={`wedge-${wedge.context}`}>
          <StaticLine
            points={[
              new THREE.Vector3(Math.cos(wedge.startAngle) * layout.rInner, 0, Math.sin(wedge.startAngle) * layout.rInner),
              new THREE.Vector3(Math.cos(wedge.startAngle) * layout.rOuter, 0, Math.sin(wedge.startAngle) * layout.rOuter)
            ]}
            color="#22303a"
            opacity={0.18}
          />
          {freshness && (
            <StaticLine
              points={arcPoints(layout.rInner + band * layout.deadlineF, wedge.startAngle + 0.02, wedge.endAngle - 0.02, 28)}
              color={trustColor("stale")}
              opacity={0.4}
            />
          )}
          <StaticLine
            points={arcPoints(layout.rOuter + 0.2, wedge.startAngle + 0.015, wedge.endAngle - 0.015, 32)}
            color={layout.wedgeKind === "context" ? contextStyle(wedge.context).accent : "#4f8fb5"}
            opacity={0.65}
          />
        </group>
      ))}
    </group>
  );
}

function ProposalStems({ nodes }: { nodes: LayoutNode[] }) {
  const stems = nodes.filter((node) => node.position[1] > 0.05);
  return (
    <group>
      {stems.map((node) => (
        <StaticLine
          key={`stem-${node.id}`}
          points={[new THREE.Vector3(node.position[0], 0, node.position[2]), new THREE.Vector3(...node.position)]}
          color={trustColor("proposal")}
          opacity={0.5}
        />
      ))}
    </group>
  );
}

function GateRing({ git }: { git: GitState }) {
  const color = git.proposal.is_proposal_branch ? trustColor("proposal") : trustColor("root");
  return (
    <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, -0.01, 0]}>
      <torusGeometry args={[1.05, 0.02, 12, 96]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.8} toneMapped={false} />
    </mesh>
  );
}

// ---------------------------------------------------------------------------
// Nodes: instanced by (shape, trust, dimmed) with MORPH tweening — nodes keep
// their identity across perspective switches and glide to new positions.

type NodeGroup = {
  key: string;
  shape: SuperShape;
  material: (typeof TRUST_MATERIALS)[TrustKey | "root"];
  trust: TrustKey | "root";
  dimmed: boolean;
  items: LayoutNode[];
};

type MorphState = {
  from: Map<string, [number, number, number]>;
  start: number | null;
  duration: number;
  active: boolean;
};

function easeOutCubic(t: number): number {
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

function NodeInstances({
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

function ClusterStars({ stars, onDrill }: { stars: ClusterStar[]; onDrill: (star: ClusterStar) => void }) {
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

function HorizonBeacons({ beacons, onJump }: { beacons: Beacon[]; onJump: (context: string) => void }) {
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

// ---------------------------------------------------------------------------
// Glow, rings, starfield, labels

function GlowSprites({
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

function RingSprites({ nodes }: { nodes: LayoutNode[] }) {
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

function StarField({ quality }: { quality: string }) {
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

type SceneLabel = {
  node: LayoutNode;
  annotation: string | null;
  annotationColor: string | null;
};

function buildLabelSet(layout: WorldLayout, highlightedIds: Set<string>, selectedId: string, budget: number): SceneLabel[] {
  const seen = new Set<string>();
  const labels: SceneLabel[] = [];
  const push = (node: LayoutNode | undefined, annotation: string | null, annotationColor: string | null) => {
    if (!node || seen.has(node.id)) return;
    seen.add(node.id);
    labels.push({ node, annotation, annotationColor });
  };
  const byOverdue = [...layout.nodes].sort((a, b) => b.overdueRatio - a.overdueRatio || a.title.localeCompare(b.title));

  push(layout.nodes.find((node) => node.isRoot), null, null);
  if (selectedId) push(layout.nodes.find((node) => node.id === selectedId || node.path === selectedId), null, null);

  const candidates: SceneLabel[] = [];
  for (const node of byOverdue) {
    if (node.risk_flags.length > 0) {
      candidates.push({ node, annotation: node.risk_flags[0].replaceAll("_", " "), annotationColor: trustColor("risk") });
    }
  }
  for (const node of byOverdue) {
    if (node.freshness_state === "stale") {
      const overdueDays = Math.max(0, Math.round(node.ageDays - node.ageDays / Math.max(node.overdueRatio, 0.01)));
      candidates.push({
        node,
        annotation: node.overdueRatio > 1 ? `${overdueDays}d overdue` : "needs refresh",
        annotationColor: trustColor("stale")
      });
    }
  }
  for (const node of byOverdue) {
    if (node.approved_state === "proposal") {
      candidates.push({ node, annotation: "draft change", annotationColor: trustColor("proposal") });
    }
  }
  let highlightLabels = 0;
  for (const node of layout.nodes) {
    if (highlightLabels >= 4) break;
    if (highlightedIds.has(node.id) || highlightedIds.has(node.path)) {
      candidates.push({ node, annotation: "in review", annotationColor: "#8fd0e8" });
      highlightLabels += 1;
    }
  }
  for (const node of layout.nodes) {
    if (node.isHub && !node.isRoot) candidates.push({ node, annotation: null, annotationColor: null });
  }
  for (const candidate of candidates) {
    if (labels.length >= budget + 2) break;
    push(candidate.node, candidate.annotation, candidate.annotationColor);
  }
  return labels;
}

function NodeLabels({ labels, selectedId }: { labels: SceneLabel[]; selectedId: string }) {
  const tiers = useMemo(() => {
    const buckets = new Map<number, SceneLabel[]>();
    for (const label of labels) {
      const angle = Math.atan2(label.node.position[2], label.node.position[0]);
      const bucket = Math.round(angle / 0.42);
      const list = buckets.get(bucket) ?? [];
      list.push(label);
      buckets.set(bucket, list);
    }
    const tierById = new Map<string, number>();
    for (const list of buckets.values()) {
      list
        .sort(
          (a, b) =>
            Math.hypot(a.node.position[0], a.node.position[2]) - Math.hypot(b.node.position[0], b.node.position[2]) ||
            a.node.id.localeCompare(b.node.id)
        )
        .forEach((label, index) => tierById.set(label.node.id, index));
    }
    return tierById;
  }, [labels]);
  return (
    <group>
      {labels.map(({ node, annotation, annotationColor }) => {
        const selected = node.id === selectedId || node.path === selectedId;
        const lift = node.scale * 1.7 + 0.14 + (tiers.get(node.id) ?? 0) * 0.3;
        return (
          <Html
            key={`label-${node.id}`}
            position={[node.position[0], node.position[1] + lift, node.position[2]]}
            center
            distanceFactor={4}
            className={selected ? "radarLabel selected" : "radarLabel"}
            wrapperClass="sceneHtmlLabel"
            zIndexRange={[30, 0]}
          >
            <span>
              <strong>{node.title}</strong>
              {annotation && <em style={{ color: annotationColor ?? undefined }}>{annotation}</em>}
            </span>
          </Html>
        );
      })}
    </group>
  );
}

// Rim pills: the diegetic group handles. Honest shown/total counts; click
// drills (or cycles focus when the group has no deeper level).
function GroupRimPills({
  groups,
  focusedGroupKey,
  onGroupSelect
}: {
  groups: WorldGroup[];
  focusedGroupKey: string;
  onGroupSelect: (group: WorldGroup) => void;
}) {
  return (
    <group>
      {groups.map((group) => {
        const accent = group.kind === "context" ? contextStyle(group.labelKey).accent : "#4f8fb5";
        const label = worldGroupLabel(group.kind, group.labelKey);
        return (
          <Html key={`rim-${group.key}`} position={group.anchor} center distanceFactor={5.2} wrapperClass="sceneHtmlLabel" className="radarRimPill" zIndexRange={[40, 0]}>
            <button
              style={{ borderColor: accent, pointerEvents: "auto" }}
              className={focusedGroupKey === group.key ? "focused" : undefined}
              onClick={(event) => {
                event.stopPropagation();
                onGroupSelect(group);
              }}
              type="button"
            >
              <strong>{label}</strong>
              <small>{group.shown < group.count ? `${group.shown}/${group.count}` : group.count}</small>
            </button>
          </Html>
        );
      })}
    </group>
  );
}

// Target-lock reticle + Q/W/E/R quick-action ring. Real DOM buttons — the
// diegetic ring and its accessibility twin are the same element.
function TargetLock({
  node,
  onRead,
  onPacket,
  onTrails,
  onRefresh
}: {
  node: LayoutNode;
  onRead: () => void;
  onPacket: () => void;
  onTrails: () => void;
  onRefresh: () => void;
}) {
  return (
    <Html position={node.position} center distanceFactor={4.6} wrapperClass="sceneHtmlLabel" className="targetLock" zIndexRange={[50, 0]}>
      <div className="lockReticle" aria-hidden />
      <div className="lockRing" role="menu" aria-label={t("scene.lock.aria", { title: node.title })}>
        <button className="lockAction lockN" onClick={onRead} type="button" role="menuitem" title={t("scene.lock.readTitle")}>
          {t("scene.lock.read")}
        </button>
        <button className="lockAction lockE" onClick={onPacket} type="button" role="menuitem" title={t("scene.lock.packetTitle")}>
          {t("scene.lock.packet")}
        </button>
        <button className="lockAction lockS" onClick={onTrails} type="button" role="menuitem" title={t("scene.lock.trailsTitle")}>
          {t("scene.lock.trails")}
        </button>
        <button className="lockAction lockW" onClick={onRefresh} type="button" role="menuitem" title={t("scene.lock.refreshTitle")}>
          {t("scene.lock.refresh")}
        </button>
      </div>
    </Html>
  );
}

// ---------------------------------------------------------------------------
// Camera: WARP (drill in), RETREAT (level up), FOCUS (target-lock glide).
// All eased ≤900ms, interruptible by user input; instant under reduced motion.

function CameraDirector({
  layout,
  lockedNode,
  enableIntro,
  motion
}: {
  layout: WorldLayout;
  lockedNode: LayoutNode | null;
  enableIntro: boolean;
  motion: boolean;
}) {
  const { camera, size, invalidate } = useThree();
  const controlsRef = useRef<OrbitControlsImpl | null>(null);
  const animation = useRef<{
    fromTarget: THREE.Vector3;
    toTarget: THREE.Vector3;
    fromDistance: number;
    toDistance: number;
    start: number | null;
    duration: number;
    active: boolean;
  } | null>(null);
  const lastKey = useRef("");

  const fitDistance = useMemo(() => {
    const rLabel = layout.rOuter + 1.1;
    const vFov = (40 * Math.PI) / 180;
    const aspect = size.width / Math.max(size.height, 1);
    const hFov = 2 * Math.atan(Math.tan(vFov / 2) * aspect);
    return (rLabel / Math.sin(Math.min(vFov, hFov) / 2)) * 0.88;
  }, [layout.rOuter, size.height, size.width]);

  useEffect(() => {
    const desiredTarget = lockedNode ? new THREE.Vector3(...lockedNode.position) : new THREE.Vector3(0, 0, 0);
    const desiredDistance = lockedNode ? Math.max(fitDistance * 0.36, 2.6) : fitDistance;
    const key = `${layout.perspective}:${layout.level}:${lockedNode?.id ?? ""}:${fitDistance.toFixed(2)}`;
    if (key === lastKey.current) return;
    const firstFrame = lastKey.current === "";
    lastKey.current = key;

    const controls = controlsRef.current;
    const currentTarget = controls ? controls.target.clone() : new THREE.Vector3(0, 0, 0);
    const currentDistance = camera.position.distanceTo(currentTarget) || fitDistance;

    // FOCUS ~350ms; WARP/RETREAT ~600ms; intro slightly longer glide.
    const duration = !motion ? 0 : lockedNode ? 0.35 : firstFrame && enableIntro ? 0.75 : 0.6;
    animation.current = {
      fromTarget: currentTarget,
      toTarget: desiredTarget,
      fromDistance: firstFrame ? desiredDistance * 1.28 : currentDistance,
      toDistance: desiredDistance,
      start: null,
      duration: Math.max(duration, 0.0001),
      active: true
    };
    if ("fov" in camera) {
      (camera as THREE.PerspectiveCamera).fov = 40;
      (camera as THREE.PerspectiveCamera).updateProjectionMatrix();
    }
    if (!motion) {
      // Reduced motion / test mode: instant CUT.
      const polar = 0.72;
      camera.position.set(
        desiredTarget.x,
        desiredTarget.y + Math.cos(polar) * desiredDistance,
        desiredTarget.z + Math.sin(polar) * desiredDistance
      );
      controls?.target.copy(desiredTarget);
      camera.lookAt(desiredTarget);
      controls?.update();
      animation.current = null;
      invalidate();
    }
    invalidate();
  }, [camera, enableIntro, fitDistance, invalidate, layout.level, layout.perspective, lockedNode, motion]);

  useFrame((state) => {
    const anim = animation.current;
    const controls = controlsRef.current;
    if (!anim?.active || !controls) return;
    if (anim.start === null) anim.start = state.clock.elapsedTime;
    const t = Math.min((state.clock.elapsedTime - anim.start) / anim.duration, 1);
    const eased = easeOutCubic(t);
    const target = anim.fromTarget.clone().lerp(anim.toTarget, eased);
    const distance = THREE.MathUtils.lerp(anim.fromDistance, anim.toDistance, eased);
    // Preserve the user's azimuth; ease the polar toward the mode default.
    const offset = camera.position.clone().sub(controls.target);
    const spherical = new THREE.Spherical().setFromVector3(offset.lengthSq() > 0.0001 ? offset : new THREE.Vector3(0, 1, 1));
    spherical.radius = distance;
    const desiredPolar = anim.toTarget.lengthSq() > 0.01 ? 0.95 : 0.72;
    spherical.phi = THREE.MathUtils.lerp(spherical.phi, desiredPolar, 0.12);
    controls.target.copy(target);
    camera.position.copy(target.clone().add(new THREE.Vector3().setFromSpherical(spherical)));
    camera.lookAt(target);
    controls.update();
    state.invalidate();
    if (t >= 1) anim.active = false;
  });

  return (
    <OrbitControls
      ref={controlsRef}
      enablePan={false}
      minDistance={fitDistance * 0.18}
      maxDistance={fitDistance * 1.6}
      minPolarAngle={0.3}
      maxPolarAngle={1.25}
      enableDamping
      onStart={() => {
        // User input interrupts any camera choreography immediately.
        if (animation.current) animation.current.active = false;
      }}
    />
  );
}

// ---------------------------------------------------------------------------
// Particles + ambient driver

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
function isEvidenceGap(pageType: string, sourceRefCount: number): boolean {
  if (pageType === "root_index" || pageType === "context_hub") return false;
  if (isRawData(pageType)) return false;
  return sourceRefCount === 0;
}

function SceneParticles({
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

function AmbientDriver({
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
  onSelect,
  onHover,
  onGroupSelect,
  onStarDrill,
  onBeaconJump,
  onLockRead,
  onLockPacket,
  onLockTrails,
  onLockRefresh
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
  onSelect: (node: LayoutNode) => void;
  onHover: (node: LayoutNode | null, event?: ThreeEvent<PointerEvent>) => void;
  onGroupSelect: (group: WorldGroup) => void;
  onStarDrill: (star: ClusterStar) => void;
  onBeaconJump: (context: string) => void;
  onLockRead: () => void;
  onLockPacket: () => void;
  onLockTrails: () => void;
  onLockRefresh: () => void;
}) {
  const [hoveredId, setHoveredId] = useState("");
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
      if (filter === "raw") return !isRawData(node.page_type) && !node.isRoot;
      if (filter === "unsourced") return !isEvidenceGap(node.page_type, node.source_ref_count) && !node.isRoot;
      if (filter) return nodeTrustKey(node) !== filter && !node.isRoot;
      if (highlightedIds.size > 0) {
        return !highlightedIds.has(node.id) && !highlightedIds.has(node.path) && !node.isRoot && !node.isHub;
      }
      return false;
    },
    [filter, highlightedIds]
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

  return (
    <>
      <color attach="background" args={["#05090e"]} />
      <fogExp2 attach="fog" args={["#05090e", 0.032]} />
      <hemisphereLight args={["#1a3040", "#05080c", 0.5]} />
      <directionalLight position={[4, 6, 3]} intensity={1.2} color="#cfeaff" />
      <StarField quality={profile.quality} />
      <WorldGuides layout={layout} />
      {layout.level === 0 && <GateRing git={git} />}
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
      <GlowSprites nodes={layout.nodes} highlightedIds={highlightedIds} approvalIds={approvalIds} selectedId={selectedId} walkTargetId={walkTargetId} registerPulse={registerPulse} />
      <RingSprites nodes={layout.nodes} />
      <SceneParticles layout={layout} flowEdges={flowEdges} activityLevel={activityLevel} quality={profile.quality} motion={motion} showGaps={filter === "unsourced"} />
      <NodeLabels labels={labels} selectedId={selectedId} />
      <GroupRimPills groups={layout.groups} focusedGroupKey={focusedGroupKey} onGroupSelect={onGroupSelect} />
      <ClusterStars stars={layout.clusterStars} onDrill={onStarDrill} />
      <HorizonBeacons beacons={layout.beacons} onJump={onBeaconJump} />
      {lockedNode && (
        <TargetLock node={lockedNode} onRead={onLockRead} onPacket={onLockPacket} onTrails={onLockTrails} onRefresh={onLockRefresh} />
      )}
      <CameraDirector layout={layout} lockedNode={lockedNode} enableIntro={profile.enableIntro} motion={motion} />
      <AmbientDriver enabled={motion} rootRef={rootRef} pulses={pulses} />
    </>
  );
}

// ---------------------------------------------------------------------------
// Census + status strip (DOM twin of the trust encodings)

type SceneCensus = {
  trust: { key: TrustKey; label: string; color: string; count: number }[];
  riskCount: number;
  evidenceCount: number;
  unsourcedCount: number;
  rawCount: number;
  contexts: { key: string; label: string; color: string; count: number }[];
  edgeCounts: { key: string; label: string; color: string; count: number }[];
  hidden: number;
  total: number;
};

function sceneCensus(nodes: GraphNode[], edges: GraphEdge[], layout: WorldLayout): SceneCensus {
  const visibleIds = new Set(layout.nodes.map((node) => node.id));
  const visible = nodes.filter((node) => visibleIds.has(node.id));
  const counts = new Map<TrustKey, number>();
  visible.forEach((node) => {
    const key = nodeTrustKey({ approved_state: node.approved_state, freshness_state: node.freshness_state });
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  const trust = (
    [
      { key: "fresh" as const, label: t("scene.trust.fresh") },
      { key: "stale" as const, label: t("scene.trust.stale") },
      { key: "proposal" as const, label: t("scene.trust.proposal") },
      { key: "unknown" as const, label: t("scene.trust.unknown") }
    ]
  )
    .map((entry) => ({ ...entry, color: trustColor(entry.key), count: counts.get(entry.key) || 0 }))
    .filter((entry) => entry.count > 0);
  const edgeCounts = new Map<string, number>();
  edges.forEach((edge) => {
    if (visibleIds.has(edge.source) && visibleIds.has(edge.target)) {
      edgeCounts.set(edge.type, (edgeCounts.get(edge.type) || 0) + 1);
    }
  });
  return {
    trust,
    riskCount: visible.filter((node) => node.risk_flags.length > 0).length,
    evidenceCount: visible.filter((node) => node.metrics.source_ref_count > 0).length,
    unsourcedCount: visible.filter((node) => isEvidenceGap(node.page_type, node.metrics.source_ref_count)).length,
    rawCount: visible.filter((node) => isRawData(node.page_type)).length,
    // Hue = area: the live color legend (Key popover) lists what is on screen.
    contexts: [...visible.reduce((map, node) => {
      const key = node.context || "system";
      map.set(key, (map.get(key) || 0) + 1);
      return map;
    }, new Map<string, number>()).entries()]
      .map(([key, count]) => ({ key, label: contextStyle(key).label, color: contextStyle(key).accent, count }))
      .sort((a, b) => b.count - a.count),
    edgeCounts: [...edgeCounts.entries()]
      .map(([key, count]) => ({ key, label: edgeStyle(key).label, color: edgeStyle(key).color, count }))
      .sort((a, b) => b.count - a.count),
    hidden: layout.totals.hidden,
    total: layout.totals.total
  };
}

type SceneFilter = TrustKey | "raw" | "unsourced";

function StatusStrip({
  census,
  filter,
  onFilter
}: {
  census: SceneCensus;
  filter: SceneFilter | null;
  onFilter: (key: SceneFilter | null) => void;
}) {
  const [keyOpen, setKeyOpen] = useState(false);
  return (
    <div className="radarStatusStrip" aria-label="Map status">
      <span className="stripLabel">{t("misc.filter")}</span>
      {census.trust.map((entry) => (
        <button
          className={filter === entry.key ? "stripChip active" : "stripChip"}
          key={entry.key}
          onClick={() => onFilter(filter === entry.key ? null : entry.key)}
          title={`Show only ${entry.label}`}
          type="button"
        >
          <i style={{ background: entry.color }} />
          {entry.label} {entry.count}
        </button>
      ))}
      {census.riskCount > 0 && (
        <span className="stripChip static">
          <i style={{ background: trustColor("risk") }} />
          {t("scene.risk")} {census.riskCount}
        </span>
      )}
      {census.evidenceCount > 0 && (
        <span className="stripChip static">
          <i style={{ background: edgeStyle("source_ref").color }} />
          {t("scene.evidence")} {census.evidenceCount}
        </span>
      )}
      {census.unsourcedCount > 0 && (
        <button
          className={filter === "unsourced" ? "stripChip active" : "stripChip"}
          onClick={() => onFilter(filter === "unsourced" ? null : ("unsourced" as SceneFilter))}
          title={t("misc.showOnly", { label: t("scene.unsourced") })}
          type="button"
        >
          <i style={{ background: "#8b93c9" }} />
          {t("scene.unsourced")} {census.unsourcedCount}
        </button>
      )}
      {census.rawCount > 0 && (
        <button
          className={filter === "raw" ? "stripChip active rawChip" : "stripChip rawChip"}
          onClick={() => onFilter(filter === "raw" ? null : ("raw" as SceneFilter))}
          title={t("misc.showOnly", { label: t("world.raw") })}
          type="button"
        >
          <i style={{ background: "#57d9a0", borderRadius: 0 }} />◆ {t("world.raw")} {census.rawCount}
        </button>
      )}
      {census.hidden > 0 && (
        <span className="stripChip static" title={t("scene.hiddenTitle")}>
          {t("scene.hiddenTotal", { hidden: census.hidden, total: census.total })}
        </span>
      )}
      <button className={keyOpen ? "stripChip active keyChip" : "stripChip keyChip"} onClick={() => setKeyOpen((open) => !open)} type="button">
        {t("scene.key")}
      </button>
      {keyOpen && (
        <div className="radarKeyPopover" role="dialog" aria-label="Map key">
          <div>
            <span>{t("scene.keyColorLabel")}</span>
            <p>{t("scene.keyColor")}</p>
            <ul>
              {census.contexts.map((entry) => (
                <li key={entry.key}>
                  <i style={{ background: entry.color }} />
                  {entry.label} · {entry.count}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <span>{t("scene.keyPositionLabel")}</span>
            <p>{t("scene.keyPosition")}</p>
          </div>
          <div>
            <span>{t("scene.keyShapeLabel")}</span>
            <p>{t("scene.keyShape")}</p>
          </div>
          <div>
            <span>{t("scene.keyLinesLabel")}</span>
            <ul>
              {census.edgeCounts.map((entry) => (
                <li key={entry.key}>
                  <i style={{ background: entry.color }} />
                  {entry.label} · {entry.count}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <span>{t("scene.keyUseLabel")}</span>
            <p>{t("scene.keyUse")}</p>
          </div>
        </div>
      )}
    </div>
  );
}

function HoverTooltip({ hover }: { hover: { node: LayoutNode; x: number; y: number } | null }) {
  if (!hover) return null;
  const { node } = hover;
  return (
    <div className="radarTooltip" style={{ left: hover.x + 14, top: hover.y + 12 }}>
      <strong>{node.title}</strong>
      <span>
        {pageTypeLabel(node.page_type)} · {contextStyle(node.context).label}
        {isRawData(node.page_type) ? ` · ◆ ${t("world.raw")}` : ""}
      </span>
      <span>
        {freshnessLabel(node.freshness_state)}
        {node.ageDays > 0 ? ` · ${Math.round(node.ageDays)}d since update` : ""}
      </span>
      <span>
        ← {node.inbound_links} in · → {node.outbound_links} out · evidence {node.source_ref_count}
      </span>
      {node.risk_flags.length > 0 && <span className="tooltipRisk">{node.risk_flags.join(", ").replaceAll("_", " ")}</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Minimap + 2D fallback: the same layout, the same URLs, zero motion.

export function FallbackPlanView({
  layout,
  selectedPageId,
  highlightedIds,
  onNodeSelect,
  onContextSelect
}: {
  layout: WorldLayout;
  selectedPageId: string;
  highlightedIds: Set<string>;
  onNodeSelect?: (nodeId: string) => void;
  onContextSelect?: (context: string) => void;
}) {
  const size = 420;
  const scale = size / 2 / (layout.rOuter + 1.2);
  const px = (value: number) => size / 2 + value * scale;
  const band = layout.rOuter - layout.rInner;
  const deadlineR = (layout.rInner + band * layout.deadlineF) * scale;
  return (
    <svg className="fallbackPlan" viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Content map plan view">
      {layout.guides
        .filter((guide): guide is Extract<typeof guide, { kind: "circle" }> => guide.kind === "circle")
        .map((guide, index) => (
          <circle key={`g-${index}`} cx={size / 2} cy={size / 2} r={guide.radius * scale} fill="none" stroke="#22303a" strokeOpacity="0.5" />
        ))}
      {layout.radial === "freshness" && (
        <>
          <circle cx={size / 2} cy={size / 2} r={layout.rInner * scale} fill="none" stroke="#22303a" strokeOpacity="0.5" />
          <circle cx={size / 2} cy={size / 2} r={layout.rOuter * scale} fill="none" stroke="#22303a" strokeOpacity="0.5" />
          <circle cx={size / 2} cy={size / 2} r={deadlineR} fill="none" stroke={trustColor("stale")} strokeOpacity="0.45" strokeDasharray="4 4" />
        </>
      )}
      {layout.wedges.map((wedge) => (
        <line
          key={`ray-${wedge.context}`}
          x1={px(Math.cos(wedge.startAngle) * layout.rInner)}
          y1={px(Math.sin(wedge.startAngle) * layout.rInner)}
          x2={px(Math.cos(wedge.startAngle) * layout.rOuter)}
          y2={px(Math.sin(wedge.startAngle) * layout.rOuter)}
          stroke="#22303a"
          strokeOpacity="0.4"
        />
      ))}
      {layout.groups.map((group) => (
        <text
          key={`plan-label-${group.key}`}
          x={px(group.anchor[0])}
          y={px(group.anchor[2])}
          className="planContextLabel"
          textAnchor="middle"
          style={{ cursor: onContextSelect ? "pointer" : undefined }}
          onClick={() => group.drill?.context && onContextSelect?.(group.drill.context)}
        >
          {worldGroupLabel(group.kind, group.labelKey)} · {group.shown < group.count ? `${group.shown}/${group.count}` : group.count}
        </text>
      ))}
      {layout.clusterStars.map((star) => (
        <g key={`plan-star-${star.key}`}>
          <circle
            cx={px(star.position[0])}
            cy={px(star.position[2])}
            r={Math.max(5, star.scale * scale * 1.6)}
            fill="#334a5c"
            stroke="#6bd7ff"
            strokeWidth={1.4}
            onClick={() => star.drill?.context && onContextSelect?.(star.drill.context)}
            style={{ cursor: onContextSelect && star.drill?.context ? "pointer" : undefined }}
          />
          <text x={px(star.position[0])} y={px(star.position[2]) + 3} className="planContextLabel" textAnchor="middle">
            +{star.count}
          </text>
        </g>
      ))}
      {layout.nodes.map((node) => {
        const highlighted = highlightedIds.has(node.id) || highlightedIds.has(node.path);
        const selected = node.id === selectedPageId || node.path === selectedPageId;
        // At 2-4px, STATE wins the pixel: attention dots take the state accent
        // and a size bump; calm dots carry the context hue (aged). Premixing
        // hue+tone at this size reads as murk for everyone.
        const trust = nodeTrustKey(node);
        const attention = trust === "stale" || trust === "proposal";
        const fill = node.isRoot ? trustColor("root") : attention ? trustColor(trust) : nodeDisplayColor(node);
        return (
          <circle
            key={`plan-${node.id}`}
            cx={px(node.position[0])}
            cy={px(node.position[2])}
            r={Math.max(attention ? 4 : 3, node.scale * scale * (attention ? 2 : 1.6))}
            fill={fill}
            fillOpacity={trust === "fresh" && !selected && !highlighted ? 0.55 : trust === "unknown" ? 0.7 : 0.95}
            stroke={selected ? "#dff8ff" : highlighted ? "#8fd0e8" : node.risk_flags.length > 0 ? trustColor("risk") : "none"}
            strokeWidth={selected || highlighted ? 2 : 1.4}
            onClick={() => onNodeSelect?.(node.id)}
            style={{ cursor: onNodeSelect ? "pointer" : undefined }}
          />
        );
      })}
    </svg>
  );
}

// The reduced-motion / no-WebGL fallback navigates the exact same topology at
// the same URLs: perspectives, levels, groups and pages as nested lists.
function SceneFallback({
  layout,
  git,
  selectedPageId,
  highlightedIds,
  census,
  makeHref,
  onNodeSelect,
  onGroupSelect,
  onStarDrill
}: {
  layout: WorldLayout;
  git: GitState;
  selectedPageId: string;
  highlightedIds: Set<string>;
  census: SceneCensus;
  makeHref: (patch: ScenePatch) => string;
  onNodeSelect?: (nodeId: string) => void;
  onGroupSelect: (group: WorldGroup) => void;
  onStarDrill: (star: ClusterStar) => void;
}) {
  return (
    <div className="sceneFallback" aria-label="Content map">
      <div className="fallbackCore">
        <strong>{git.proposal.is_proposal_branch ? "Draft change" : "Approved content"}</strong>
        <span>{workspaceLabel(git)}</span>
      </div>
      <FallbackPlanView
        layout={layout}
        selectedPageId={selectedPageId}
        highlightedIds={highlightedIds}
        onNodeSelect={onNodeSelect}
        onContextSelect={(context) => onGroupSelect({ key: context, kind: "context", labelKey: context, count: 0, shown: 0, anchor: [0, 0, 0], drill: { context }, memberIds: [] })}
      />
      <div className="fallbackCensus" aria-label="Content map counts">
        {census.trust.map((entry) => (
          <span key={entry.key}>
            <i style={{ background: entry.color }} />
            {entry.label} {entry.count}
          </span>
        ))}
        {census.hidden > 0 && <span>{t("scene.hiddenTotal", { hidden: census.hidden, total: census.total })}</span>}
      </div>
      <nav className="fallbackGroups" aria-label="Grupos deste nível">
        {layout.groups.map((group) => (
          <a
            key={group.key}
            className="fallbackGroupLink"
            href={
              group.drill
                ? makeHref({ context: group.drill.context ?? null, group: group.drill.group ?? null, pageId: null, reader: false })
                : makeHref({})
            }
            onClick={(event) => {
              event.preventDefault();
              onGroupSelect(group);
            }}
          >
            {worldGroupLabel(group.kind, group.labelKey)} · {group.shown < group.count ? `${group.shown}/${group.count}` : group.count}
          </a>
        ))}
        {layout.clusterStars.map((star) =>
          star.drill ? (
            <a
              key={star.key}
              className="fallbackGroupLink starLink"
              href={makeHref({ context: star.drill.context ?? null, group: star.drill.group ?? null, pageId: null, reader: false })}
              onClick={(event) => {
                event.preventDefault();
                onStarDrill(star);
              }}
            >
              +{star.count} {t("scene.hidden")}
            </a>
          ) : (
            <button key={star.key} className="fallbackGroupLink starLink" onClick={() => onStarDrill(star)} type="button">
              +{star.count} {t("scene.hidden")} · {t("scene.showMore")}
            </button>
          )
        )}
      </nav>
      <div className="fallbackNodeGrid">
        {layout.nodes.slice(0, 24).map((node) => {
          const trust = nodeTrustKey(node);
          return (
            <a
              className={`fallbackNode node-${node.freshness_state}${node.id === selectedPageId || node.path === selectedPageId ? " active" : ""}${highlightedIds.has(node.id) || highlightedIds.has(node.path) ? " highlighted" : ""}`}
              key={`${node.id}-${node.path}`}
              href={makeHref({ pageId: node.id, reader: true })}
              onClick={(event) => {
                event.preventDefault();
                onNodeSelect?.(node.id);
              }}
              // Border = context identity; the state ALSO gets a text chip so
              // the fallback never encodes meaning in color alone (WCAG 1.4.1).
              style={{ borderColor: nodeDisplayColor(node) }}
              title={node.path}
            >
              {node.title}
              {trust !== "fresh" && <small className="fallbackNodeState">{t(`scene.trust.${trust}`)}</small>}
            </a>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

const NO_EDGES: GraphEdge[] = [];
const NO_IDS: string[] = [];

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
      nodes,
      edges,
      maxNodes: Math.min(profile.maxNodes + revealBoost, 480),
      snapshotAt
    }),
    [edges, nodes, profile.maxNodes, revealBoost, route.context, route.group, route.pageId, route.perspective, snapshotAt]
  );
  const layout = useWorldLayout(request);
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
      navigate({ pageId: node.id, reader: true });
      announce(`${node.title}, ${contextStyle(node.context).label}, ${freshnessLabel(node.freshness_state)}`);
    },
    [announce, navigate]
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
      const perspectiveKeys: Record<string, PerspectiveId> = { "1": "radar", "2": "atlas", "3": "districts", "4": "trails" };
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
        if (route.pageId) {
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
    selectNode
  ]);
  const focusedGroupKey = layout.groups[focusedGroupIndex]?.key ?? "";


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
                onSelect={selectNode}
                onHover={handleHover}
                onGroupSelect={handleGroupSelect}
                onStarDrill={handleStarDrill}
                onBeaconJump={handleBeaconJump}
                onLockRead={() => navigate({ reader: true })}
                onLockPacket={() => route.pageId && onTogglePacket?.(route.pageId)}
                onLockTrails={() => navigate({ perspective: "trails" })}
                onLockRefresh={() => onRunRefresh?.()}
              />
            </Canvas>
          </div>
          {children}
          <HoverTooltip hover={hover} />
          <StatusStrip census={census} filter={filter} onFilter={(key) => navigate({ filter: key })} />
          {/* Minimap: persistent overview disc; M or click expands it as an
              instant, motion-free zoom-to-galaxy. Hidden while the reader dock
              is open (the dock would fully cover the disc); M still expands it
              fullscreen over the dock. */}
          {(!route.reader || minimapExpanded) && (
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
