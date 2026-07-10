// CameraDirector: WARP (drill in), RETREAT (level up) and FOCUS (target-lock
// glide) choreography over OrbitControls. All eased and interruptible by user
// input; instant cuts under reduced motion / test mode.

import { OrbitControls } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type { LayoutNode } from "../../../scene/layout";
import type { WorldLayout } from "../../../scene/perspectives";
import { motionDurationSeconds, motionProgress } from "../../../world/visual/motionGrammar";
import type { MotionIntent } from "../../../world/visual/motionGrammar";

export function travelThetaFromWorldPoint(point: [number, number, number] | null | undefined): number | null {
  if (!point) return null;
  const [x, , z] = point;
  if (x * x + z * z < 0.0001) return null;
  return Math.atan2(-x, -z);
}

export function centeredGroupCameraLift(layout: WorldLayout): number {
  if (layout.perspective !== "quadrants" || layout.level < 1) return 0;
  const center = layout.nodes.find((node) => node.isRoot && node.isGroup);
  if (!center) return 0;
  return Math.min(Math.max(center.scale * 0.65, 0.22), 0.58);
}

export function centeredGroupSafeAreaDistanceMultiplier(layout: WorldLayout): number {
  if (layout.perspective !== "quadrants" || layout.level < 1) return 1;
  const center = layout.nodes.find((node) => node.isRoot && node.isGroup);
  const memberCount = center?.groupMemberIds?.length ?? 0;
  if (!center || memberCount < 18) return 1;
  const densityGain = Math.log2(memberCount / 16) * (layout.level >= 2 ? 0.14 : 0.045);
  const levelGain = layout.level >= 2 ? 0.08 : 0.025;
  return Number(Math.min(layout.level >= 2 ? 1.34 : 1.16, 1 + levelGain + densityGain).toFixed(4));
}

export function centeredGroupCameraPhi(layout: WorldLayout): number {
  if (layout.perspective !== "quadrants" || layout.level < 1) return 0.72;
  const safeAreaMultiplier = centeredGroupSafeAreaDistanceMultiplier(layout);
  if (layout.level >= 2) return safeAreaMultiplier > 1.16 ? 0.64 : safeAreaMultiplier > 1 ? 0.72 : 0.78;
  return safeAreaMultiplier > 1 ? 0.86 : 0.9;
}

export function centeredGroupCameraDistance(layout: WorldLayout, fitDistance: number): number {
  if (layout.perspective !== "quadrants" || layout.level < 1) return fitDistance;
  const center = layout.nodes.find((node) => node.isRoot && node.isGroup);
  if (!center) return fitDistance;
  const bodyRadius = Math.max(center.scale * 3.25, center.groupKind === "quadrant" ? 1.18 : 0.96);
  const bodyFit = bodyRadius * (layout.level >= 2 ? 3.55 : 3.35);
  const worldFit = fitDistance * (layout.level >= 2 ? 0.6 : 0.6);
  return Number((Math.max(bodyFit, worldFit, layout.level >= 2 ? 5.6 : 5.3) * centeredGroupSafeAreaDistanceMultiplier(layout)).toFixed(4));
}

export function hoverInspectionCameraWeight(layout: WorldLayout, node: LayoutNode | null | undefined): number {
  void layout;
  void node;
  return 0;
}

export function hoverInspectionCameraTarget(layout: WorldLayout, node: LayoutNode | null | undefined): [number, number, number] | null {
  const weight = hoverInspectionCameraWeight(layout, node);
  if (!node || weight <= 0) return null;
  const center = layout.nodes.find((candidate) => candidate.isRoot && candidate.isGroup)?.position ?? ([0, 0, 0] as [number, number, number]);
  return [
    Number((center[0] + (node.position[0] - center[0]) * weight).toFixed(4)),
    Number((Math.max(center[1], 0) + Math.max(node.position[1] + node.scale * 0.62, 0.12) * weight).toFixed(4)),
    Number((center[2] + (node.position[2] - center[2]) * weight).toFixed(4))
  ];
}

export function hoverInspectionDistanceMultiplier(layout: WorldLayout, node: LayoutNode | null | undefined): number {
  const weight = hoverInspectionCameraWeight(layout, node);
  if (weight <= 0) return 1;
  const navigableBoost = node?.isGroup && node.groupDrill ? 0.04 : 0;
  return Number(Math.max(0.88, 1 - weight * 0.16 - navigableBoost).toFixed(4));
}

export function CameraDirector({
  layout,
  lockedNode,
  flyToNode = null,
  travelVia = null,
  enableIntro,
  motion,
  motionScale = 1,
  transition
}: {
  layout: WorldLayout;
  lockedNode: LayoutNode | null;
  // A transient CINEMATIC target (a newborn entity): the camera glides to it
  // without locking the page — the birth is WITNESSED, then control returns.
  flyToNode?: LayoutNode | null;
  // Previous-world position of the group being opened. It bends the camera
  // target toward the selected object, so drill-down reads as physical travel
  // through one world instead of a cut to a fresh camera setup.
  travelVia?: [number, number, number] | null;
  enableIntro: boolean;
  motion: boolean;
  motionScale?: number;
  transition: { sequence: number; intent: MotionIntent; duration: number };
}) {
  const { camera, size, invalidate } = useThree();
  const controlsRef = useRef<OrbitControlsImpl | null>(null);
  const animation = useRef<{
    fromTarget: THREE.Vector3;
    viaTarget: THREE.Vector3 | null;
    toTarget: THREE.Vector3;
    fromDistance: number;
    toDistance: number;
    fromPhi: number;
    toPhi: number;
    fromTheta: number;
    toTheta: number | null;
    thetaArc: number;
    distanceSwell: number;
    targetLift: number;
    start: number | null;
    duration: number;
    active: boolean;
    intent: MotionIntent;
  } | null>(null);
  const lastKey = useRef("");
  const lastTransitionSequence = useRef(0);

  const lerpAngle = (from: number, to: number, t: number) => {
    const delta = Math.atan2(Math.sin(to - from), Math.cos(to - from));
    return from + delta * t;
  };

  const stableUnit = (value: string) => {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
      hash ^= value.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0) / 4294967296;
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
    // Priority: a newborn being witnessed > a conceptual quadrant lens > a
    // locked page > origin. A quadrant lens is not a new center object: it
    // moves the camera target into the selected sector while the locked page
    // remains the foreground anchor in the same world.
    const quadrantLensTarget =
      layout.perspective === "quadrants" && layout.cameraTarget ? new THREE.Vector3(...layout.cameraTarget) : null;
    const regionTarget = !flyToNode && quadrantLensTarget ? quadrantLensTarget : !lockedNode && layout.cameraTarget ? new THREE.Vector3(...layout.cameraTarget) : null;
    const quadrantGroupTarget =
      !lockedNode && !flyToNode && layout.perspective === "quadrants" && layout.level > 0 ? new THREE.Vector3(0, 0, 0) : null;
    const groupCameraLift = centeredGroupCameraLift(layout);
    const regionDirection =
      regionTarget && regionTarget.lengthSq() > 0.001
        ? new THREE.Vector3(regionTarget.x, 0, regionTarget.z).normalize()
        : null;
    const groupTravel = !lockedNode && !flyToNode && layout.perspective === "quadrants" && layout.level > 0 && Boolean(layout.group);
    const lockedTravel = Boolean(lockedNode && travelVia);
    const groupTravelSeed = stableUnit(`${layout.perspective}:${layout.group ?? ""}:${layout.level}`);
    const groupTravelTheta = groupTravel ? travelThetaFromWorldPoint(travelVia) ?? -Math.PI + groupTravelSeed * Math.PI * 2 : null;
    const baseDesiredTarget = regionTarget
      ? regionTarget.clone().multiplyScalar(lockedNode ? 0.72 : 0.62)
      : lockedNode
        ? new THREE.Vector3(...lockedNode.position)
        : flyToNode
          ? new THREE.Vector3(...flyToNode.position)
          : quadrantGroupTarget
            ? quadrantGroupTarget.clone().setY(groupCameraLift)
            : new THREE.Vector3(0, 0, 0);
    const desiredTarget = baseDesiredTarget;
    const viaTarget =
      (groupTravel || lockedTravel) && travelVia
        ? new THREE.Vector3(travelVia[0], Math.max(groupCameraLift * 0.55, lockedTravel ? 0.28 : 0), travelVia[2])
        : null;
    const baseDesiredDistance = regionTarget
      ? Math.max(fitDistance * (lockedNode ? 0.34 : 0.42), lockedNode ? 2.8 : 3.2)
      : lockedNode
        ? Math.max(fitDistance * 0.36, 2.6)
        : flyToNode
          ? Math.max(fitDistance * 0.5, 3)
          : quadrantGroupTarget
            ? centeredGroupCameraDistance(layout, fitDistance)
            : fitDistance;
    const desiredDistance = baseDesiredDistance;
    const centerId = layout.nodes.find((node) => node.isRoot)?.id ?? "";
    const key = `${layout.perspective}:${layout.level}:${layout.group ?? ""}:${centerId}:${lockedNode?.id ?? ""}:${flyToNode?.id ?? ""}:${(layout.cameraTarget ?? []).map((n) => n.toFixed(1)).join(",")}:${(travelVia ?? []).map((n) => n.toFixed(1)).join(",")}:${fitDistance.toFixed(2)}`;
    if (key === lastKey.current && motion) {
      // Overlay transactions deliberately leave the camera untouched. Lens
      // transactions may arrive one render before their worker layout, so keep
      // those pending until cameraTarget changes.
      if (transition.intent === "overlay") lastTransitionSequence.current = transition.sequence;
      return;
    }
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
    const desiredTheta = regionTheta ?? groupTravelTheta;
    const targetPhi = regionTarget
        ? lockedNode
          ? 1.02
          : 1.08
        : quadrantGroupTarget
          ? centeredGroupCameraPhi(layout)
          : lockedNode || flyToNode
            ? 0.95
            : 0.72;
    const arcSign = groupTravelSeed >= 0.5 ? 1 : -1;
    const thetaArc = groupTravel ? arcSign * (layout.level >= 2 ? 0.58 : 0.42) : 0;
    const distanceSwell = groupTravel || lockedTravel ? Math.min(Math.max(fitDistance * (layout.level >= 2 ? 0.085 : 0.105), 0.48), 1.25) : 0;
    const targetLift = groupTravel ? groupCameraLift + (layout.level >= 2 ? 0.22 : 0.3) : lockedTravel ? 0.18 : 0;

    const fallbackIntent: MotionIntent = lockedTravel || groupTravel || quadrantGroupTarget
      ? "travel"
      : lockedNode
        ? "control"
        : regionTarget
          ? "lens"
          : "view";
    const sharedTransition =
      transition.sequence !== lastTransitionSequence.current && transition.intent !== "overlay";
    lastTransitionSequence.current = transition.sequence;
    const motionIntent = sharedTransition ? transition.intent : fallbackIntent;
    const duration = sharedTransition
      ? transition.duration
      : motionDurationSeconds(motionIntent, motionScale, !motion);
    animation.current = {
      fromTarget: currentTarget,
      viaTarget,
      toTarget: desiredTarget,
      fromDistance: firstFrame ? desiredDistance * 1.28 : currentDistance,
      toDistance: desiredDistance,
      fromPhi: currentSpherical.phi,
      toPhi: targetPhi,
      fromTheta: currentSpherical.theta,
      toTheta: desiredTheta,
      thetaArc,
      distanceSwell,
      targetLift,
      start: null,
      duration: Math.max(duration, 0.0001),
      active: true,
      intent: motionIntent
    };
    if ("fov" in camera) {
      (camera as THREE.PerspectiveCamera).fov = 40;
      (camera as THREE.PerspectiveCamera).updateProjectionMatrix();
    }
    if (!motion) {
      // Reduced motion / test mode: instant CUT.
      const spherical = new THREE.Spherical(desiredDistance, targetPhi, desiredTheta ?? currentSpherical.theta);
      camera.position.copy(desiredTarget.clone().add(new THREE.Vector3().setFromSpherical(spherical)));
      controls?.target.copy(desiredTarget);
      camera.lookAt(desiredTarget);
      controls?.update();
      animation.current = null;
      invalidate();
    }
    invalidate();
  }, [camera, cameraTargetKey, enableIntro, fitDistance, flyToNode, invalidate, layout, layout.group, layout.level, layout.perspective, lockedNode, motion, motionScale, transition.duration, transition.intent, transition.sequence, travelVia]);

  useFrame((state) => {
    const anim = animation.current;
    const controls = controlsRef.current;
    if (!anim?.active || !controls) return;
    if (anim.start === null) anim.start = state.clock.elapsedTime;
    const t = Math.min((state.clock.elapsedTime - anim.start) / anim.duration, 1);
    const eased = motionProgress(anim.intent, t);
    const travelArc = Math.sin(t * Math.PI);
    const target = anim.viaTarget
      ? anim.fromTarget
          .clone()
          .lerp(anim.viaTarget, eased)
          .lerp(anim.viaTarget.clone().lerp(anim.toTarget, eased), eased)
      : anim.fromTarget.clone().lerp(anim.toTarget, eased);
    if (anim.targetLift > 0) target.y += travelArc * anim.targetLift;
    const distance = THREE.MathUtils.lerp(anim.fromDistance, anim.toDistance, eased) + travelArc * anim.distanceSwell;
    // Quadrant flight owns azimuth so the selected region opens ahead and the
    // root stays close in the foreground. Other moves preserve user azimuth.
    const offset = camera.position.clone().sub(controls.target);
    const spherical = new THREE.Spherical().setFromVector3(
      offset.lengthSq() > 0.0001 ? offset : new THREE.Vector3(0, 1, 1)
    );
    spherical.radius = distance;
    spherical.phi = THREE.MathUtils.lerp(anim.fromPhi, anim.toPhi, eased);
    if (anim.toTheta !== null) {
      spherical.theta = lerpAngle(anim.fromTheta, anim.toTheta, eased) + travelArc * anim.thetaArc;
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
