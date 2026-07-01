import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import type { GraphNode, GitState } from "../types";

const COLORS = {
  fresh: "#5ee6a8",
  stale: "#ffb454",
  unknown: "#9aa3b2",
  proposal: "#c57cff",
  root: "#6bd7ff"
};

function NodeOrb({ node, index, total }: { node: GraphNode; index: number; total: number }) {
  const ref = useRef<THREE.Mesh>(null);
  const angle = (index / Math.max(total, 1)) * Math.PI * 2;
  const radius = 2.25 + (index % 4) * 0.42;
  const position = useMemo<[number, number, number]>(
    () => [Math.cos(angle) * radius, Math.sin(index * 1.7) * 0.34, Math.sin(angle) * radius],
    [angle, index, radius]
  );
  useFrame(({ clock }) => {
    if (!ref.current) return;
    const pulse = 1 + Math.sin(clock.elapsedTime * 1.4 + index) * 0.045;
    ref.current.scale.setScalar(pulse);
  });
  const color = COLORS[node.freshness_state] ?? COLORS.unknown;
  const size = node.page_type === "root_index" ? 0.28 : 0.16 + Math.min(node.metrics.outbound_links, 5) * 0.025;
  return (
    <mesh ref={ref} position={position} userData={{ title: node.title }}>
      <sphereGeometry args={[size, 24, 24]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.28} roughness={0.42} />
    </mesh>
  );
}

function GateRing({ git }: { git: GitState }) {
  const ref = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    if (!ref.current) return;
    ref.current.rotation.z = clock.elapsedTime * 0.12;
  });
  const color = git.proposal.is_proposal_branch ? COLORS.proposal : COLORS.root;
  return (
    <mesh ref={ref} rotation={[Math.PI / 2, 0, 0]}>
      <torusGeometry args={[1.35, 0.025, 16, 96]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.36} />
    </mesh>
  );
}

function SceneContent({ nodes, git }: { nodes: GraphNode[]; git: GitState }) {
  const visibleNodes = nodes.slice(0, 52);
  return (
    <>
      <color attach="background" args={["#0b1117"]} />
      <ambientLight intensity={0.7} />
      <pointLight position={[3, 4, 2]} intensity={2.1} color="#d9fff2" />
      <pointLight position={[-3, -2, -3]} intensity={0.8} color="#ffdd9a" />
      <mesh>
        <sphereGeometry args={[0.56, 32, 32]} />
        <meshStandardMaterial color={COLORS.root} emissive={COLORS.root} emissiveIntensity={0.42} roughness={0.34} />
      </mesh>
      <GateRing git={git} />
      {visibleNodes.map((node, index) => (
        <NodeOrb key={`${node.id}-${node.path}`} node={node} index={index} total={visibleNodes.length} />
      ))}
      <OrbitControls enablePan={false} minDistance={3.2} maxDistance={7.8} enableDamping />
    </>
  );
}

export function SystemScene({ nodes, git }: { nodes: GraphNode[]; git: GitState }) {
  return (
    <div className="sceneShell" aria-label="Operational 3D wiki state">
      <Canvas camera={{ position: [0, 2.6, 5.3], fov: 46 }} dpr={[1, 1.75]}>
        <SceneContent nodes={nodes} git={git} />
      </Canvas>
    </div>
  );
}
