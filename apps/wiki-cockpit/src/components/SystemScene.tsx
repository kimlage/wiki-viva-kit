import { Html, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import type { ThreeEvent } from "@react-three/fiber";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import type { GraphEdge, GraphNode, GitState } from "../types";
import { contextStyle, edgeStyle, pageTypeLabel, pageTypeStyle, trustColor } from "../data/presentation";
import { glowTexture, ringTexture } from "../scene/glow";
import { computeGalaxyLayout, scenePerformanceProfile } from "../scene/layout";
import type { GalaxyLayout, LayoutNode, LayoutWedge, ScenePerformanceProfile } from "../scene/layout";
import {
  auraPoint,
  buildAuraParticles,
  buildEmberParticles,
  buildFlowParticles,
  buildStemParticles,
  emberPoint,
  flowPoint,
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
  if (state === "fresh") return "ok";
  if (state === "stale") return "needs refresh";
  return "not checked";
}

function workspaceLabel(git: GitState): string {
  if (git.proposal.is_proposal_branch) return git.proposal.theme ? `review: ${git.proposal.theme}` : "review workspace";
  if (git.current_branch === git.default_branch) return "approved workspace";
  return "current workspace";
}

type SceneIntent = {
  label: string;
  detail: string;
  count: number;
};

export type SceneIntentOption = {
  id: string;
  label: string;
  count: number;
};

type TrustKey = "fresh" | "stale" | "unknown" | "proposal";

function nodeTrustKey(node: Pick<LayoutNode, "approved_state" | "freshness_state">): TrustKey {
  if (node.approved_state === "proposal") return "proposal";
  if (node.freshness_state === "fresh") return "fresh";
  if (node.freshness_state === "stale") return "stale";
  return "unknown";
}

// Salience inversion: healthy content is dark and quiet, everything that
// needs a human glows. Trust hexes stay the legend colors.
const TRUST_MATERIALS: Record<TrustKey | "root", { color: string; emissiveIntensity: number; opacity: number; glows: boolean }> = {
  fresh: { color: "#37906b", emissiveIntensity: 0.32, opacity: 1, glows: false },
  stale: { color: "#ffb454", emissiveIntensity: 1.1, opacity: 1, glows: true },
  proposal: { color: "#c57cff", emissiveIntensity: 1.0, opacity: 1, glows: true },
  unknown: { color: "#77808c", emissiveIntensity: 0.14, opacity: 0.6, glows: false },
  root: { color: "#6bd7ff", emissiveIntensity: 0.9, opacity: 1, glows: true }
};

function trustMaterial(node: LayoutNode) {
  if (node.isRoot) return TRUST_MATERIALS.root;
  return TRUST_MATERIALS[nodeTrustKey(node)];
}

function trustDisplayColor(node: LayoutNode): string {
  if (node.isRoot) return trustColor("root");
  return trustColor(nodeTrustKey(node));
}

// Shape super-families: 7 configured shapes collapse to 3 that stay legible
// at node size. Presentation overrides still steer the mapping.
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

function useGalaxyLayout(nodes: GraphNode[], profile: ScenePerformanceProfile, snapshotAt?: string): GalaxyLayout {
  const [layout, setLayout] = useState<GalaxyLayout>(() => computeGalaxyLayout(nodes, profile.maxNodes, snapshotAt));
  useEffect(() => {
    let active = true;
    const sync = () => {
      const next = computeGalaxyLayout(nodes, profile.maxNodes, snapshotAt);
      if (active) setLayout(next);
    };
    if (typeof Worker === "undefined") {
      sync();
      return () => {
        active = false;
      };
    }
    const worker = new Worker(new URL("../scene/layout.worker.ts", import.meta.url), { type: "module" });
    worker.onmessage = (event: MessageEvent<GalaxyLayout>) => {
      if (active) setLayout(event.data);
    };
    worker.onerror = () => sync();
    worker.postMessage({ nodes, maxNodes: profile.maxNodes, snapshotAt });
    return () => {
      active = false;
      worker.terminate();
    };
  }, [nodes, profile.maxNodes, snapshotAt]);
  return layout;
}

function layoutNodeIndex(layout: GalaxyLayout): Map<string, LayoutNode> {
  const index = new Map<string, LayoutNode>();
  layout.nodes.forEach((node) => {
    index.set(node.id, node);
    index.set(node.path, node);
  });
  return index;
}

// ---------------------------------------------------------------------------
// Edges: quadratic bezier arcs merged into one vertex-colored LineSegments.
// Reference links arc BELOW the disc so the bulk web never hides nodes.

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
  quality: string
): number {
  const touchesFocus =
    focusIds.size > 0 && [edge.from.id, edge.from.path, edge.to.id, edge.to.path].some((key) => focusIds.has(key));
  const insideHighlight =
    highlightedIds.size > 0 &&
    (highlightedIds.has(edge.from.id) || highlightedIds.has(edge.from.path)) &&
    (highlightedIds.has(edge.to.id) || highlightedIds.has(edge.to.path));
  if (touchesFocus) return edge.type === "markdown_link" ? 0.65 : 1;
  if (insideHighlight && edge.type === "pr_impact") return 1;
  const rest = EDGE_REST_OPACITY[edge.type] ?? 0.3;
  const ambient = edge.type === "markdown_link" ? (quality === "rich" ? 0.08 : 0) : rest;
  return focusIds.size > 0 ? ambient * 0.25 : ambient;
}

function selectSceneEdges(
  edges: GraphEdge[],
  layout: GalaxyLayout,
  focusIds: Set<string>,
  highlightedIds: Set<string>,
  profile: ScenePerformanceProfile
): SceneEdge[] {
  const index = layoutNodeIndex(layout);
  const mapped: (SceneEdge & { sortKey: string })[] = [];
  for (const edge of edges) {
    const from = index.get(edge.source);
    const to = index.get(edge.target);
    if (!from || !to || from.id === to.id) continue;
    const emphasis = edgeEmphasis({ from, to, type: edge.type }, focusIds, highlightedIds, profile.quality);
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

function mocParentRoute(edges: GraphEdge[], layout: GalaxyLayout, selectedId: string): LayoutNode[] {
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

function RouteLine({ route }: { route: LayoutNode[] }) {
  const { invalidate } = useThree();
  const object = useMemo(() => {
    if (route.length < 2) return null;
    const points = route.map((node) => new THREE.Vector3(...node.position));
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({ color: "#dff8ff", transparent: true, opacity: 0.9, toneMapped: false });
    return { line: new THREE.Line(geometry, material), geometry, material };
  }, [route]);
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
// Reference geometry: every line answers a question. Polar rings = how far
// from verified; deadline arcs = the freshness window; rays = context bounds.

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

function RadarGrid({ layout }: { layout: GalaxyLayout }) {
  const band = layout.rOuter - layout.rInner;
  const gridRadii = [layout.rInner, layout.rInner + band * 0.33, layout.rInner + band, layout.rOuter + 0.02];
  const deadlineRadius = layout.rInner + band * layout.deadlineF;
  // The widest wedge carries the on-map caption for the freshness deadline.
  const captionWedge = [...layout.wedges].sort(
    (a, b) => b.endAngle - b.startAngle - (a.endAngle - a.startAngle) || a.context.localeCompare(b.context)
  )[0];
  return (
    <group>
      {/* Danger zone: the translucent amber band past the deadline arc makes
          "outside = overdue" readable without a legend. */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.03, 0]}>
        <ringGeometry args={[deadlineRadius, layout.rOuter, 96]} />
        <meshBasicMaterial color={trustColor("stale")} transparent opacity={0.045} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} side={THREE.DoubleSide} />
      </mesh>
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
          <span>freshness deadline · older content drifts outward</span>
        </Html>
      )}
      {gridRadii.map((radius) => (
        <StaticLine key={`grid-${radius}`} points={circlePoints(radius)} color="#22303a" opacity={0.28} />
      ))}
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
          {/* Deadline arc: crossing it means the freshness window has passed. */}
          <StaticLine
            points={arcPoints(layout.rInner + band * layout.deadlineF, wedge.startAngle + 0.02, wedge.endAngle - 0.02, 28)}
            color={trustColor("stale")}
            opacity={0.4}
          />
          {/* Context accent arc on the rim. */}
          <StaticLine
            points={arcPoints(layout.rOuter + 0.2, wedge.startAngle + 0.015, wedge.endAngle - 0.015, 32)}
            color={contextStyle(wedge.context).accent}
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
// Nodes: instanced by (shape, trust, dimmed). Dimmed groups darken to 25%.

type NodeGroup = {
  key: string;
  shape: SuperShape;
  material: (typeof TRUST_MATERIALS)[TrustKey | "root"];
  trust: TrustKey | "root";
  dimmed: boolean;
  items: LayoutNode[];
};

function InstancedNodeMesh({
  group,
  profile,
  selectedId,
  onSelect,
  onHover,
  registerMaterial
}: {
  group: NodeGroup;
  profile: ScenePerformanceProfile;
  selectedId: string;
  onSelect: (node: LayoutNode) => void;
  onHover: (node: LayoutNode | null, event?: ThreeEvent<PointerEvent>) => void;
  registerMaterial: (trust: TrustKey | "root", dimmed: boolean, material: THREE.MeshStandardMaterial | null) => void;
}) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const { invalidate } = useThree();
  const matrix = useMemo(() => new THREE.Matrix4(), []);
  const quaternion = useMemo(() => new THREE.Quaternion(), []);
  useLayoutEffect(() => {
    if (!ref.current) return;
    group.items.forEach((node, index) => {
      const selected = node.id === selectedId || node.path === selectedId ? 1.18 : 1;
      matrix.compose(
        new THREE.Vector3(...node.position),
        quaternion,
        new THREE.Vector3(node.scale * selected, node.scale * selected, node.scale * selected)
      );
      ref.current?.setMatrixAt(index, matrix);
    });
    ref.current.instanceMatrix.needsUpdate = true;
    invalidate();
  }, [group.items, invalidate, matrix, quaternion, selectedId]);
  const dim = group.dimmed ? 0.25 : 1;
  const baseColor = useMemo(() => new THREE.Color(group.material.color).multiplyScalar(dim), [dim, group.material.color]);
  const emissiveColor = useMemo(() => new THREE.Color(trustColor(group.trust as TrustKey | "root")).multiplyScalar(dim), [dim, group.trust]);
  return (
    <instancedMesh
      ref={ref}
      args={[undefined, undefined, Math.max(group.items.length, 1)]}
      onClick={(event) => {
        event.stopPropagation();
        if (typeof event.instanceId === "number" && group.items[event.instanceId]) onSelect(group.items[event.instanceId]);
      }}
      onPointerMove={(event) => {
        if (typeof event.instanceId === "number" && group.items[event.instanceId]) onHover(group.items[event.instanceId], event);
      }}
      onPointerOut={() => onHover(null)}
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
  );
}

function NodeInstances({
  nodes,
  profile,
  selectedId,
  dimTest,
  onSelect,
  onHover,
  registerMaterial
}: {
  nodes: LayoutNode[];
  profile: ScenePerformanceProfile;
  selectedId: string;
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
          onSelect={onSelect}
          onHover={onHover}
          registerMaterial={registerMaterial}
        />
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// Glow sprites: additive halos behind everything that demands attention.

function GlowSprites({
  nodes,
  highlightedIds,
  selectedId,
  registerPulse
}: {
  nodes: LayoutNode[];
  highlightedIds: Set<string>;
  selectedId: string;
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
          node.id === selectedId ||
          node.path === selectedId
      ),
    [highlightedIds, nodes, selectedId]
  );
  if (!texture) return null;
  return (
    <group>
      {glowing.map((node) => {
        const highlighted = highlightedIds.has(node.id) || highlightedIds.has(node.path);
        const selected = node.id === selectedId || node.path === selectedId;
        const trust = nodeTrustKey(node);
        const color = selected ? "#dff8ff" : trustDisplayColor(node);
        const size = node.scale * (selected || highlighted ? 5.2 : 4.2);
        const opacity = selected ? 0.6 : highlighted ? 0.5 : trust === "stale" ? 0.38 : 0.3;
        return (
          <sprite key={`glow-${node.id}`} position={node.position} scale={[size, size, 1]}>
            <spriteMaterial
              ref={(material) => {
                if (trust === "stale" && !selected && !highlighted) registerPulse("stale", material);
                if (highlighted) registerPulse("highlight", material);
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

// ---------------------------------------------------------------------------
// Labels: budgeted always-on labels for the attention set + hubs.

type SceneLabel = {
  node: LayoutNode;
  annotation: string | null;
  annotationColor: string | null;
};

function buildLabelSet(layout: GalaxyLayout, highlightedIds: Set<string>, selectedId: string, budget: number): SceneLabel[] {
  const seen = new Set<string>();
  const labels: SceneLabel[] = [];
  const push = (node: LayoutNode | undefined, annotation: string | null, annotationColor: string | null) => {
    if (!node || seen.has(node.id)) return;
    seen.add(node.id);
    labels.push({ node, annotation, annotationColor });
  };
  const byOverdue = [...layout.nodes].sort((a, b) => b.overdueRatio - a.overdueRatio || a.title.localeCompare(b.title));

  // Root and selection are always labeled, outside the budget.
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
  // Deconflict by angular neighborhood: labels sharing a sector bucket climb
  // in deterministic tiers instead of overprinting each other.
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

function ContextRimPills({ wedges, onContextSelect }: { wedges: LayoutWedge[]; onContextSelect?: (context: string) => void }) {
  return (
    <group>
      {wedges.map((wedge) => {
        const style = contextStyle(wedge.context);
        return (
          <Html key={`rim-${wedge.context}`} position={wedge.rimPosition} center distanceFactor={5.2} wrapperClass="sceneHtmlLabel" className="radarRimPill" zIndexRange={[40, 0]}>
            <button
              style={{ borderColor: style.accent, pointerEvents: "auto" }}
              onClick={(event) => {
                event.stopPropagation();
                onContextSelect?.(wedge.context);
              }}
              type="button"
            >
              <strong>{style.label}</strong>
              <span className="rimDots" aria-hidden>
                {wedge.freshCount > 0 && <i style={{ background: trustColor("fresh") }} />}
                {wedge.staleCount > 0 && <i style={{ background: trustColor("stale") }} />}
                {wedge.proposalCount > 0 && <i style={{ background: trustColor("proposal") }} />}
                {wedge.unknownCount > 0 && <i style={{ background: trustColor("unknown") }} />}
                {wedge.riskCount > 0 && <i style={{ background: trustColor("risk") }} />}
              </span>
              <small>
                {wedge.count}
                {wedge.staleCount > 0 ? ` · ${wedge.staleCount} old` : ""}
              </small>
            </button>
          </Html>
        );
      })}
    </group>
  );
}

// ---------------------------------------------------------------------------
// Camera: fit-to-content framing with polar clamps and a short intro glide.

function CameraRig({ layout, enableIntro }: { layout: GalaxyLayout; enableIntro: boolean }) {
  const { camera, size, invalidate } = useThree();
  const framed = useRef<number>(0);
  const intro = useRef({ active: false, from: 0, to: 0, started: null as number | null });
  const fitDistance = useMemo(() => {
    const rLabel = layout.rOuter + 1.1;
    const vFov = (40 * Math.PI) / 180;
    const aspect = size.width / Math.max(size.height, 1);
    const hFov = 2 * Math.atan(Math.tan(vFov / 2) * aspect);
    return (rLabel / Math.sin(Math.min(vFov, hFov) / 2)) * 0.88;
  }, [layout.rOuter, size.height, size.width]);
  useEffect(() => {
    if (framed.current === fitDistance) return;
    framed.current = fitDistance;
    const polar = 0.72;
    const apply = (distance: number) => {
      camera.position.set(0, Math.cos(polar) * distance, Math.sin(polar) * distance);
      camera.lookAt(0, 0, 0);
    };
    if (enableIntro) {
      intro.current = { active: true, from: fitDistance * 1.28, to: fitDistance, started: null };
      apply(fitDistance * 1.28);
    } else {
      apply(fitDistance);
    }
    if ("fov" in camera) {
      (camera as THREE.PerspectiveCamera).fov = 40;
      (camera as THREE.PerspectiveCamera).updateProjectionMatrix();
    }
    invalidate();
  }, [camera, enableIntro, fitDistance, invalidate]);
  useFrame((state) => {
    if (!intro.current.active) return;
    const now = state.clock.elapsedTime;
    if (intro.current.started === null) intro.current.started = now;
    const t = Math.min(1, (now - intro.current.started) / 0.65);
    const eased = 1 - Math.pow(1 - t, 3);
    const distance = THREE.MathUtils.lerp(intro.current.from, intro.current.to, eased);
    const polar = 0.72;
    camera.position.set(0, Math.cos(polar) * distance, Math.sin(polar) * distance);
    camera.lookAt(0, 0, 0);
    state.invalidate();
    if (t >= 1) intro.current.active = false;
  });
  return (
    <OrbitControls
      enablePan={false}
      minDistance={fitDistance * 0.4}
      maxDistance={fitDistance * 1.6}
      minPolarAngle={0.35}
      maxPolarAngle={1.2}
      enableDamping
    />
  );
}

// ---------------------------------------------------------------------------
// Particle systems: every emitter maps to a real signal. Core aura density =
// recent activity; flow sparks travel provenance arcs; embers rise from
// overdue pages; stem sparks climb toward floating drafts.

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
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        toneMapped={false}
      />
    </points>
  );
}

function SceneParticles({
  layout,
  flowEdges,
  activityLevel,
  quality,
  motion
}: {
  layout: GalaxyLayout;
  flowEdges: SceneEdge[];
  activityLevel: number;
  quality: string;
  motion: boolean;
}) {
  const rich = quality === "rich";
  const aura = useMemo(
    () => buildAuraParticles(activityLevel, rich ? 120 : 60),
    [activityLevel, rich]
  );
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
  const flow = useMemo(
    () => buildFlowParticles(flowInputs, rich ? 2 : 1, rich ? 72 : 36),
    [flowInputs, rich]
  );
  const embers = useMemo(
    () => buildEmberParticles(layout.nodes.filter((node) => node.freshness_state === "stale"), rich ? 5 : 3, rich ? 60 : 30),
    [layout.nodes, rich]
  );
  const stems = useMemo(
    () => buildStemParticles(layout.nodes.filter((node) => node.approved_state === "proposal" && node.position[1] > 0.05), 3, 24),
    [layout.nodes]
  );
  if (!motion || quality === "compact") return null;
  return (
    <group>
      <ParticleCloud particles={aura} evaluate={auraPoint} size={0.62} baseColor={trustColor("root")} />
      <ParticleCloud particles={flow} evaluate={flowPoint} size={0.58} colorFor={(particle) => particle.color} />
      <ParticleCloud particles={embers} evaluate={emberPoint} size={0.6} baseColor="#ffd27a" />
      <ParticleCloud particles={stems} evaluate={stemPoint} size={0.6} baseColor="#e2aaff" />
    </group>
  );
}

// ---------------------------------------------------------------------------
// Ambient animation driver: one useFrame, gated by the motion governor.

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
    const stalePulse = 0.3 + 0.09 * Math.sin((t * Math.PI * 2) / 2.4);
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
  filter,
  motion,
  activityLevel,
  onSelect,
  onHover,
  onContextSelect
}: {
  layout: GalaxyLayout;
  edges: GraphEdge[];
  git: GitState;
  profile: ScenePerformanceProfile;
  selectedId: string;
  highlightedIds: Set<string>;
  filter: TrustKey | null;
  motion: boolean;
  activityLevel: number;
  onSelect: (node: LayoutNode) => void;
  onHover: (node: LayoutNode | null, event?: ThreeEvent<PointerEvent>) => void;
  onContextSelect?: (context: string) => void;
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

  const sceneEdges = useMemo(
    () => selectSceneEdges(edges, layout, focusIds, highlightedIds, profile),
    [edges, focusIds, highlightedIds, layout, profile]
  );
  // Flow sparks stay honest: they ride arcs that touch something needing
  // attention (stale, draft, risk) or the focused node — never the healthy
  // bulk, so quiet content stays quiet.
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

  const dimTest = useCallback(
    (node: LayoutNode) => {
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

  return (
    <>
      <color attach="background" args={["#05090e"]} />
      <fogExp2 attach="fog" args={["#05090e", 0.032]} />
      <hemisphereLight args={["#1a3040", "#05080c", 0.5]} />
      <directionalLight position={[4, 6, 3]} intensity={1.2} color="#cfeaff" />
      <StarField quality={profile.quality} />
      <RadarGrid layout={layout} />
      <GateRing git={git} />
      <ProposalStems nodes={layout.nodes} />
      <EdgeArcs edges={sceneEdges} quality={profile.quality} />
      <RouteLine route={route} />
      <NodeInstances
        nodes={layout.nodes.filter((node) => !node.isRoot)}
        profile={profile}
        selectedId={selectedId}
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
          onClick={(event) => {
            event.stopPropagation();
            onSelect(rootNode);
          }}
          onPointerMove={(event) => handleHover(rootNode, event)}
          onPointerOut={() => handleHover(null)}
        >
          <sphereGeometry args={[1, profile.geometrySegments + 8, profile.geometrySegments + 8]} />
          <meshStandardMaterial
            color={TRUST_MATERIALS.root.color}
            emissive={trustColor("root")}
            emissiveIntensity={TRUST_MATERIALS.root.emissiveIntensity}
            roughness={0.3}
            toneMapped={false}
          />
        </mesh>
      )}
      <GlowSprites nodes={layout.nodes} highlightedIds={highlightedIds} selectedId={selectedId} registerPulse={registerPulse} />
      <RingSprites nodes={layout.nodes} />
      <SceneParticles layout={layout} flowEdges={flowEdges} activityLevel={activityLevel} quality={profile.quality} motion={motion} />
      <NodeLabels labels={labels} selectedId={selectedId} />
      <ContextRimPills wedges={layout.wedges} onContextSelect={onContextSelect} />
      <CameraRig layout={layout} enableIntro={profile.enableIntro} />
      <AmbientDriver enabled={motion} rootRef={rootRef} pulses={pulses} />
    </>
  );
}

// ---------------------------------------------------------------------------
// HUD + census

type SceneCensus = {
  trust: { key: TrustKey; label: string; color: string; count: number }[];
  riskCount: number;
  evidenceCount: number;
  edgeCounts: { key: string; label: string; color: string; count: number }[];
  truncated: number;
};

function sceneCensus(nodes: GraphNode[], edges: GraphEdge[], layout: GalaxyLayout): SceneCensus {
  const visibleIds = new Set(layout.nodes.map((node) => node.id));
  const visible = nodes.filter((node) => visibleIds.has(node.id));
  const counts = new Map<TrustKey, number>();
  visible.forEach((node) => {
    const key = nodeTrustKey({ approved_state: node.approved_state, freshness_state: node.freshness_state });
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  const trust = (
    [
      { key: "fresh" as const, label: "up to date" },
      { key: "stale" as const, label: "needs refresh" },
      { key: "proposal" as const, label: "draft change" },
      { key: "unknown" as const, label: "not checked" }
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
    edgeCounts: [...edgeCounts.entries()]
      .map(([key, count]) => ({ key, label: edgeStyle(key).label, color: edgeStyle(key).color, count }))
      .sort((a, b) => b.count - a.count),
    truncated: layout.truncated
  };
}

function StatusStrip({
  census,
  filter,
  onFilter
}: {
  census: SceneCensus;
  filter: TrustKey | null;
  onFilter: (key: TrustKey | null) => void;
}) {
  const [keyOpen, setKeyOpen] = useState(false);
  return (
    <div className="radarStatusStrip" aria-label="Map status">
      <span className="stripLabel">filter</span>
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
          risk {census.riskCount}
        </span>
      )}
      {census.evidenceCount > 0 && (
        <span className="stripChip static">
          <i style={{ background: edgeStyle("source_ref").color }} />
          evidence {census.evidenceCount}
        </span>
      )}
      {census.truncated > 0 && <span className="stripChip static">{census.truncated} hidden</span>}
      <button className={keyOpen ? "stripChip active keyChip" : "stripChip keyChip"} onClick={() => setKeyOpen((open) => !open)} type="button">
        Key
      </button>
      {keyOpen && (
        <div className="radarKeyPopover" role="dialog" aria-label="Map key">
          <div>
            <span>Position</span>
            <p>Angle = area. Distance from center = time since verified; past the amber arc = overdue. Floating = draft change.</p>
          </div>
          <div>
            <span>Core</span>
            <p>The center is the wiki root; the ring around it shows the workspace gate (purple = draft in review, cyan = approved).</p>
          </div>
          <div>
            <span>Shape</span>
            <p>◆ evidence source · ⬡ area hub · ● content</p>
          </div>
          <div>
            <span>Lines</span>
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
            <span>Motion</span>
            <p>Core sparks = this week's activity (still when idle). Sparks on lines = review/ingestion flow around items needing attention; select a page to see its own evidence flow. Rising embers = content aging out. Climbing sparks = drafts waiting for approval.</p>
          </div>
          <div>
            <span>Use it</span>
            <p>Hover = inspect + connections. Click = open details. Drag = orbit. Scroll = zoom.</p>
          </div>
        </div>
      )}
    </div>
  );
}

function IntentBar({
  intent,
  options,
  git,
  onIntentChange
}: {
  intent: SceneIntent;
  options: SceneIntentOption[];
  git: GitState;
  onIntentChange?: (id: string) => void;
}) {
  const activeId = options.find((option) => option.label === intent.label)?.id ?? options[0]?.id ?? "";
  return (
    <div className="radarIntentBar" aria-label="Current task">
      {options.length > 0 && onIntentChange ? (
        <label className="intentSelect">
          <select value={activeId} onChange={(event) => onIntentChange(event.target.value)}>
            {options.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label} · {option.count}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <strong>{intent.label}</strong>
      )}
      <span className="intentDetail">{intent.detail}</span>
      <span className={git.proposal.is_proposal_branch ? "gateChip proposal" : "gateChip approved"}>{workspaceLabel(git)}</span>
    </div>
  );
}

function SelectedCard({
  node,
  onDismiss,
  onAddToPacket
}: {
  node: LayoutNode | null;
  onDismiss: () => void;
  onAddToPacket?: (id: string) => void;
}) {
  if (!node) return null;
  return (
    <div className="radarSelectedCard" aria-live="polite">
      <div className="radarSelectedHead">
        <span>Selected content</span>
        <button onClick={onDismiss} title="Dismiss" type="button">
          ×
        </button>
      </div>
      <strong>{node.title}</strong>
      <p>
        {contextStyle(node.context).label} · {pageTypeLabel(node.page_type)} · {freshnessLabel(node.freshness_state)}
      </p>
      <div className="radarSelectedActions">
        <a href={`/pages/${encodeURIComponent(node.id)}`}>Open content</a>
        {onAddToPacket && (
          <button onClick={() => onAddToPacket(node.id)} type="button">
            Add to packet
          </button>
        )}
      </div>
      <details className="sceneTechnicalDetails">
        <summary>Source and file details</summary>
        <code>{node.path}</code>
      </details>
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
// 2D fallback: an SVG plan view of the SAME layout so reduced-motion and
// screenshot tests pin the real geometry.

function FallbackPlanView({
  layout,
  selectedPageId,
  highlightedIds,
  onNodeSelect
}: {
  layout: GalaxyLayout;
  selectedPageId: string;
  highlightedIds: Set<string>;
  onNodeSelect?: (nodeId: string) => void;
}) {
  const size = 420;
  const scale = size / 2 / (layout.rOuter + 1.2);
  const px = (value: number) => size / 2 + value * scale;
  const band = layout.rOuter - layout.rInner;
  const deadlineR = (layout.rInner + band * layout.deadlineF) * scale;
  return (
    <svg className="fallbackPlan" viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Content map plan view">
      <circle cx={size / 2} cy={size / 2} r={layout.rInner * scale} fill="none" stroke="#22303a" strokeOpacity="0.5" />
      <circle cx={size / 2} cy={size / 2} r={layout.rOuter * scale} fill="none" stroke="#22303a" strokeOpacity="0.5" />
      <circle cx={size / 2} cy={size / 2} r={deadlineR} fill="none" stroke={trustColor("stale")} strokeOpacity="0.45" strokeDasharray="4 4" />
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
      {layout.wedges.map((wedge) => (
        <text key={`plan-label-${wedge.context}`} x={px(wedge.rimPosition[0])} y={px(wedge.rimPosition[2])} className="planContextLabel" textAnchor="middle">
          {contextStyle(wedge.context).label} · {wedge.count}
        </text>
      ))}
      {layout.nodes.map((node) => {
        const highlighted = highlightedIds.has(node.id) || highlightedIds.has(node.path);
        const selected = node.id === selectedPageId || node.path === selectedPageId;
        return (
          <circle
            key={`plan-${node.id}`}
            cx={px(node.position[0])}
            cy={px(node.position[2])}
            r={Math.max(3, node.scale * scale * 1.6)}
            fill={trustDisplayColor(node)}
            fillOpacity={node.freshness_state === "fresh" && !selected && !highlighted ? 0.55 : 0.95}
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

function SceneFallback({
  nodes,
  layout,
  git,
  selectedPageId,
  highlightedIds,
  intent,
  census,
  onNodeSelect
}: {
  nodes: GraphNode[];
  layout: GalaxyLayout;
  git: GitState;
  selectedPageId: string;
  highlightedIds: Set<string>;
  intent: SceneIntent;
  census: SceneCensus;
  onNodeSelect?: (nodeId: string) => void;
}) {
  const visibleNodes = useMemo(() => {
    const priority = [...nodes].sort((a, b) => {
      const aSelected = a.id === selectedPageId || a.path === selectedPageId ? 1 : 0;
      const bSelected = b.id === selectedPageId || b.path === selectedPageId ? 1 : 0;
      const aHighlighted = highlightedIds.has(a.id) || highlightedIds.has(a.path) ? 1 : 0;
      const bHighlighted = highlightedIds.has(b.id) || highlightedIds.has(b.path) ? 1 : 0;
      return bSelected - aSelected || bHighlighted - aHighlighted || a.title.localeCompare(b.title);
    });
    return priority.slice(0, 8);
  }, [highlightedIds, nodes, selectedPageId]);
  return (
    <div className="sceneFallback" aria-label="Content map">
      <div className="fallbackCore">
        <strong>{git.proposal.is_proposal_branch ? "Draft change" : "Approved content"}</strong>
        <span>{workspaceLabel(git)}</span>
      </div>
      <div className="sceneIntentBadge" aria-label="Current task">
        <span>{intent.count} highlighted</span>
        <strong>{intent.label}</strong>
        <p>{intent.detail}</p>
      </div>
      <FallbackPlanView layout={layout} selectedPageId={selectedPageId} highlightedIds={highlightedIds} onNodeSelect={onNodeSelect} />
      <div className="fallbackCensus" aria-label="Content map counts">
        {census.trust.map((entry) => (
          <span key={entry.key}>
            <i style={{ background: entry.color }} />
            {entry.label} {entry.count}
          </span>
        ))}
        {census.riskCount > 0 && (
          <span>
            <i style={{ background: trustColor("risk") }} />
            risk {census.riskCount}
          </span>
        )}
      </div>
      <div className="fallbackNodeGrid">
        {visibleNodes.map((node) => (
          <button
            className={`fallbackNode node-${node.freshness_state}${node.id === selectedPageId || node.path === selectedPageId ? " active" : ""}${highlightedIds.has(node.id) || highlightedIds.has(node.path) ? " highlighted" : ""}`}
            key={`${node.id}-${node.path}`}
            onClick={() => onNodeSelect?.(node.id)}
            title={node.path}
          >
            {node.title}
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

export function SystemScene({
  nodes,
  edges = [],
  git,
  selectedPageId = "",
  highlightedPageIds = [],
  intent = { label: "Browse the wiki", detail: "Pick a node to inspect the related content.", count: highlightedPageIds.length },
  intentOptions = [],
  snapshotAt,
  activityLevel = 0,
  onNodeSelect,
  onIntentChange,
  onAddToPacket,
  children
}: {
  nodes: GraphNode[];
  edges?: GraphEdge[];
  git: GitState;
  selectedPageId?: string;
  highlightedPageIds?: string[];
  intent?: SceneIntent;
  intentOptions?: SceneIntentOption[];
  snapshotAt?: string;
  activityLevel?: number;
  onNodeSelect?: (nodeId: string) => void;
  onIntentChange?: (intentId: string) => void;
  onAddToPacket?: (nodeId: string) => void;
  children?: React.ReactNode;
}) {
  const [fallback, setFallback] = useState(shouldUseFallback);
  const [motion, setMotion] = useState(allowAmbientMotion);
  const profile = useSceneProfile(nodes.length);
  const layout = useGalaxyLayout(nodes, profile, snapshotAt);
  const [explicitSelection, setExplicitSelection] = useState<string>("");
  const [filter, setFilter] = useState<TrustKey | null>(null);
  const [hover, setHover] = useState<{ node: LayoutNode; x: number; y: number } | null>(null);
  const highlightedIds = useMemo(() => new Set(highlightedPageIds), [highlightedPageIds]);
  const census = useMemo(() => sceneCensus(nodes, edges, layout), [edges, layout, nodes]);
  const nodeIndex = useMemo(() => layoutNodeIndex(layout), [layout]);
  const activeSelectionId = explicitSelection || selectedPageId;
  const selectedNode = activeSelectionId ? nodeIndex.get(activeSelectionId) ?? null : null;

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

  const selectNode = useCallback(
    (node: LayoutNode) => {
      setExplicitSelection(node.id);
      onNodeSelect?.(node.id);
    },
    [onNodeSelect]
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

  const handleContextSelect = useCallback(
    (context: string) => {
      const hub = layout.nodes.find((node) => node.isHub && node.context === context && !node.isRoot);
      if (hub) selectNode(hub);
    },
    [layout.nodes, selectNode]
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExplicitSelection("");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className={fallback ? "sceneShell radarShell fallbackMode" : "sceneShell radarShell"} aria-label="Content relationship map">
      {fallback ? (
        <>
          {children}
          <SceneFallback
            nodes={nodes}
            layout={layout}
            git={git}
            selectedPageId={activeSelectionId}
            highlightedIds={highlightedIds}
            intent={intent}
            census={census}
            onNodeSelect={onNodeSelect}
          />
        </>
      ) : (
        <>
          <IntentBar intent={intent} options={intentOptions} git={git} onIntentChange={onIntentChange} />
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
              onPointerMissed={() => setExplicitSelection("")}
            >
              <SceneContent
                layout={layout}
                edges={edges}
                git={git}
                profile={profile}
                selectedId={activeSelectionId}
                highlightedIds={highlightedIds}
                filter={filter}
                motion={motion}
                activityLevel={activityLevel}
                onSelect={selectNode}
                onHover={handleHover}
                onContextSelect={handleContextSelect}
              />
            </Canvas>
          </div>
          {children}
          <HoverTooltip hover={hover} />
          <SelectedCard node={explicitSelection ? selectedNode : null} onDismiss={() => setExplicitSelection("")} onAddToPacket={onAddToPacket} />
          <StatusStrip census={census} filter={filter} onFilter={setFilter} />
        </>
      )}
    </div>
  );
}
