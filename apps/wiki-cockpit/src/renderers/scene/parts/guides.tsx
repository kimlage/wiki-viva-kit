// Reference geometry: the world's static guide lines — level rings/arcs/rays,
// the freshness danger zone, proposal stems, the gate torus and the quadrant
// floor frame. Read-only decoration derived from the layout; no interaction
// besides the labels' own buttons.

import { Html } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import type { RefObject } from "react";
import * as THREE from "three";
import { t } from "../../../data/i18n";
import { contextStyle, edgeStyle, pageTypeStyle, trustColor } from "../../../data/presentation";
import { QUADRANT_CENTER_ANGLE, SCENE_FACETS } from "../../../scene/facets";
import type { GitState } from "../../../types";
import type { LayoutNode } from "../../../scene/layout";
import type { WorldLayout } from "../../../scene/perspectives";
import type { GroupRelationBundle, RelationLane } from "./materials";
import { morphAttachmentOpacity } from "./nodes";
import type { MorphState } from "./nodes";

export type DensityPressureSpec = {
  intensity: number;
  memberCount: number;
  hiddenCount: number;
  markerCount: number;
  radius: number;
  color: string;
};

export type DensityReliefSpec = {
  color: string;
  gridCount: number;
  opacity: number;
  radius: number;
  rimOpacity: number;
};

export type AggregateStateRimSlice = {
  key: "risk" | "stale" | "proposal" | "unknown" | "fresh";
  beadCount: number;
  color: string;
  count: number;
  end: number;
  share: number;
  start: number;
};

export type AggregateStateRimSpec = {
  radius: number;
  slices: AggregateStateRimSlice[];
  total: number;
};

export type HiddenDepthHaloSpec = {
  color: string;
  compression: number;
  hiddenCount: number;
  layerCount: number;
  opacity: number;
  radius: number;
  spokeCount: number;
};

export type FocusContextSpec = {
  color: string;
  lift: number;
  mode: "hover" | "lock";
  radius: number;
  ringCount: number;
  tickCount: number;
};

export type InspectionBeamSpec = {
  key: "evidence" | "links" | "risk" | "freshness" | "group";
  color: string;
  intensity: number;
  lift: number;
  radius: number;
  spokeCount: number;
};

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

export function densityPressureSpec(layout: WorldLayout): DensityPressureSpec | null {
  if (layout.perspective !== "quadrants" || layout.level < 1) return null;
  const center = layout.nodes.find((node) => node.isRoot && node.isGroup) ?? layout.nodes.find((node) => node.isRoot);
  if (!center?.isGroup) return null;
  const memberCount = center.groupMemberIds?.length ?? layout.totals.total;
  const hiddenCount = layout.clusterStars.reduce((sum, star) => sum + star.count, 0);
  const pressure = memberCount + hiddenCount * 0.7 + Math.max(0, layout.truncated) * 0.5;
  if (pressure < 12) return null;
  const intensity = Math.min(1, Math.max(0.18, pressure / 80));
  const markerCount = Math.max(6, Math.min(28, Math.round(6 + Math.sqrt(pressure) * 2.1)));
  const groupFamily = center.groupKind === "region_family" ? center.groupLabelKey || "source" : center.groupKind || "region";
  const color = groupFamily === "source" ? "#5ee6b7" : groupFamily === "event" ? "#ffcf6b" : groupFamily === "person" ? "#a890ff" : "#6bd7ff";
  return {
    intensity,
    memberCount,
    hiddenCount,
    markerCount,
    radius: Math.max(center.scale * 2.1, layout.rInner + (layout.rOuter - layout.rInner) * 0.24),
    color
  };
}

export function densityReliefSpec(layout: WorldLayout): DensityReliefSpec | null {
  const pressure = densityPressureSpec(layout);
  if (!pressure || pressure.intensity < 0.38) return null;
  const totalMass = pressure.memberCount + pressure.hiddenCount;
  return {
    color: pressure.color,
    gridCount: Math.max(8, Math.min(18, Math.round(6 + Math.sqrt(totalMass) * 1.35))),
    opacity: Number((0.08 + pressure.intensity * 0.11).toFixed(4)),
    radius: Number((pressure.radius * (1.14 + pressure.intensity * 0.14)).toFixed(4)),
    rimOpacity: Number((0.1 + pressure.intensity * 0.16).toFixed(4))
  };
}

export function aggregateStateRimSpec(layout: WorldLayout): AggregateStateRimSpec | null {
  const pressure = densityPressureSpec(layout);
  if (!pressure || layout.clusterStars.length === 0) return null;
  const totals = layout.clusterStars.reduce(
    (acc, star) => {
      acc.fresh += star.histogram.fresh;
      acc.stale += star.histogram.stale;
      acc.unknown += star.histogram.unknown;
      acc.proposal += star.histogram.proposal;
      acc.risk += star.histogram.risk;
      return acc;
    },
    { fresh: 0, stale: 0, unknown: 0, proposal: 0, risk: 0 }
  );
  const order: AggregateStateRimSlice["key"][] = ["risk", "stale", "proposal", "unknown", "fresh"];
  const total = order.reduce((sum, key) => sum + totals[key], 0);
  if (total < 3) return null;
  const gap = Math.PI * 0.018;
  let cursor = -Math.PI / 2;
  const slices = order
    .filter((key) => totals[key] > 0)
    .map((key) => {
      const count = totals[key];
      const share = count / total;
      const length = Math.max(share * Math.PI * 2 - gap, Math.PI * 0.045);
      const start = cursor;
      const end = cursor + length;
      cursor = end + gap;
      return {
        key,
        beadCount: Math.max(1, Math.min(8, Math.ceil(Math.sqrt(count)))),
        color: trustColor(key),
        count,
        end: Number(end.toFixed(4)),
        share: Number(share.toFixed(4)),
        start: Number(start.toFixed(4))
      };
    });
  return {
    radius: Number((pressure.radius * 1.08).toFixed(4)),
    slices,
    total
  };
}

export function hiddenDepthHaloSpec(layout: WorldLayout): HiddenDepthHaloSpec | null {
  const pressure = densityPressureSpec(layout);
  if (!pressure) return null;
  const hiddenCount = pressure.hiddenCount + Math.max(0, layout.truncated);
  if (hiddenCount < 6) return null;
  const visibleCount = Math.max(pressure.memberCount, 1);
  const compression = Math.min(1, hiddenCount / (visibleCount + hiddenCount));
  return {
    color: pressure.color,
    compression: Number(compression.toFixed(4)),
    hiddenCount,
    layerCount: Math.max(2, Math.min(6, Math.ceil(Math.sqrt(hiddenCount) / 2))),
    opacity: Number((0.08 + compression * 0.16).toFixed(4)),
    radius: Number((pressure.radius * (0.54 + compression * 0.18)).toFixed(4)),
    spokeCount: Math.max(6, Math.min(18, Math.round(6 + Math.sqrt(hiddenCount) * 1.25)))
  };
}


export function focusContextSpec(node: LayoutNode | null | undefined, mode: "hover" | "lock"): FocusContextSpec | null {
  if (!node) return null;
  const family = pageTypeStyle(node.page_type).family;
  const mass = Math.max(0, node.inbound_links + node.outbound_links + node.source_ref_count + node.risk_flags.length * 4);
  const ringCount = node.source_ref_count > 0 || family === "source" ? 3 : mass > 18 || node.isGroup ? 2 : 1;
  const tickCount = Math.max(4, Math.min(22, Math.round(4 + Math.sqrt(mass + (node.isGroup ? node.groupMemberIds?.length ?? 0 : 0)) * 1.8)));
  const familyColor = family === "source" ? edgeStyle("source_ref").color : pageTypeStyle(node.page_type).accent || contextStyle(node.context).accent;
  const stateColor = node.risk_flags.length > 0
    ? trustColor("risk")
    : node.approved_state === "proposal"
      ? trustColor("proposal")
      : node.freshness_state === "stale"
        ? trustColor("stale")
        : familyColor;
  return {
    color: stateColor,
    lift: Math.max(node.scale * 0.12, 0.035),
    mode,
    radius: Number((node.scale * (node.isGroup ? 1.52 : 1.15) + Math.min(0.34, Math.log2(mass + 1) * 0.034)).toFixed(4)),
    ringCount,
    tickCount
  };
}

export function inspectionBeamSpecs(node: LayoutNode | null | undefined): InspectionBeamSpec[] {
  if (!node) return [];
  const specs: InspectionBeamSpec[] = [];
  const baseRadius = node.scale * (node.isGroup ? 1.7 : 1.34);
  const lift = Math.max(node.scale * 0.22, 0.07);
  const push = (spec: Omit<InspectionBeamSpec, "lift" | "radius">, radiusGain = 0) => {
    specs.push({
      ...spec,
      lift,
      radius: Number((baseRadius + radiusGain).toFixed(4))
    });
  };
  if (node.isGroup) {
    const count = node.groupMemberIds?.length ?? 0;
    push({
      key: "group",
      color: pageTypeStyle(node.page_type).accent || contextStyle(node.context).accent,
      intensity: Math.min(1, Math.max(0.28, count / 48)),
      spokeCount: Math.max(5, Math.min(24, Math.round(5 + Math.sqrt(count) * 2)))
    });
  }
  if (node.source_ref_count > 0) {
    push({
      key: "evidence",
      color: edgeStyle("source_ref").color,
      intensity: Math.min(1, Math.max(0.34, node.source_ref_count / 16)),
      spokeCount: Math.max(3, Math.min(16, Math.ceil(Math.sqrt(node.source_ref_count) * 3)))
    }, 0.12);
  }
  const linkMass = node.inbound_links + node.outbound_links;
  if (linkMass > 0) {
    push({
      key: "links",
      color: contextStyle(node.context).accent,
      intensity: Math.min(0.92, Math.max(0.22, linkMass / 28)),
      spokeCount: Math.max(3, Math.min(18, Math.round(3 + Math.sqrt(linkMass) * 2.2)))
    }, 0.24);
  }
  if (node.risk_flags.length > 0) {
    push({
      key: "risk",
      color: trustColor("risk"),
      intensity: Math.min(1, 0.55 + node.risk_flags.length * 0.16),
      spokeCount: Math.max(4, Math.min(12, node.risk_flags.length * 4))
    }, 0.36);
  }
  if (node.approved_state === "proposal" || node.freshness_state === "stale" || node.freshness_state === "unknown") {
    const key = node.approved_state === "proposal" ? "proposal" : node.freshness_state;
    push({
      key: "freshness",
      color: trustColor(key),
      intensity: node.approved_state === "proposal" ? 0.72 : node.freshness_state === "stale" ? 0.62 : 0.42,
      spokeCount: node.approved_state === "proposal" ? 7 : node.freshness_state === "stale" ? 6 : 4
    }, 0.48);
  }
  return specs.slice(0, 5);
}

export function InspectionBeams({ node, motion }: { node: LayoutNode | null | undefined; motion: boolean }) {
  const specs = useMemo(() => inspectionBeamSpecs(node), [node]);
  const ref = useRef<THREE.Group>(null);
  useFrame((state) => {
    if (!motion || !ref.current || specs.length === 0) return;
    ref.current.rotation.y = Math.sin(state.clock.elapsedTime * 0.5) * 0.08;
    state.invalidate();
  });
  if (!node || specs.length === 0) return null;
  const baseY = node.position[1] + Math.max(node.scale * 0.2, 0.06);
  return (
    <group ref={ref} position={[node.position[0], baseY, node.position[2]]} renderOrder={7}>
      {specs.map((spec, specIndex) => (
        <group key={`${node.id}-inspect-${spec.key}-${specIndex}`} rotation={[0, specIndex * 0.42, 0]}>
          {Array.from({ length: spec.spokeCount }, (_, index) => {
            const angle = (index / spec.spokeCount) * Math.PI * 2;
            const inner = spec.radius * 0.42;
            const outer = spec.radius * (0.78 + spec.intensity * 0.26);
            const y = spec.lift + (index % 2) * 0.035 + specIndex * 0.012;
            const points = [
              new THREE.Vector3(Math.cos(angle) * inner, y, Math.sin(angle) * inner),
              new THREE.Vector3(Math.cos(angle) * outer, y + 0.035 * spec.intensity, Math.sin(angle) * outer)
            ];
            return <StaticLine key={`${spec.key}-${index}`} points={points} color={spec.color} opacity={0.16 + spec.intensity * 0.24} />;
          })}
        </group>
      ))}
    </group>
  );
}

export function FocusContextField({ node, mode, motion }: { node: LayoutNode | null | undefined; mode: "hover" | "lock"; motion: boolean }) {
  const spec = useMemo(() => focusContextSpec(node, mode), [mode, node]);
  const ref = useRef<THREE.Group>(null);
  useFrame((state) => {
    if (!motion || !ref.current || !spec) return;
    ref.current.rotation.y = state.clock.elapsedTime * (spec.mode === "lock" ? 0.12 : 0.18);
    const pulse = 1 + Math.sin(state.clock.elapsedTime * (spec.mode === "lock" ? 1.2 : 1.8)) * (spec.mode === "lock" ? 0.018 : 0.026);
    ref.current.scale.setScalar(pulse);
    state.invalidate();
  });
  if (!node || !spec) return null;
  const position: [number, number, number] = [node.position[0], node.position[1] + spec.lift, node.position[2]];
  const ringOpacity = spec.mode === "lock" ? 0.34 : 0.22;
  const tickOpacity = spec.mode === "lock" ? 0.56 : 0.38;
  return (
    <group ref={ref} position={position} renderOrder={6}>
      {Array.from({ length: spec.ringCount }, (_, index) => (
        <mesh key={`focus-ring-${node.id}-${index}`} rotation={[-Math.PI / 2, 0, 0]}>
          <torusGeometry args={[spec.radius + index * 0.095, 0.008 + index * 0.002, 6, 72]} />
          <meshBasicMaterial color={spec.color} transparent opacity={ringOpacity / (index + 1)} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
        </mesh>
      ))}
      {Array.from({ length: spec.tickCount }, (_, index) => {
        const angle = (index / spec.tickCount) * Math.PI * 2;
        const strong = index % Math.max(2, Math.floor(spec.tickCount / spec.ringCount)) === 0;
        const size = strong ? 0.055 : 0.034;
        const radius = spec.radius + spec.ringCount * 0.095 + (strong ? 0.025 : 0);
        return (
          <mesh key={`focus-tick-${node.id}-${index}`} position={[Math.cos(angle) * radius, strong ? 0.035 : 0.018, Math.sin(angle) * radius]} rotation={[0, -angle, 0]}>
            <boxGeometry args={[size * 0.42, size * 0.26, size]} />
            <meshBasicMaterial color={spec.color} transparent opacity={tickOpacity} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
          </mesh>
        );
      })}
    </group>
  );
}

export function DensityPressureField({ layout, motion }: { layout: WorldLayout; motion: boolean }) {
  const spec = useMemo(() => densityPressureSpec(layout), [layout]);
  const ringRef = useRef<THREE.Mesh>(null);
  const markerRef = useRef<THREE.Group>(null);
  useFrame((state) => {
    if (!motion || !spec) return;
    const elapsed = state.clock.elapsedTime;
    if (ringRef.current) {
      const pulse = 1 + Math.sin(elapsed * (0.45 + spec.intensity * 0.25)) * 0.025 * spec.intensity;
      ringRef.current.scale.setScalar(pulse);
    }
    if (markerRef.current) {
      markerRef.current.rotation.y = elapsed * (0.025 + spec.intensity * 0.035);
      markerRef.current.position.y = Math.sin(elapsed * 0.55) * 0.012 * spec.intensity;
    }
    state.invalidate();
  });
  if (!spec) return null;
  const inner = spec.radius;
  const outer = spec.radius + 0.08 + spec.intensity * 0.16;
  return (
    <group>
      <mesh ref={ringRef} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.018, 0]} renderOrder={2}>
        <ringGeometry args={[inner, outer, 128]} />
        <meshBasicMaterial color={spec.color} transparent opacity={0.035 + spec.intensity * 0.05} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} side={THREE.DoubleSide} />
      </mesh>
      <group ref={markerRef}>
        {Array.from({ length: spec.markerCount }, (_, index) => {
          const angle = (index / spec.markerCount) * Math.PI * 2;
          const large = index % 5 === 0;
          const radius = outer + (large ? 0.08 : 0);
          const mass = large ? 0.038 + spec.intensity * 0.026 : 0.022 + spec.intensity * 0.018;
          return (
            <mesh key={`density-pressure-${index}`} position={[Math.cos(angle) * radius, 0.04 + (large ? 0.025 : 0), Math.sin(angle) * radius]}>
              <boxGeometry args={[mass * 1.4, mass * 0.55, mass]} />
              <meshBasicMaterial color={spec.color} transparent opacity={0.18 + spec.intensity * 0.28} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
            </mesh>
          );
        })}
      </group>
    </group>
  );
}

export function DensityReliefField({ layout, motion }: { layout: WorldLayout; motion: boolean }) {
  const spec = useMemo(() => densityReliefSpec(layout), [layout]);
  const ref = useRef<THREE.Group>(null);
  useFrame((state) => {
    if (!motion || !ref.current || !spec) return;
    ref.current.rotation.y = Math.sin(state.clock.elapsedTime * 0.22) * 0.018;
    state.invalidate();
  });
  if (!spec) return null;
  return (
    <group ref={ref} renderOrder={1}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.006, 0]}>
        <circleGeometry args={[spec.radius, 96]} />
        <meshBasicMaterial color="#02080d" transparent opacity={spec.opacity} depthWrite={false} toneMapped={false} side={THREE.DoubleSide} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.009, 0]}>
        <ringGeometry args={[spec.radius * 0.92, spec.radius, 128]} />
        <meshBasicMaterial color={spec.color} transparent opacity={spec.rimOpacity} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} side={THREE.DoubleSide} />
      </mesh>
      {Array.from({ length: spec.gridCount }, (_, index) => {
        const angle = (index / spec.gridCount) * Math.PI * 2;
        const radius = spec.radius * (0.42 + (index % 3) * 0.16);
        const length = spec.radius * (index % 4 === 0 ? 0.24 : 0.14);
        return (
          <mesh
            key={`density-relief-grid-${index}`}
            position={[Math.cos(angle) * radius, 0.022, Math.sin(angle) * radius]}
            rotation={[0, -angle, 0]}
          >
            <boxGeometry args={[0.012, 0.008, length]} />
            <meshBasicMaterial color={spec.color} transparent opacity={0.12 + spec.rimOpacity * 0.38} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
          </mesh>
        );
      })}
    </group>
  );
}

export function HiddenDepthHalo({ layout, motion }: { layout: WorldLayout; motion: boolean }) {
  const spec = useMemo(() => hiddenDepthHaloSpec(layout), [layout]);
  const ref = useRef<THREE.Group>(null);
  useFrame((state) => {
    if (!motion || !ref.current || !spec) return;
    ref.current.rotation.y = Math.sin(state.clock.elapsedTime * 0.16) * 0.018;
    ref.current.position.y = Math.sin(state.clock.elapsedTime * 0.42) * 0.006;
    state.invalidate();
  });
  if (!spec) return null;
  return (
    <group ref={ref} renderOrder={2}>
      {Array.from({ length: spec.layerCount }, (_, index) => {
        const f = index / Math.max(spec.layerCount - 1, 1);
        const radius = spec.radius * (1 - f * 0.28);
        const y = 0.014 + index * 0.034;
        const opacity = spec.opacity * (1 - f * 0.42);
        return (
          <group key={`hidden-depth-layer-${index}`}>
            <StaticLine points={circlePoints(radius, 88, y)} color={spec.color} opacity={opacity} />
            <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, y - 0.004, 0]}>
              <ringGeometry args={[radius * 0.965, radius, 96]} />
              <meshBasicMaterial color={spec.color} transparent opacity={opacity * 0.22} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} side={THREE.DoubleSide} />
            </mesh>
          </group>
        );
      })}
      {Array.from({ length: spec.spokeCount }, (_, index) => {
        const angle = (index / spec.spokeCount) * Math.PI * 2;
        const outer = spec.radius * (0.98 + (index % 3) * 0.03);
        const inner = spec.radius * (0.52 + (index % 2) * 0.06);
        const y0 = 0.018;
        const y1 = 0.062 + spec.compression * 0.11;
        const points = [
          new THREE.Vector3(Math.cos(angle) * outer, y0, Math.sin(angle) * outer),
          new THREE.Vector3(Math.cos(angle) * inner, y1, Math.sin(angle) * inner)
        ];
        return <StaticLine key={`hidden-depth-spoke-${index}`} points={points} color={spec.color} opacity={spec.opacity * 0.58} />;
      })}
    </group>
  );
}

export function AggregateStateRim({ layout, motion }: { layout: WorldLayout; motion: boolean }) {
  const spec = useMemo(() => aggregateStateRimSpec(layout), [layout]);
  const ref = useRef<THREE.Group>(null);
  useFrame((state) => {
    if (!motion || !ref.current || !spec) return;
    ref.current.rotation.y = Math.sin(state.clock.elapsedTime * 0.18) * 0.012;
    state.invalidate();
  });
  if (!spec) return null;
  return (
    <group ref={ref} renderOrder={3}>
      {spec.slices.map((slice) => {
        const points = arcPoints(spec.radius, slice.start, slice.end, 36, 0.052);
        return (
          <group key={`aggregate-state-rim-${slice.key}`}>
            <StaticLine points={points} color={slice.color} opacity={0.28 + Math.min(slice.share, 0.6) * 0.42} />
            {Array.from({ length: slice.beadCount }, (_, index) => {
              const t = slice.beadCount === 1 ? 0.5 : index / (slice.beadCount - 1);
              const angle = slice.start + (slice.end - slice.start) * t;
              const strong = slice.key === "risk" || slice.key === "stale";
              const size = (strong ? 0.036 : 0.026) + Math.min(slice.share, 0.45) * 0.025;
              return (
                <mesh key={`aggregate-state-bead-${slice.key}-${index}`} position={[Math.cos(angle) * spec.radius, strong ? 0.082 : 0.066, Math.sin(angle) * spec.radius]}>
                  <sphereGeometry args={[size, 8, 6]} />
                  <meshBasicMaterial color={slice.color} transparent opacity={strong ? 0.74 : 0.56} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
                </mesh>
              );
            })}
          </group>
        );
      })}
    </group>
  );
}

function RelationLaneArc({
  lane,
  index,
  total,
  center,
  level,
  motion
}: {
  lane: RelationLane;
  index: number;
  total: number;
  center: [number, number, number];
  level: number;
  motion: boolean;
}) {
  const groupRef = useRef<THREE.Group>(null);
  const color = edgeStyle(lane.type).color;
  const radius = (level >= 2 ? 1.16 : 1.34) + index * 0.16;
  const y = 0.12 + index * 0.055;
  const start = -Math.PI * 0.82 + index * 0.18;
  const length = Math.max(Math.PI * 0.34, Math.min(Math.PI * 1.72, lane.share * Math.PI * 2.05));
  const points = useMemo(() => arcPoints(radius, start, start + length, 44, y), [length, radius, start, y]);
  const beadCount = Math.max(1, Math.min(9, Math.ceil(Math.sqrt(lane.count))));
  useFrame((state) => {
    if (!motion || !groupRef.current) return;
    groupRef.current.rotation.y = Math.sin(state.clock.elapsedTime * 0.35 + index) * 0.018;
    state.invalidate();
  });
  return (
    <group ref={groupRef} position={center}>
      <StaticLine points={points} color={color} opacity={0.62 - index * 0.08} />
      {Array.from({ length: beadCount }, (_, beadIndex) => {
        const t = beadCount === 1 ? 0.5 : beadIndex / (beadCount - 1);
        const angle = start + length * t;
        const mass = Math.min(Math.sqrt(lane.count) / 5, 1);
        return (
          <mesh key={`${lane.type}-lane-bead-${beadIndex}`} position={[Math.cos(angle) * radius, y + 0.035, Math.sin(angle) * radius]}>
            <sphereGeometry args={[0.035 + mass * 0.018, 8, 8]} />
            <meshBasicMaterial color={color} transparent opacity={0.78 - index * 0.07} toneMapped={false} />
          </mesh>
        );
      })}
      {index === total - 1 && (
        <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, -0.015, 0]}>
          <ringGeometry args={[radius + 0.1, radius + 0.105, 96]} />
          <meshBasicMaterial color="#dff8ff" transparent opacity={0.08} depthWrite={false} toneMapped={false} side={THREE.DoubleSide} />
        </mesh>
      )}
    </group>
  );
}

function bundleCurvePoints(bundle: GroupRelationBundle, index: number): THREE.Vector3[] {
  const from = new THREE.Vector3(...bundle.from);
  const to = new THREE.Vector3(...bundle.to);
  const distance = from.distanceTo(to);
  const side = new THREE.Vector3(to.z - from.z, 0, from.x - to.x).normalize();
  const sideOffset = side.lengthSq() > 0 ? side.multiplyScalar((index % 2 === 0 ? 1 : -1) * Math.min(0.16 + index * 0.035, 0.34)) : side;
  const control = from
    .clone()
    .lerp(to, 0.52)
    .add(sideOffset);
  control.y += Math.min(Math.max(distance * 0.15, 0.24), 0.72);
  return new THREE.QuadraticBezierCurve3(from, control, to).getPoints(36);
}

export type GroupRelationBundleVisualSpec = {
  beadCount: number;
  haloOpacity: number;
  haloRadius: number;
  opacity: number;
  particleRadius: number;
  tubeRadius: number;
};

export function groupRelationBundleVisualSpec(bundle: Pick<GroupRelationBundle, "count" | "share">): GroupRelationBundleVisualSpec {
  const mass = Math.min(Math.sqrt(Math.max(bundle.count, 1)) / 12, 1);
  const share = Math.min(Math.max(bundle.share, 0), 1);
  return {
    beadCount: Math.max(1, Math.min(7, Math.ceil(Math.sqrt(Math.max(bundle.count, 1)) / 3))),
    haloOpacity: Number((0.035 + share * 0.09).toFixed(4)),
    haloRadius: Number((0.038 + mass * 0.038 + share * 0.016).toFixed(4)),
    opacity: Number(Math.min(0.42, 0.11 + share * 0.36).toFixed(4)),
    particleRadius: Number((0.026 + mass * 0.032).toFixed(4)),
    tubeRadius: Number((0.012 + mass * 0.024 + share * 0.012).toFixed(4))
  };
}

function pointAlong(points: THREE.Vector3[], t: number): THREE.Vector3 {
  const safeT = Math.min(Math.max(t, 0), 1);
  const scaled = safeT * Math.max(points.length - 1, 1);
  const index = Math.floor(scaled);
  const next = Math.min(index + 1, points.length - 1);
  const local = scaled - index;
  return points[index].clone().lerp(points[next], local);
}

export function travelWakeCurvePoints(
  from: [number, number, number],
  to: [number, number, number],
  level: number
): THREE.Vector3[] {
  const start = new THREE.Vector3(...from);
  const end = new THREE.Vector3(...to);
  const distance = start.distanceTo(end);
  if (distance < 0.08) return [start, end];
  const side = new THREE.Vector3(end.z - start.z, 0, start.x - end.x).normalize();
  const control = start
    .clone()
    .lerp(end, 0.48)
    .add(side.multiplyScalar(Math.min(distance * 0.1, 0.42)));
  control.y += Math.min(Math.max(distance * 0.18, level >= 2 ? 0.38 : 0.28), level >= 2 ? 1.0 : 0.78);
  return new THREE.QuadraticBezierCurve3(start, control, end).getPoints(42);
}

export function travelWakeLevel(layoutLevel: number, hasLockedTarget: boolean): number {
  return hasLockedTarget ? Math.max(layoutLevel, 1) : layoutLevel;
}

export function TravelWake({
  from,
  to,
  level,
  color = "#dff8ff",
  motion
}: {
  from: [number, number, number] | null;
  to: [number, number, number];
  level: number;
  color?: string;
  motion: boolean;
}) {
  const ref = useRef<THREE.Group>(null);
  const beadRefs = useRef<THREE.Mesh[]>([]);
  const points = useMemo(() => (from && level > 0 ? travelWakeCurvePoints(from, to, level) : []), [from, level, to]);
  const distance = useMemo(() => {
    if (!from) return 0;
    return new THREE.Vector3(...from).distanceTo(new THREE.Vector3(...to));
  }, [from, to]);
  const beadCount = Math.max(2, Math.min(5, Math.ceil(distance * 1.1)));
  useFrame((state) => {
    if (!motion || !ref.current || points.length < 2) return;
    const pulse = Math.sin(state.clock.elapsedTime * 1.4);
    ref.current.position.y = pulse * 0.012;
    beadRefs.current.forEach((mesh, beadIndex) => {
      const t = (state.clock.elapsedTime * 0.24 + beadIndex / beadCount) % 1;
      const point = pointAlong(points, t);
      mesh.position.set(point.x, point.y + 0.035, point.z);
    });
    state.invalidate();
  });
  if (!from || level <= 0 || points.length < 2 || distance < 0.08) return null;
  return (
    <group ref={ref}>
      <StaticLine points={points} color={color} opacity={level >= 2 ? 0.28 : 0.22} />
      <mesh position={from} rotation={[Math.PI / 2, 0, 0]} renderOrder={6}>
        <ringGeometry args={[0.09, 0.12, 24]} />
        <meshBasicMaterial color={color} transparent opacity={0.28} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} side={THREE.DoubleSide} />
      </mesh>
      {Array.from({ length: beadCount }, (_, beadIndex) => {
        const t = beadCount === 1 ? 0.5 : beadIndex / (beadCount - 1);
        const point = pointAlong(points, t);
        return (
          <mesh
            key={`travel-wake-bead-${beadIndex}`}
            ref={(mesh) => {
              if (mesh) beadRefs.current[beadIndex] = mesh;
            }}
            position={[point.x, point.y + 0.035, point.z]}
            renderOrder={6}
          >
            <sphereGeometry args={[0.035, 8, 8]} />
            <meshBasicMaterial color={color} transparent opacity={0.58} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
          </mesh>
        );
      })}
    </group>
  );
}

export type ParentDrillGateSpec = {
  position: [number, number, number];
  yaw: number;
  radius: number;
};

export function parentDrillGateSpec(layout: WorldLayout, travelVia: [number, number, number] | null): ParentDrillGateSpec | null {
  if (layout.perspective !== "quadrants" || layout.level < 1) return null;
  const center = layout.nodes.find((node) => node.isRoot && node.isGroup) ?? layout.nodes.find((node) => node.isRoot);
  if (!center) return null;
  const origin = travelVia && Math.hypot(travelVia[0] - center.position[0], travelVia[2] - center.position[2]) > 0.2
    ? new THREE.Vector3(travelVia[0], 0, travelVia[2])
    : new THREE.Vector3(0, 0, layout.level >= 2 ? -1 : 1);
  const direction = origin.sub(new THREE.Vector3(center.position[0], 0, center.position[2]));
  if (direction.lengthSq() < 0.001) direction.set(0, 0, layout.level >= 2 ? -1 : 1);
  direction.normalize();
  const distance = Math.max(layout.rOuter + (layout.level >= 2 ? 1.35 : 1.05), layout.level >= 2 ? 4.75 : 4.35);
  const position: [number, number, number] = [
    Number((center.position[0] + direction.x * distance).toFixed(4)),
    Number((0.42 + layout.level * 0.08).toFixed(4)),
    Number((center.position[2] + direction.z * distance).toFixed(4))
  ];
  const yaw = Math.atan2(-direction.x, -direction.z);
  return {
    position,
    yaw: Number(yaw.toFixed(4)),
    radius: Number((layout.level >= 2 ? 0.42 : 0.36).toFixed(4))
  };
}

export function parentDrillPathCurvePoints(layout: WorldLayout, travelVia: [number, number, number] | null): THREE.Vector3[] {
  const gate = parentDrillGateSpec(layout, travelVia);
  if (!gate) return [];
  const center = layout.nodes.find((node) => node.isRoot && node.isGroup) ?? layout.nodes.find((node) => node.isRoot);
  if (!center) return [];
  const start = new THREE.Vector3(gate.position[0], Math.max(gate.position[1], 0.3), gate.position[2]);
  const end = new THREE.Vector3(center.position[0], Math.max(center.position[1] + center.scale * 0.8, 0.36), center.position[2]);
  const distance = start.distanceTo(end);
  if (distance < 0.08) return [start, end];
  const side = new THREE.Vector3(end.z - start.z, 0, start.x - end.x).normalize();
  const control = start
    .clone()
    .lerp(end, 0.5)
    .add(side.multiplyScalar(Math.min(distance * 0.045, 0.22)));
  control.y += Math.min(Math.max(distance * 0.12, layout.level >= 2 ? 0.54 : 0.42), layout.level >= 2 ? 1.05 : 0.82);
  return new THREE.QuadraticBezierCurve3(start, control, end).getPoints(52);
}

export function ParentDrillPath({
  layout,
  travelVia,
  motion
}: {
  layout: WorldLayout;
  travelVia: [number, number, number] | null;
  motion: boolean;
}) {
  const ref = useRef<THREE.Group>(null);
  const beadRefs = useRef<THREE.Mesh[]>([]);
  const points = useMemo(() => parentDrillPathCurvePoints(layout, travelVia), [layout, travelVia]);
  const floorPoints = useMemo(() => points.map((point) => new THREE.Vector3(point.x, 0.025, point.z)), [points]);
  const beadCount = layout.level >= 2 ? 5 : 4;
  useFrame((state) => {
    if (!motion || !ref.current || points.length < 2) return;
    const elapsed = state.clock.elapsedTime;
    ref.current.position.y = Math.sin(elapsed * 0.7) * 0.01;
    beadRefs.current.forEach((mesh, beadIndex) => {
      // Parent path is a return lane: motes drift from current center back to
      // the parent gate while the short TravelWake still marks the entry move.
      const t = 1 - ((elapsed * 0.105 + beadIndex / beadCount) % 1);
      const point = pointAlong(points, t);
      mesh.position.set(point.x, point.y + 0.025, point.z);
    });
    state.invalidate();
  });
  if (points.length < 2) return null;
  const start = points[0];
  const end = points[points.length - 1];
  return (
    <group ref={ref} renderOrder={5}>
      <StaticLine points={floorPoints} color="#5ee6b7" opacity={0.12} />
      <StaticLine points={points} color="#dff8ff" opacity={layout.level >= 2 ? 0.3 : 0.24} />
      <mesh position={[end.x, 0.05, end.z]} rotation={[Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.32 + layout.level * 0.05, 0.34 + layout.level * 0.05, 48]} />
        <meshBasicMaterial color="#dff8ff" transparent opacity={0.16} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} side={THREE.DoubleSide} />
      </mesh>
      <mesh position={[start.x, 0.055, start.z]} rotation={[Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.2, 0.225, 36]} />
        <meshBasicMaterial color="#5ee6b7" transparent opacity={0.2} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} side={THREE.DoubleSide} />
      </mesh>
      {Array.from({ length: beadCount }, (_, beadIndex) => {
        const point = pointAlong(points, 1 - beadIndex / beadCount);
        return (
          <mesh
            key={`parent-path-bead-${beadIndex}`}
            ref={(mesh) => {
              if (mesh) beadRefs.current[beadIndex] = mesh;
            }}
            position={[point.x, point.y + 0.025, point.z]}
            renderOrder={6}
          >
            <sphereGeometry args={[layout.level >= 2 ? 0.036 : 0.031, 8, 8]} />
            <meshBasicMaterial color={beadIndex === 0 ? "#dff8ff" : "#5ee6b7"} transparent opacity={0.56} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
          </mesh>
        );
      })}
    </group>
  );
}

export function ParentDrillGate({
  layout,
  travelVia,
  motion,
  onRetreat
}: {
  layout: WorldLayout;
  travelVia: [number, number, number] | null;
  motion: boolean;
  onRetreat: () => void;
}) {
  const visualRef = useRef<THREE.Group>(null);
  const spec = useMemo(() => parentDrillGateSpec(layout, travelVia), [layout, travelVia]);
  useFrame((state) => {
    if (!motion || !visualRef.current || !spec) return;
    const t = state.clock.elapsedTime;
    visualRef.current.position.y = Math.sin(t * 1.2) * 0.025;
    visualRef.current.rotation.z = Math.sin(t * 0.7) * 0.04;
    state.invalidate();
  });
  if (!spec) return null;
  return (
    <group position={spec.position} rotation={[0, spec.yaw, 0]} renderOrder={7}>
      <mesh
        frustumCulled={false}
        onClick={(event) => {
          event.stopPropagation();
          onRetreat();
        }}
      >
        <sphereGeometry args={[spec.radius * 1.28, 12, 10]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} colorWrite={false} />
      </mesh>
      <group ref={visualRef}>
        <mesh>
          <torusGeometry args={[spec.radius, Math.max(spec.radius * 0.045, 0.018), 8, 48]} />
          <meshBasicMaterial color="#dff8ff" transparent opacity={0.36} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
        </mesh>
        <mesh rotation={[0, 0, Math.PI / 4]}>
          <torusGeometry args={[spec.radius * 0.68, Math.max(spec.radius * 0.028, 0.012), 6, 32]} />
          <meshBasicMaterial color="#5ee6b7" transparent opacity={0.46} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
        </mesh>
        {[-0.34, 0, 0.34].map((offset, index) => (
          <mesh key={`parent-gate-step-${index}`} position={[offset * spec.radius, -spec.radius * 0.08, spec.radius * 0.05]} scale={[spec.radius * 0.16, spec.radius * 0.07, spec.radius * 0.42]}>
            <boxGeometry args={[1, 1, 1]} />
            <meshBasicMaterial color={index === 1 ? "#dff8ff" : "#5ee6b7"} transparent opacity={index === 1 ? 0.55 : 0.34} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
          </mesh>
        ))}
      </group>
      <Html position={[0, -spec.radius * 0.72, 0]} center distanceFactor={5.8} wrapperClass="sceneHtmlLabel sceneHtmlControl" className="parentDrillGateLabel" zIndexRange={[32, 0]}>
        <button type="button" aria-label={t("scene.parentGate")} title={t("scene.parentGateTitle")} onClick={onRetreat}>
          ↩
        </button>
      </Html>
    </group>
  );
}

export type DrillOriginEchoSpec = {
  position: [number, number, number];
  family: string;
  radius: number;
  color: string;
};

export type DrillContextTetherSpec = {
  key: string;
  targetId: string;
  from: [number, number, number];
  to: [number, number, number];
  color: string;
  opacity: number;
  beadCount: number;
  satelliteKind: "family" | "region";
};

export type DrillWaypointSpec = {
  key: string;
  targetId: string;
  position: [number, number, number];
  color: string;
  radius: number;
  tickCount: number;
  yaw: number;
  strength: number;
  satelliteKind: "family" | "region";
};

export function drillOriginEchoSpec(layout: WorldLayout, origin: [number, number, number] | null): DrillOriginEchoSpec | null {
  if (layout.perspective !== "quadrants" || layout.level < 1 || !origin) return null;
  const center = layout.nodes.find((node) => node.isRoot && node.isGroup);
  if (!center) return null;
  const family = center.groupKind === "quadrant" ? "region" : center.groupLabelKey || pageTypeStyle(center.page_type).family || "content";
  const color = pageTypeStyle(family === "region" ? "visual_group_region" : `visual_group_${family}`).accent || "#86e7ff";
  const radius = Math.max(0.22, Math.min(center.scale * (layout.level >= 2 ? 0.68 : 0.58), 0.42));
  return {
    position: [origin[0], Math.max(origin[1] + 0.08, 0.08), origin[2]],
    family,
    radius: Number(radius.toFixed(4)),
    color
  };
}

function groupNodeFamily(node: LayoutNode): string {
  if (node.groupKind === "quadrant") return "region";
  return node.groupLabelKey || pageTypeStyle(node.page_type).family || "content";
}

function groupNodeColor(node: LayoutNode): string {
  const family = groupNodeFamily(node);
  return pageTypeStyle(family === "region" ? "visual_group_region" : `visual_group_${family}`).accent || contextStyle(node.context).accent || "#86e7ff";
}

export function drillWaypointSpecs(layout: WorldLayout, maxWaypoints = 7): DrillWaypointSpec[] {
  if (layout.perspective !== "quadrants" || layout.level < 1) return [];
  const center = layout.nodes.find((node) => node.isRoot && node.isGroup);
  if (!center) return [];
  return layout.nodes
    .filter((node) => node.isGroup && !node.isRoot && Boolean(node.groupDrill))
    .map((node) => {
      const count = node.groupMemberIds?.length ?? 0;
      const satelliteKind: DrillWaypointSpec["satelliteKind"] = node.groupKind === "quadrant" ? "region" : "family";
      return { node, count, satelliteKind };
    })
    .sort(
      (a, b) =>
        Number(b.satelliteKind === "family") - Number(a.satelliteKind === "family") ||
        (a.node.ring ?? 9) - (b.node.ring ?? 9) ||
        b.count - a.count ||
        a.node.id.localeCompare(b.node.id)
    )
    .slice(0, maxWaypoints)
    .map(({ node, count, satelliteKind }) => {
      const dx = center.position[0] - node.position[0];
      const dz = center.position[2] - node.position[2];
      const strength = Math.min(1, Math.max(0.18, Math.log2(Math.max(count, 1) + 1) / 8));
      return {
        key: `drill-waypoint-${node.id}`,
        targetId: node.id,
        position: [node.position[0], Number((Math.max(node.position[1] + node.scale * 0.72, 0.1)).toFixed(4)), node.position[2]],
        color: groupNodeColor(node),
        radius: Number((Math.max(node.scale * (satelliteKind === "family" ? 1.02 : 0.82), satelliteKind === "family" ? 0.28 : 0.22)).toFixed(4)),
        tickCount: Math.max(3, Math.min(9, Math.ceil(Math.sqrt(Math.max(count, 1)) / (satelliteKind === "family" ? 2.6 : 3.8)))),
        yaw: Number(Math.atan2(dx, dz).toFixed(4)),
        strength: Number(strength.toFixed(4)),
        satelliteKind
      };
    });
}

export function drillContextTetherSpecs(layout: WorldLayout, maxTethers = 7): DrillContextTetherSpec[] {
  if (layout.perspective !== "quadrants" || layout.level < 1) return [];
  const center = layout.nodes.find((node) => node.isRoot && node.isGroup);
  if (!center) return [];
  const satellites = layout.nodes
    .filter((node) => node.isGroup && !node.isRoot)
    .map((node) => {
      const count = node.groupMemberIds?.length ?? 0;
      const satelliteKind: DrillContextTetherSpec["satelliteKind"] = node.groupKind === "quadrant" ? "region" : "family";
      return { node, count, satelliteKind };
    })
    .sort(
      (a, b) =>
        Number(b.satelliteKind === "family") - Number(a.satelliteKind === "family") ||
        (a.node.ring ?? 9) - (b.node.ring ?? 9) ||
        b.count - a.count ||
        a.node.id.localeCompare(b.node.id)
    )
    .slice(0, maxTethers);

  return satellites.map(({ node, count, satelliteKind }, index) => ({
    key: `${center.id}->${node.id}:context-${satelliteKind}`,
    targetId: node.id,
    from: center.position,
    to: node.position,
    color: groupNodeColor(node),
    opacity: Number((satelliteKind === "family" ? Math.min(0.32, 0.16 + count * 0.012) : Math.min(0.22, 0.1 + count * 0.006)).toFixed(4)),
    beadCount:
      satelliteKind === "family"
        ? Math.max(2, Math.min(4, Math.ceil(Math.sqrt(Math.max(count, 1)) / 4)))
        : Math.max(1, Math.min(2, Math.ceil(Math.sqrt(Math.max(count, 1)) / 4))),
    satelliteKind
  }));
}

export function drillContextTetherCurvePoints(tether: Pick<DrillContextTetherSpec, "from" | "to" | "satelliteKind">, index = 0): THREE.Vector3[] {
  const from = new THREE.Vector3(...tether.from);
  const to = new THREE.Vector3(...tether.to);
  const distance = from.distanceTo(to);
  const side = new THREE.Vector3(to.z - from.z, 0, from.x - to.x).normalize();
  const sideOffset = side.lengthSq() > 0 ? side.multiplyScalar((index % 2 === 0 ? 1 : -1) * (tether.satelliteKind === "family" ? 0.1 : 0.06)) : side;
  const control = from.clone().lerp(to, tether.satelliteKind === "family" ? 0.54 : 0.48).add(sideOffset);
  control.y += Math.min(Math.max(distance * (tether.satelliteKind === "family" ? 0.1 : 0.07), 0.16), tether.satelliteKind === "family" ? 0.46 : 0.32);
  return new THREE.QuadraticBezierCurve3(from, control, to).getPoints(28);
}

function DrillOriginGlyph({ family, color, radius }: { family: string; color: string; radius: number }) {
  if (family === "source") {
    return (
      <group rotation={[0, Math.PI / 8, 0]}>
        {[-0.34, 0, 0.34].map((offset, index) => (
          <mesh key={`drill-origin-source-${index}`} position={[offset * radius, index * radius * 0.18, 0]} scale={[radius * 0.78, radius * 0.52, radius * 0.16]}>
            <boxGeometry args={[1, 1, 1]} />
            <meshBasicMaterial color={index === 1 ? "#dff8ff" : color} transparent opacity={index === 1 ? 0.48 : 0.34} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
          </mesh>
        ))}
      </group>
    );
  }
  if (family === "event") {
    return (
      <group>
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[radius * 0.42, radius * 0.035, 6, 28]} />
          <meshBasicMaterial color={color} transparent opacity={0.46} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
        </mesh>
        {[0, 1, 2].map((index) => {
          const angle = -Math.PI / 2 + index * Math.PI * 0.66;
          return (
            <mesh key={`drill-origin-event-${index}`} position={[Math.cos(angle) * radius * 0.36, 0.02, Math.sin(angle) * radius * 0.36]}>
              <sphereGeometry args={[radius * 0.08, 8, 6]} />
              <meshBasicMaterial color={index === 1 ? "#dff8ff" : color} transparent opacity={0.58} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
            </mesh>
          );
        })}
      </group>
    );
  }
  if (family === "region") {
    return (
      <group>
        <mesh rotation={[Math.PI / 2, 0, Math.PI / 4]}>
          <boxGeometry args={[radius * 0.72, radius * 0.72, radius * 0.08]} />
          <meshBasicMaterial color={color} transparent opacity={0.34} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
        </mesh>
        {[0.48, 0.68, 0.88].map((scale, index) => (
          <mesh key={`drill-origin-region-ring-${index}`} rotation={[Math.PI / 2, 0, 0]}>
            <torusGeometry args={[radius * scale, radius * 0.025, 5, 36]} />
            <meshBasicMaterial color={index === 1 ? "#dff8ff" : color} transparent opacity={0.2 + index * 0.06} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
          </mesh>
        ))}
      </group>
    );
  }
  return (
    <group>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[radius * 0.54, radius * 0.04, 6, 32]} />
        <meshBasicMaterial color={color} transparent opacity={0.38} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
      </mesh>
      <mesh>
        <boxGeometry args={[radius * 0.48, radius * 0.48, radius * 0.48]} />
        <meshBasicMaterial color="#dff8ff" transparent opacity={0.32} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
      </mesh>
    </group>
  );
}

export function DrillOriginEcho({
  layout,
  origin,
  motion,
  onRetreat
}: {
  layout: WorldLayout;
  origin: [number, number, number] | null;
  motion: boolean;
  onRetreat: () => void;
}) {
  const visualRef = useRef<THREE.Group>(null);
  const spec = useMemo(() => drillOriginEchoSpec(layout, origin), [layout, origin]);
  useFrame((state) => {
    if (!motion || !visualRef.current || !spec) return;
    const elapsed = state.clock.elapsedTime;
    visualRef.current.rotation.y = elapsed * 0.22;
    visualRef.current.position.y = Math.sin(elapsed * 1.1) * 0.025;
    state.invalidate();
  });
  if (!spec) return null;
  return (
    <group position={spec.position} renderOrder={7}>
      <mesh
        frustumCulled={false}
        onClick={(event) => {
          event.stopPropagation();
          onRetreat();
        }}
      >
        <sphereGeometry args={[spec.radius * 1.5, 12, 10]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} colorWrite={false} />
      </mesh>
      <group ref={visualRef}>
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[spec.radius * 1.18, Math.max(spec.radius * 0.035, 0.01), 6, 48]} />
          <meshBasicMaterial color={spec.color} transparent opacity={0.26} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
        </mesh>
        <DrillOriginGlyph family={spec.family} color={spec.color} radius={spec.radius} />
      </group>
    </group>
  );
}

function DrillContextTether({ tether, index, motion }: { tether: DrillContextTetherSpec; index: number; motion: boolean }) {
  const ref = useRef<THREE.Group>(null);
  const beadRefs = useRef<THREE.Mesh[]>([]);
  const points = useMemo(() => drillContextTetherCurvePoints(tether, index), [index, tether]);
  useFrame((state) => {
    if (!motion || !ref.current) return;
    const elapsed = state.clock.elapsedTime;
    ref.current.position.y = Math.sin(elapsed * 0.48 + index * 0.7) * 0.012;
    beadRefs.current.forEach((mesh, beadIndex) => {
      const phase = (elapsed * (tether.satelliteKind === "family" ? 0.08 : 0.055) + beadIndex / Math.max(tether.beadCount, 1) + index * 0.09) % 1;
      const point = pointAlong(points, phase);
      mesh.position.set(point.x, point.y + 0.018, point.z);
    });
    state.invalidate();
  });
  return (
    <group ref={ref} renderOrder={2}>
      <StaticLine points={points} color={tether.color} opacity={tether.opacity} />
      {Array.from({ length: tether.beadCount }, (_, beadIndex) => {
        const point = pointAlong(points, tether.beadCount === 1 ? 0.5 : beadIndex / (tether.beadCount - 1));
        const radius = tether.satelliteKind === "family" ? 0.026 : 0.02;
        return (
          <mesh
            key={`${tether.key}-context-bead-${beadIndex}`}
            ref={(mesh) => {
              if (mesh) beadRefs.current[beadIndex] = mesh;
            }}
            position={[point.x, point.y + 0.018, point.z]}
          >
            <sphereGeometry args={[radius, 8, 8]} />
            <meshBasicMaterial color={tether.color} transparent opacity={tether.satelliteKind === "family" ? 0.46 : 0.34} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
          </mesh>
        );
      })}
    </group>
  );
}

export function DrillContextTethers({ layout, motion }: { layout: WorldLayout; motion: boolean }) {
  const tethers = useMemo(() => drillContextTetherSpecs(layout), [layout]);
  if (tethers.length === 0) return null;
  return (
    <group>
      {tethers.map((tether, index) => (
        <DrillContextTether key={`drill-context-tether-${tether.key}`} tether={tether} index={index} motion={motion} />
      ))}
    </group>
  );
}

function DrillWaypoint({ waypoint, index, motion }: { waypoint: DrillWaypointSpec; index: number; motion: boolean }) {
  const ref = useRef<THREE.Group>(null);
  useFrame((state) => {
    if (!motion || !ref.current) return;
    const elapsed = state.clock.elapsedTime;
    ref.current.rotation.y = waypoint.yaw + Math.sin(elapsed * 0.5 + index) * 0.055;
    ref.current.position.y = waypoint.position[1] + Math.sin(elapsed * 0.9 + index * 0.65) * 0.018;
    state.invalidate();
  });
  return (
    <group ref={ref} position={waypoint.position} rotation={[0, waypoint.yaw, 0]} renderOrder={5}>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[waypoint.radius, Math.max(waypoint.radius * 0.028, 0.008), 5, 42]} />
        <meshBasicMaterial color={waypoint.color} transparent opacity={0.2 + waypoint.strength * 0.22} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
      </mesh>
      <mesh position={[0, 0.014, waypoint.radius * 0.42]} rotation={[Math.PI / 2, 0, 0]}>
        <coneGeometry args={[waypoint.radius * 0.16, waypoint.radius * 0.34, 3]} />
        <meshBasicMaterial color="#dff8ff" transparent opacity={0.22 + waypoint.strength * 0.24} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
      </mesh>
      {Array.from({ length: waypoint.tickCount }, (_, tickIndex) => {
        const angle = (tickIndex / waypoint.tickCount) * Math.PI * 2;
        const major = tickIndex === 0;
        return (
          <mesh
            key={`${waypoint.key}-tick-${tickIndex}`}
            position={[Math.sin(angle) * waypoint.radius, major ? 0.05 : 0.032, Math.cos(angle) * waypoint.radius]}
            rotation={[0, angle, 0]}
            scale={[major ? 1.3 : 1, 1, major ? 1.25 : 1]}
          >
            <boxGeometry args={[waypoint.radius * 0.055, waypoint.radius * 0.04, waypoint.radius * 0.22]} />
            <meshBasicMaterial color={major ? "#dff8ff" : waypoint.color} transparent opacity={major ? 0.52 : 0.28 + waypoint.strength * 0.18} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
          </mesh>
        );
      })}
    </group>
  );
}

export function DrillWaypoints({ layout, motion }: { layout: WorldLayout; motion: boolean }) {
  const waypoints = useMemo(() => drillWaypointSpecs(layout), [layout]);
  if (waypoints.length === 0) return null;
  return (
    <group>
      {waypoints.map((waypoint, index) => (
        <DrillWaypoint key={waypoint.key} waypoint={waypoint} index={index} motion={motion} />
      ))}
    </group>
  );
}

function GroupRelationBundleArc({ bundle, index, motion }: { bundle: GroupRelationBundle; index: number; motion: boolean }) {
  const ref = useRef<THREE.Group>(null);
  const beadRefs = useRef<THREE.Mesh[]>([]);
  const color = edgeStyle(bundle.type).color;
  const points = useMemo(() => bundleCurvePoints(bundle, index), [bundle, index]);
  const curve = useMemo(() => new THREE.CatmullRomCurve3(points), [points]);
  const visual = useMemo(() => groupRelationBundleVisualSpec(bundle), [bundle]);
  useFrame((state) => {
    if (!motion || !ref.current) return;
    const elapsed = state.clock.elapsedTime;
    ref.current.position.y = Math.sin(elapsed * 0.75 + index * 0.9) * 0.018;
    beadRefs.current.forEach((mesh, beadIndex) => {
      const phase = (elapsed * (0.12 + bundle.share * 0.16) + beadIndex / Math.max(visual.beadCount, 1) + index * 0.11) % 1;
      const directed =
        bundle.flow === "in"
          ? 1 - phase
          : bundle.flow === "mixed" && beadIndex % 2 === 1
            ? 1 - phase
            : phase;
      const point = pointAlong(points, directed);
      mesh.position.set(point.x, point.y + 0.025, point.z);
    });
    state.invalidate();
  });
  return (
    <group ref={ref}>
      <mesh renderOrder={3}>
        <tubeGeometry args={[curve, 32, visual.haloRadius, 8, false]} />
        <meshBasicMaterial color={color} transparent opacity={visual.haloOpacity} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
      </mesh>
      <mesh renderOrder={4}>
        <tubeGeometry args={[curve, 32, visual.tubeRadius, 8, false]} />
        <meshBasicMaterial color={color} transparent opacity={visual.opacity} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
      </mesh>
      <StaticLine points={points} color={color} opacity={Math.min(0.36, visual.opacity + 0.08)} />
      {Array.from({ length: visual.beadCount }, (_, beadIndex) => {
        const t = visual.beadCount === 1 ? 0.5 : beadIndex / (visual.beadCount - 1);
        const directed =
          bundle.flow === "in"
            ? 1 - t
            : bundle.flow === "mixed" && beadIndex % 2 === 1
              ? 1 - t
              : t;
        const point = pointAlong(points, directed);
        const mass = Math.min(Math.sqrt(bundle.count) / 12, 1);
        return (
          <mesh
            key={`${bundle.key}-bead-${beadIndex}`}
            ref={(mesh) => {
              if (mesh) beadRefs.current[beadIndex] = mesh;
            }}
            position={[point.x, point.y + 0.025, point.z]}
          >
            <sphereGeometry args={[visual.particleRadius, 8, 8]} />
            <meshBasicMaterial color={color} transparent opacity={0.5 + mass * 0.18} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
          </mesh>
        );
      })}
    </group>
  );
}

export function RelationLanes({
  lanes,
  bundles = [],
  layout,
  motion
}: {
  lanes: RelationLane[];
  bundles?: GroupRelationBundle[];
  layout: WorldLayout;
  motion: boolean;
}) {
  if ((lanes.length === 0 && bundles.length === 0) || layout.perspective !== "quadrants") return null;
  if (layout.level < 1 && bundles.length === 0) return null;
  const centerNode = layout.nodes.find((node) => node.isRoot && node.isGroup) ?? layout.nodes.find((node) => node.isRoot);
  if (!centerNode) return null;
  const center: [number, number, number] = [centerNode.position[0], centerNode.position[1], centerNode.position[2]];
  return (
    <group>
      {lanes.map((lane, index) => (
        <RelationLaneArc
          key={`relation-lane-${lane.type}`}
          lane={lane}
          index={index}
          total={lanes.length}
          center={center}
          level={layout.level}
          motion={motion}
        />
      ))}
      {bundles.map((bundle, index) => (
        <GroupRelationBundleArc key={`group-relation-bundle-${bundle.key}`} bundle={bundle} index={index} motion={motion} />
      ))}
    </group>
  );
}

export function WorldGuides({ layout }: { layout: WorldLayout }) {
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
              never fakes a date that does not exist. The band (and its label)
              only exists when some page actually HAS no date: no data, no
              instrument — a newborn world must not open with audit jargon. */}
          {layout.unknownR !== null && layout.nodes.some((node) => node.freshness_state === "unknown") && (
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

export function ProposalStems({ nodes, morph }: { nodes: LayoutNode[]; morph: RefObject<MorphState> }) {
  const { invalidate } = useThree();
  const object = useMemo(() => {
    const points = nodes
      .filter((node) => node.position[1] > 0.05)
      .flatMap((node) => [
        new THREE.Vector3(node.position[0], 0, node.position[2]),
        new THREE.Vector3(...node.position)
      ]);
    if (points.length === 0) return null;
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({
      color: trustColor("proposal"),
      transparent: true,
      opacity: morph.current?.active ? 0 : 0.5,
      toneMapped: false
    });
    return { lines: new THREE.LineSegments(geometry, material), geometry, material };
  }, [morph, nodes]);
  useFrame((state) => {
    if (!object) return;
    object.material.opacity = morphAttachmentOpacity(morph.current, state.clock.elapsedTime, 0.5);
  });
  useEffect(() => {
    invalidate();
    return () => {
      object?.geometry.dispose();
      object?.material.dispose();
    };
  }, [invalidate, object]);
  return object ? <primitive object={object.lines} /> : null;
}

export function GateRing({ git }: { git: GitState }) {
  const color = git.proposal.is_proposal_branch ? trustColor("proposal") : trustColor("root");
  return (
    <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, -0.01, 0]}>
      <torusGeometry args={[1.05, 0.02, 12, 96]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.8} toneMapped={false} />
    </mesh>
  );
}

// Quadrant frame: four THIN translucent floor squares that make the quadrant
// structure POSITIONAL — architecture, not a modal concept. Neutral HUD blue
// at whisper opacity; the active quadrant's square breathes slightly brighter.
// Each square's placement is DERIVED from the same sector-center angle the
// layout uses to place that facet's NODES — the floor can never disagree with
// the world (a hand-written sign table once put every square in the wrong
// sector: selecting Culture & relations lit the square over Identity & intent pages).
const QUADRANT_SQUARES: { facet: string; sx: 1 | -1; sz: 1 | -1 }[] = SCENE_FACETS.map((facet) => ({
  facet,
  sx: Math.cos(QUADRANT_CENTER_ANGLE[facet]) >= 0 ? 1 : -1,
  sz: Math.sin(QUADRANT_CENTER_ANGLE[facet]) >= 0 ? 1 : -1
}));

// Reuse the cockpit's established quadrant accents. The territories need to
// read as four places before a user opens the compass; the previous neutral
// blue at 4.5% opacity collapsed into one indistinct floor ring.
const QUADRANT_TERRITORY_COLORS: Record<string, string> = {
  intencao: "#7fd0e8",
  pratica: "#ffb454",
  relacoes: "#c57cff",
  sistemas: "#5ee6a8"
};

export function QuadrantPlanes({ rOuter, activeQuadrant }: { rOuter: number; activeQuadrant?: string }) {
  const size = rOuter + 0.9;
  const gap = 0.24;
  return (
    <group position={[0, -0.42, 0]}>
      {QUADRANT_SQUARES.map(({ facet, sx, sz }) => {
        const active = activeQuadrant === facet;
        const color = QUADRANT_TERRITORY_COLORS[facet] ?? "#7fd0e8";
        const half = (size - gap) / 2;
        return (
          <group key={facet} position={[sx * (half + gap / 2 + gap / 2), 0, sz * (half + gap / 2 + gap / 2)]}>
            <mesh rotation={[-Math.PI / 2, 0, 0]}>
              <planeGeometry args={[size - gap, size - gap]} />
              <meshBasicMaterial
                color={color}
                transparent
                opacity={active ? 0.15 : 0.068}
                depthWrite={false}
                toneMapped={false}
                side={THREE.DoubleSide}
              />
            </mesh>
            {/* The thin edge that makes the square READ as a frame. */}
            <lineSegments rotation={[-Math.PI / 2, 0, 0]}>
              <edgesGeometry args={[new THREE.PlaneGeometry(size - gap, size - gap)]} />
              <lineBasicMaterial
                color={color}
                transparent
                opacity={active ? 0.62 : 0.34}
                toneMapped={false}
              />
            </lineSegments>
          </group>
        );
      })}
    </group>
  );
}
