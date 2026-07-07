// CameraDirector: WARP (drill in), RETREAT (level up) and FOCUS (target-lock
// glide) choreography over OrbitControls. All eased and interruptible by user
// input; instant cuts under reduced motion / test mode.

import { OrbitControls } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type { LayoutNode } from "../layout";
import type { WorldLayout } from "../perspectives";
import { easeOutCubic } from "./nodes";

export function CameraDirector({
  layout,
  lockedNode,
  flyToNode = null,
  enableIntro,
  motion
}: {
  layout: WorldLayout;
  lockedNode: LayoutNode | null;
  // A transient CINEMATIC target (a newborn entity): the camera glides to it
  // without locking the page — the birth is WITNESSED, then control returns.
  flyToNode?: LayoutNode | null;
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
    fromPhi: number;
    toPhi: number;
    fromTheta: number;
    toTheta: number | null;
    start: number | null;
    duration: number;
    active: boolean;
  } | null>(null);
  const lastKey = useRef("");

  const lerpAngle = (from: number, to: number, t: number) => {
    const delta = Math.atan2(Math.sin(to - from), Math.cos(to - from));
    return from + delta * t;
  };

  const fitDistance = useMemo(() => {
    const rLabel = layout.rOuter + 1.1;
    const vFov = (40 * Math.PI) / 180;
    const aspect = size.width / Math.max(size.height, 1);
    const hFov = 2 * Math.atan(Math.tan(vFov / 2) * aspect);
    return (rLabel / Math.sin(Math.min(vFov, hFov) / 2)) * 0.88;
  }, [layout.rOuter, size.height, size.width]);
  const cameraTargetKey = (layout.cameraTarget ?? []).map((n) => n.toFixed(3)).join(",");

  useEffect(() => {
    // Priority: a locked page > a newborn being witnessed > an active quadrant
    // region (fly-to) > the origin.
    const regionTarget = !lockedNode && layout.cameraTarget ? new THREE.Vector3(...layout.cameraTarget) : null;
    const regionDirection =
      regionTarget && regionTarget.lengthSq() > 0.001
        ? new THREE.Vector3(regionTarget.x, 0, regionTarget.z).normalize()
        : null;
    const desiredTarget = lockedNode
      ? new THREE.Vector3(...lockedNode.position)
      : flyToNode
        ? new THREE.Vector3(...flyToNode.position)
        : regionTarget
          ? regionTarget.clone().multiplyScalar(0.62)
          : new THREE.Vector3(0, 0, 0);
    const desiredDistance = lockedNode
      ? Math.max(fitDistance * 0.36, 2.6)
      : flyToNode
        ? Math.max(fitDistance * 0.5, 3)
        : regionTarget
          ? Math.max(fitDistance * 0.42, 3.2)
          : fitDistance;
    const key = `${layout.perspective}:${layout.level}:${lockedNode?.id ?? ""}:${flyToNode?.id ?? ""}:${(layout.cameraTarget ?? []).map((n) => n.toFixed(1)).join(",")}:${fitDistance.toFixed(2)}`;
    if (key === lastKey.current) return;
    const firstFrame = lastKey.current === "";
    lastKey.current = key;

    const controls = controlsRef.current;
    const currentTarget = controls ? controls.target.clone() : new THREE.Vector3(0, 0, 0);
    const currentDistance = camera.position.distanceTo(currentTarget) || fitDistance;
    const currentOffset = camera.position.clone().sub(currentTarget);
    const currentSpherical = new THREE.Spherical().setFromVector3(
      currentOffset.lengthSq() > 0.0001 ? currentOffset : new THREE.Vector3(0, 1, 1)
    );
    const regionTheta = regionDirection ? Math.atan2(-regionDirection.x, -regionDirection.z) : null;
    const targetPhi = regionTarget ? 1.08 : lockedNode || flyToNode ? 0.95 : 0.72;

    // FOCUS ~350ms; WARP/RETREAT ~600ms; intro slightly longer glide.
    const duration = !motion ? 0 : lockedNode ? 0.35 : regionTarget ? 0.75 : firstFrame && enableIntro ? 0.75 : 0.6;
    animation.current = {
      fromTarget: currentTarget,
      toTarget: desiredTarget,
      fromDistance: firstFrame ? desiredDistance * 1.28 : currentDistance,
      toDistance: desiredDistance,
      fromPhi: currentSpherical.phi,
      toPhi: targetPhi,
      fromTheta: currentSpherical.theta,
      toTheta: regionTheta,
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
      const spherical = new THREE.Spherical(desiredDistance, targetPhi, regionTheta ?? currentSpherical.theta);
      camera.position.copy(desiredTarget.clone().add(new THREE.Vector3().setFromSpherical(spherical)));
      controls?.target.copy(desiredTarget);
      camera.lookAt(desiredTarget);
      controls?.update();
      animation.current = null;
      invalidate();
    }
    invalidate();
  }, [camera, cameraTargetKey, enableIntro, fitDistance, flyToNode, invalidate, layout.level, layout.perspective, lockedNode, motion]);

  useFrame((state) => {
    const anim = animation.current;
    const controls = controlsRef.current;
    if (!anim?.active || !controls) return;
    if (anim.start === null) anim.start = state.clock.elapsedTime;
    const t = Math.min((state.clock.elapsedTime - anim.start) / anim.duration, 1);
    const eased = easeOutCubic(t);
    const target = anim.fromTarget.clone().lerp(anim.toTarget, eased);
    const distance = THREE.MathUtils.lerp(anim.fromDistance, anim.toDistance, eased);
    // Quadrant flight owns azimuth so the selected region opens ahead and the
    // root stays close in the foreground. Other moves preserve user azimuth.
    const offset = camera.position.clone().sub(controls.target);
    const spherical = new THREE.Spherical().setFromVector3(
      offset.lengthSq() > 0.0001 ? offset : new THREE.Vector3(0, 1, 1)
    );
    spherical.radius = distance;
    spherical.phi = THREE.MathUtils.lerp(anim.fromPhi, anim.toPhi, eased);
    if (anim.toTheta !== null) {
      spherical.theta = lerpAngle(anim.fromTheta, anim.toTheta, eased);
    }
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
