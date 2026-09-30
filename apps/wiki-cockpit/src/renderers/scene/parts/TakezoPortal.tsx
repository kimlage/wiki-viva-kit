// Takezo's chain portal (plan §15.4): a luminous arc of toroidal chain links
// that draws itself during the abrachaindabra ritual. The "chain" is a visual
// pun on abra-CHAIN-dabra — purely decorative, never a count or a data
// encoding, and its color lives OUTSIDE the data legend. One InstancedMesh
// keeps the whole arc at a single draw call inside the ritual's budget.

import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { motionProgress } from "../../../world/visual/motionGrammar";

export const TAKEZO_PORTAL_LINK_COUNT = 15;
export const TAKEZO_PORTAL_RADIUS = 1.5;

// Within the existing decorative render-order budget (1–7); depthWrite is
// explicit so the layer composes predictably with the data layers.
export const TAKEZO_RENDER_ORDER = 6;

export type TakezoPortalLinkTransform = {
  position: [number, number, number];
  quaternion: [number, number, number, number];
};

/**
 * Deterministic link placement along a semicircular arch above the ground plane:
 * link i sits at angle π·i/(n−1), its plane containing the arc tangent, with
 * every other link twisted 90° around the tangent so the arc reads as a chain.
 */
export function takezoPortalLinkTransforms(
  linkCount = TAKEZO_PORTAL_LINK_COUNT,
  radius = TAKEZO_PORTAL_RADIUS
): TakezoPortalLinkTransform[] {
  const transforms: TakezoPortalLinkTransform[] = [];
  const tangentTwist = new THREE.Quaternion();
  const planeAlign = new THREE.Quaternion();
  const combined = new THREE.Quaternion();
  const zAxis = new THREE.Vector3(0, 0, 1);
  const xAxis = new THREE.Vector3(1, 0, 0);
  for (let index = 0; index < linkCount; index += 1) {
    const angle = linkCount === 1 ? Math.PI / 2 : (Math.PI * index) / (linkCount - 1);
    planeAlign.setFromAxisAngle(zAxis, angle);
    tangentTwist.setFromAxisAngle(xAxis, index % 2 === 0 ? 0 : Math.PI / 2);
    combined.copy(planeAlign).multiply(tangentTwist);
    transforms.push({
      position: [Math.cos(angle) * radius, Math.sin(angle) * radius + 0.04, 0],
      quaternion: [combined.x, combined.y, combined.z, combined.w]
    });
  }
  return transforms;
}

/** How many links the drawing animation reveals at a given eased progress. */
export function portalLinksRevealed(progress: number, linkCount = TAKEZO_PORTAL_LINK_COUNT): number {
  if (progress <= 0) return 0;
  if (progress >= 1) return linkCount;
  return Math.min(linkCount, Math.max(1, Math.ceil(progress * linkCount)));
}

export type TakezoPortalBuild = {
  mesh: THREE.InstancedMesh;
  drawCalls: number;
  dispose: () => void;
};

// Chain glow: a pale periwinkle deliberately absent from the trust, context
// and page-type palettes — the ritual may never impersonate a data state.
export const TAKEZO_CHAIN_COLOR = "#cdd9f7";

export function buildTakezoPortal(
  linkCount = TAKEZO_PORTAL_LINK_COUNT,
  radius = TAKEZO_PORTAL_RADIUS
): TakezoPortalBuild {
  const geometry = new THREE.TorusGeometry(0.1, 0.026, 8, 20);
  const material = new THREE.MeshStandardMaterial({
    color: TAKEZO_CHAIN_COLOR,
    emissive: TAKEZO_CHAIN_COLOR,
    emissiveIntensity: 0.55,
    roughness: 0.35,
    metalness: 0.4,
    depthWrite: true,
    toneMapped: false
  });
  const mesh = new THREE.InstancedMesh(geometry, material, linkCount);
  const matrix = new THREE.Matrix4();
  const quaternion = new THREE.Quaternion();
  const position = new THREE.Vector3();
  const scale = new THREE.Vector3(1, 1, 1);
  takezoPortalLinkTransforms(linkCount, radius).forEach((transform, index) => {
    position.set(...transform.position);
    quaternion.set(...transform.quaternion);
    matrix.compose(position, quaternion, scale);
    mesh.setMatrixAt(index, matrix);
  });
  mesh.instanceMatrix.needsUpdate = true;
  mesh.renderOrder = TAKEZO_RENDER_ORDER;
  mesh.frustumCulled = false;
  return {
    mesh,
    drawCalls: 1,
    dispose: () => {
      geometry.dispose();
      material.dispose();
    }
  };
}

/**
 * The ritual's chain arc. Lazy-mounted only while the ritual is on stage;
 * `animate=false` (reduced motion / degraded density budget) shows the full
 * static arc immediately. The draw animation invalidates frames only while it
 * is actually running — the portal is completely silent when idle.
 */
export function TakezoPortal({
  delayMs,
  durationMs,
  animate
}: {
  delayMs: number;
  durationMs: number;
  animate: boolean;
}) {
  const build = useMemo(() => buildTakezoPortal(), []);
  useEffect(() => () => build.dispose(), [build]);
  const startRef = useRef<number | null>(null);
  const doneRef = useRef(!animate || durationMs <= 0);
  if (doneRef.current) build.mesh.count = TAKEZO_PORTAL_LINK_COUNT;
  else if (startRef.current === null) build.mesh.count = 0;
  useFrame((state) => {
    if (doneRef.current) return;
    if (startRef.current === null) startRef.current = state.clock.elapsedTime;
    const elapsedMs = (state.clock.elapsedTime - startRef.current) * 1000 - delayMs;
    const progress = Math.min(Math.max(elapsedMs / durationMs, 0), 1);
    build.mesh.count = portalLinksRevealed(motionProgress("overlay", progress));
    state.invalidate();
    if (progress >= 1) doneRef.current = true;
  });
  return <primitive object={build.mesh} />;
}
