import { OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import type { ThreeEvent } from "@react-three/fiber";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import type { GraphNode, GitState } from "../types";
import { computeGalaxyLayout, scenePerformanceProfile } from "../scene/layout";
import type { GalaxyLayout, LayoutNode, ScenePerformanceProfile } from "../scene/layout";

const COLORS = {
  proposal: "#c57cff",
  root: "#6bd7ff"
};

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

function freshnessLabel(state: string): string {
  if (state === "fresh") return "ok";
  if (state === "stale") return "needs refresh";
  return "not checked";
}

function contentKindLabel(kind: string): string {
  const labels: Record<string, string> = {
    root_index: "home map",
    context_hub: "area overview",
    operational_rule: "operating rule",
    source: "evidence source",
    dashboard: "dashboard",
    proposal: "review proposal"
  };
  return labels[kind] || kind.replaceAll("_", " ") || "content";
}

function workspaceLabel(git: GitState): string {
  if (git.proposal.is_proposal_branch) return git.proposal.theme ? `review: ${git.proposal.theme}` : "review workspace";
  if (git.current_branch === git.default_branch) return "approved workspace";
  return "current workspace";
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
  return useMemo(
    () => scenePerformanceProfile(nodeCount, snapshot),
    [nodeCount, snapshot]
  );
}

function useGalaxyLayout(nodes: GraphNode[], profile: ScenePerformanceProfile): GalaxyLayout {
  const [layout, setLayout] = useState<GalaxyLayout>(() => computeGalaxyLayout(nodes, profile.maxNodes));
  useEffect(() => {
    let active = true;
    const sync = () => {
      const next = computeGalaxyLayout(nodes, profile.maxNodes);
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
    worker.postMessage({ nodes, maxNodes: profile.maxNodes });
    return () => {
      active = false;
      worker.terminate();
    };
  }, [nodes, profile.maxNodes]);
  return layout;
}

function InstancedNodeMesh({
  items,
  profile,
  selectedId,
  highlightedIds,
  color,
  onSelect
}: {
  items: LayoutNode[];
  profile: ScenePerformanceProfile;
  selectedId: string;
  highlightedIds: Set<string>;
  color: string;
  onSelect: (node: LayoutNode) => void;
}) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const { invalidate } = useThree();
  const matrix = useMemo(() => new THREE.Matrix4(), []);
  const quaternion = useMemo(() => new THREE.Quaternion(), []);
  useLayoutEffect(() => {
    if (!ref.current) return;
    items.forEach((node, index) => {
      const selected = node.id === selectedId || node.path === selectedId ? 1.24 : highlightedIds.has(node.id) || highlightedIds.has(node.path) ? 1.12 : 1;
      matrix.compose(
        new THREE.Vector3(...node.position),
        quaternion,
        new THREE.Vector3(node.scale * selected, node.scale * selected, node.scale * selected)
      );
      ref.current?.setMatrixAt(index, matrix);
    });
    ref.current.instanceMatrix.needsUpdate = true;
    invalidate();
  }, [highlightedIds, invalidate, items, matrix, quaternion, selectedId]);
  const handleClick = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    if (typeof event.instanceId === "number" && items[event.instanceId]) {
      onSelect(items[event.instanceId]);
    }
  };
  return (
    <instancedMesh ref={ref} args={[undefined, undefined, Math.max(items.length, 1)]} onClick={handleClick}>
      <sphereGeometry args={[1, profile.geometrySegments, profile.geometrySegments]} />
      <meshBasicMaterial color={color} toneMapped={false} />
    </instancedMesh>
  );
}

function InstancedNodeLayer({
  items,
  profile,
  selectedId,
  highlightedIds,
  onSelect
}: {
  items: LayoutNode[];
  profile: ScenePerformanceProfile;
  selectedId: string;
  highlightedIds: Set<string>;
  onSelect: (node: LayoutNode) => void;
}) {
  const groups = useMemo(() => {
    const byColor = new Map<string, LayoutNode[]>();
    for (const item of items) {
      const group = byColor.get(item.color) || [];
      group.push(item);
      byColor.set(item.color, group);
    }
    return [...byColor.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [items]);
  return (
    <>
      {groups.map(([color, group]) => (
        <InstancedNodeMesh key={color} items={group} profile={profile} selectedId={selectedId} highlightedIds={highlightedIds} color={color} onSelect={onSelect} />
      ))}
    </>
  );
}

function ContextAnchors({ layout }: { layout: GalaxyLayout }) {
  return (
    <>
      {layout.contextAnchors.map((anchor) => (
        <mesh key={anchor.context} position={anchor.position} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[0.34 + Math.min(anchor.count, 8) * 0.025, 0.008, 8, 48]} />
          <meshBasicMaterial color="#2f6373" transparent opacity={0.7} />
        </mesh>
      ))}
    </>
  );
}

function GateRing({ git }: { git: GitState }) {
  const color = git.proposal.is_proposal_branch ? COLORS.proposal : COLORS.root;
  return (
    <mesh rotation={[Math.PI / 2, 0, 0]}>
      <torusGeometry args={[1.35, 0.025, 16, 96]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.36} />
    </mesh>
  );
}

function SelectedRoute({ node }: { node: LayoutNode | null }) {
  const route = useMemo(() => {
    const points = [new THREE.Vector3(0, 0, 0), new THREE.Vector3(...(node?.position || [0, 0, 0]))];
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({ color: "#dff8ff", transparent: true, opacity: 0.88 });
    return { line: new THREE.Line(geometry, material), geometry, material };
  }, [node]);
  useEffect(() => {
    return () => {
      route.geometry.dispose();
      route.material.dispose();
    };
  }, [route]);
  if (!node) return null;
  return <primitive object={route.line} />;
}

function CameraIntro({ enabled }: { enabled: boolean }) {
  const { camera } = useThree();
  const started = useRef<number | null>(null);
  const done = useRef(!enabled);
  useEffect(() => {
    done.current = !enabled;
    started.current = null;
  }, [enabled]);
  useFrame((state) => {
    if (done.current) return;
    const now = state.clock.elapsedTime;
    if (started.current === null) started.current = now;
    const t = Math.min(1, (now - started.current) / 0.65);
    const eased = 1 - Math.pow(1 - t, 3);
    camera.position.set(
      THREE.MathUtils.lerp(0, 0, eased),
      THREE.MathUtils.lerp(4.2, 2.6, eased),
      THREE.MathUtils.lerp(7.2, 5.3, eased)
    );
    camera.lookAt(0, 0, 0);
    state.invalidate();
    if (t >= 1) done.current = true;
  });
  return null;
}

function SceneContent({
  layout,
  git,
  profile,
  selectedId,
  highlightedIds,
  onSelect
}: {
  layout: GalaxyLayout;
  git: GitState;
  profile: ScenePerformanceProfile;
  selectedId: string;
  highlightedIds: Set<string>;
  onSelect: (node: LayoutNode) => void;
}) {
  const selectedNode = layout.nodes.find((node) => node.id === selectedId || node.path === selectedId) || null;
  return (
    <>
      <color attach="background" args={["#0b1117"]} />
      <ambientLight intensity={0.72} />
      <pointLight position={[3, 4, 2]} intensity={2.1} color="#d9fff2" />
      <pointLight position={[-3, -2, -3]} intensity={0.8} color="#ffdd9a" />
      <mesh>
        <sphereGeometry args={[0.48, profile.geometrySegments + 8, profile.geometrySegments + 8]} />
        <meshStandardMaterial color={COLORS.root} emissive={COLORS.root} emissiveIntensity={0.42} roughness={0.34} />
      </mesh>
      <ContextAnchors layout={layout} />
      <GateRing git={git} />
      <SelectedRoute node={selectedNode} />
      <InstancedNodeLayer items={layout.nodes} profile={profile} selectedId={selectedId} highlightedIds={highlightedIds} onSelect={onSelect} />
      <CameraIntro enabled={profile.enableIntro} />
      <OrbitControls enablePan={false} minDistance={3.2} maxDistance={7.8} enableDamping={profile.quality !== "compact"} />
    </>
  );
}

function SceneFallback({
  nodes,
  git,
  selectedPageId,
  highlightedIds,
  onNodeSelect
}: {
  nodes: GraphNode[];
  git: GitState;
  selectedPageId: string;
  highlightedIds: Set<string>;
  onNodeSelect?: (nodeId: string) => void;
}) {
  const visibleNodes = nodes.slice(0, 8);
  return (
    <div className="sceneFallback" aria-label="Content map">
      <div className="fallbackCore">
        <strong>{git.proposal.is_proposal_branch ? "Draft change" : "Approved content"}</strong>
        <span>{workspaceLabel(git)}</span>
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

function SceneProof({ node, layout, profile }: { node: LayoutNode | null; layout: GalaxyLayout; profile: ScenePerformanceProfile }) {
  if (!node) return null;
  return (
    <div className="sceneProof" aria-live="polite">
      <strong>{node.title}</strong>
      <span>{node.context} · {contentKindLabel(node.page_type)} · {freshnessLabel(node.freshness_state)}</span>
      <code>{node.path}</code>
      <small>{profile.label} · {layout.nodes.length} nodes{layout.truncated ? ` · ${layout.truncated} hidden` : ""}</small>
    </div>
  );
}

export function SystemScene({
  nodes,
  git,
  selectedPageId = "",
  highlightedPageIds = [],
  onNodeSelect
}: {
  nodes: GraphNode[];
  git: GitState;
  selectedPageId?: string;
  highlightedPageIds?: string[];
  onNodeSelect?: (nodeId: string) => void;
}) {
  const [fallback, setFallback] = useState(shouldUseFallback);
  const profile = useSceneProfile(nodes.length);
  const layout = useGalaxyLayout(nodes, profile);
  const [selected, setSelected] = useState<LayoutNode | null>(null);
  const highlightedIds = useMemo(() => new Set(highlightedPageIds), [highlightedPageIds]);
  useEffect(() => {
    if (!layout.nodes.length) return;
    const externalSelection = selectedPageId ? layout.nodes.find((node) => node.id === selectedPageId || node.path === selectedPageId) : null;
    if (externalSelection && selected?.id !== externalSelection.id) {
      setSelected(externalSelection);
      return;
    }
    if (!selected || !layout.nodes.some((node) => node.id === selected.id)) {
      const highlighted = highlightedPageIds.length
        ? layout.nodes.find((node) => highlightedIds.has(node.id) || highlightedIds.has(node.path))
        : null;
      setSelected(highlighted || layout.nodes[0]);
    }
  }, [highlightedIds, highlightedPageIds.length, layout.nodes, selected, selectedPageId]);
  const selectNode = (node: LayoutNode) => {
    setSelected(node);
    onNodeSelect?.(node.id);
  };
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setFallback(shouldUseFallback());
    update();
    media.addEventListener?.("change", update);
    window.addEventListener("popstate", update);
    return () => {
      media.removeEventListener?.("change", update);
      window.removeEventListener("popstate", update);
    };
  }, []);

  return (
    <div className="sceneShell" aria-label="Content relationship map">
      {fallback ? (
        <SceneFallback nodes={nodes} git={git} selectedPageId={selectedPageId || selected?.id || ""} highlightedIds={highlightedIds} onNodeSelect={onNodeSelect} />
      ) : (
        <>
          <Canvas
            camera={{ position: [0, 2.6, 5.3], fov: 46 }}
            dpr={profile.dpr}
            frameloop="demand"
            gl={{ antialias: profile.quality !== "compact", powerPreference: "high-performance" }}
          >
            <SceneContent layout={layout} git={git} profile={profile} selectedId={selectedPageId || selected?.id || ""} highlightedIds={highlightedIds} onSelect={selectNode} />
          </Canvas>
          <SceneProof node={selected} layout={layout} profile={profile} />
        </>
      )}
    </div>
  );
}
