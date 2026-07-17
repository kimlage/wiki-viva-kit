// CameraDirector: WARP (drill in), RETREAT (level up) and FOCUS (target-lock
// glide) choreography over OrbitControls. All eased and interruptible by user
// input; instant cuts under reduced motion / test mode.

import { OrbitControls } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type { LayoutNode } from "../../../scene/layout";
import type { WorldLayout } from "../../../scene/perspectives";
import {
  LOWER_MAX_POLAR_ANGLE,
  LOWER_MIN_POLAR_ANGLE,
  SOURCE_FOUNDATION_CAMERA,
  UPPER_MAX_POLAR_ANGLE,
  UPPER_MIN_POLAR_ANGLE
} from "../../../world/contracts";
import type { ViewSpatialProfileId, WorldPlaneId } from "../../../world/contracts";
import { motionDurationSeconds, motionProgress } from "../../../world/visual/motionGrammar";
import type { MotionIntent } from "../../../world/visual/motionGrammar";

// --- Hemisphere profile (§11.2) ---------------------------------------------
// The camera hemisphere is registry/worker data: it arrives on the RESOLVED
// layout as `planeProfile.cameraHemisphere` and is never read from the URL.
// The user orbits inside the view's hemisphere (allowUserHemisphereCrossing is
// false on both registered profiles); only a registered view change crosses
// the horizon, and it does so on the `outer_arc` path outside world geometry.

export type CameraHemisphere = "upper" | "lower";
export type CameraTransitionPathId = "direct" | "outer_arc";

export type CameraPolarLimits = { min: number; max: number };

export type CameraPose = {
  target: [number, number, number];
  distance: number;
  phi: number;
  theta: number;
};

export function cameraHemisphereForLayout(layout: Pick<WorldLayout, "planeProfile">): CameraHemisphere {
  return layout.planeProfile?.cameraHemisphere ?? "upper";
}

export function polarLimitsForHemisphere(hemisphere: CameraHemisphere): CameraPolarLimits {
  return hemisphere === "lower"
    ? { min: LOWER_MIN_POLAR_ANGLE, max: LOWER_MAX_POLAR_ANGLE }
    : { min: UPPER_MIN_POLAR_ANGLE, max: UPPER_MAX_POLAR_ANGLE };
}

// Only the registered outer_arc choreography may span both hemispheres; these
// limits are asserted per-frame while the arc is active and withdrawn on
// settlement, so no user gesture can keep the widened corridor open.
export const HEMISPHERE_CROSSING_POLAR_LIMITS: CameraPolarLimits = {
  min: UPPER_MIN_POLAR_ANGLE,
  max: LOWER_MAX_POLAR_ANGLE
};

export function phiHemisphere(phi: number): CameraHemisphere {
  return phi > Math.PI / 2 ? "lower" : "upper";
}

// The upper-profile framing poses (0.72 dev pose, 0.95 lock, 1.02/1.08 lens)
// mirror across the horizon in the lower profile so selection framing inside
// the foundation reads identically, just seen from below.
export function mirrorPhiForHemisphere(phi: number, hemisphere: CameraHemisphere): number {
  return hemisphere === "lower" ? Math.PI - phi : phi;
}

export function clampPhiToHemisphere(phi: number, hemisphere: CameraHemisphere): number {
  const limits = polarLimitsForHemisphere(hemisphere);
  return Math.min(Math.max(phi, limits.min), limits.max);
}

// A null previous hemisphere is the physical boot pose, which is upper: a
// deep link straight into the foundation still travels the outer arc.
export function cameraTransitionPath(
  from: CameraHemisphere | null,
  to: CameraHemisphere
): CameraTransitionPathId {
  return (from ?? "upper") === to ? "direct" : "outer_arc";
}

// Default lower framing (§6.4): look at the foundation band from below at the
// registered pose. Selection/lens framing overrides this exactly like the
// upper profile's own overrides.
export function foundationCameraPose(
  layout: Pick<WorldLayout, "planeProfile">,
  fitDistance: number
): { target: [number, number, number]; distance: number; phi: number } | null {
  if (cameraHemisphereForLayout(layout) !== "lower") return null;
  return {
    target: [0, SOURCE_FOUNDATION_CAMERA.targetY, 0],
    distance: fitDistance * SOURCE_FOUNDATION_CAMERA.distanceMultiplier,
    phi: SOURCE_FOUNDATION_CAMERA.phi
  };
}

// --- outer_arc path (§11.3) -------------------------------------------------
// A: retreat beyond the clearance radius; B: shift the look target into the
// outer corridor; C: interpolate phi across the horizon outside geometry;
// D: approach and frame the destination band. The return trip runs the same
// function with the poses swapped, which is the exact inverse path.

export const OUTER_ARC_RETREAT_END = 0.3;
export const OUTER_ARC_CROSSING_END = 0.72;
export const OUTER_ARC_CLEARANCE_MARGIN = 1.6;
const OUTER_ARC_CORRIDOR_RATIO = 0.45;

export function outerArcClearanceRadius(rOuter: number, fitDistance: number, currentDistance = 0): number {
  return Math.max(rOuter + OUTER_ARC_CLEARANCE_MARGIN, fitDistance * 1.05, currentDistance);
}

function lerpNumber(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function lerpAngle(from: number, to: number, t: number): number {
  const delta = Math.atan2(Math.sin(to - from), Math.cos(to - from));
  return from + delta * t;
}

function lerpTriple(
  a: [number, number, number],
  b: [number, number, number],
  t: number
): [number, number, number] {
  return [lerpNumber(a[0], b[0], t), lerpNumber(a[1], b[1], t), lerpNumber(a[2], b[2], t)];
}

// The corridor target sits on the camera's own azimuth, outside the world
// center and the label plane, so the crossing never sweeps the view across
// the middle of either world.
function outerArcCorridorPoint(theta: number, y: number, clearance: number): [number, number, number] {
  const radius = clearance * OUTER_ARC_CORRIDOR_RATIO;
  return [Math.sin(theta) * radius, y, Math.cos(theta) * radius];
}

export function outerArcPose(from: CameraPose, to: CameraPose, clearance: number, t: number): CameraPose {
  const clamped = Math.min(Math.max(t, 0), 1);
  if (clamped < OUTER_ARC_RETREAT_END) {
    const s = clamped / OUTER_ARC_RETREAT_END;
    const corridorFrom = outerArcCorridorPoint(from.theta, from.target[1], clearance);
    return {
      target: lerpTriple(from.target, corridorFrom, s),
      distance: lerpNumber(from.distance, clearance, s),
      phi: from.phi,
      theta: from.theta
    };
  }
  if (clamped < OUTER_ARC_CROSSING_END) {
    const s = (clamped - OUTER_ARC_RETREAT_END) / (OUTER_ARC_CROSSING_END - OUTER_ARC_RETREAT_END);
    const theta = lerpAngle(from.theta, to.theta, s);
    return {
      target: outerArcCorridorPoint(theta, lerpNumber(from.target[1], to.target[1], s), clearance),
      distance: clearance,
      phi: lerpNumber(from.phi, to.phi, s),
      theta
    };
  }
  const s = (clamped - OUTER_ARC_CROSSING_END) / (1 - OUTER_ARC_CROSSING_END);
  const corridorTo = outerArcCorridorPoint(to.theta, to.target[1], clearance);
  return {
    target: lerpTriple(corridorTo, to.target, s),
    distance: lerpNumber(clearance, to.distance, s),
    phi: to.phi,
    theta: to.theta
  };
}

// World-space camera position of a pose, in THREE.Spherical's convention.
// Exists so tests can prove the arc never enters world bounds.
export function cameraPositionForPose(pose: CameraPose): [number, number, number] {
  const sinPhi = Math.sin(pose.phi);
  return [
    pose.target[0] + pose.distance * sinPhi * Math.sin(pose.theta),
    pose.target[1] + pose.distance * Math.cos(pose.phi),
    pose.target[2] + pose.distance * sinPhi * Math.cos(pose.theta)
  ];
}

// --- Near/far/fog (§11.6) ---------------------------------------------------
// Near/far stay the scene defaults (0.1/1000): the minimum orbit distance
// (fitDistance * 0.18 ≥ ~2) keeps the closest source ports outside the near
// plane, and the whole Y=-3.2..+2.4 band span sits far inside the far plane
// with ample depth precision. Fog, however, is framed from farther below in
// the foundation pose — the upper density would erase the knowledge/core
// bands — so the sources profile thins it. This is the only §11.6 adjustment
// and it is scoped to the foundation profile.
export const UPPER_PROFILE_FOG_DENSITY = 0.032;
export const FOUNDATION_PROFILE_FOG_DENSITY = 0.018;

export function sceneFogDensity(layout: Pick<WorldLayout, "planeProfile">): number {
  return layout.planeProfile ? FOUNDATION_PROFILE_FOG_DENSITY : UPPER_PROFILE_FOG_DENSITY;
}

// --- QA diagnostics (§11.7) -------------------------------------------------
// Readback attributes for Playwright; they mirror the RESOLVED layout (never a
// pending request) and carry no route semantics.
export type CameraQaAttributes = {
  hemisphere: CameraHemisphere;
  spatialProfile: ViewSpatialProfileId;
  plane: Extract<WorldPlaneId, "foundation" | "knowledge">;
  path: CameraTransitionPathId;
};

export function cameraQaAttributes(
  layout: Pick<WorldLayout, "planeProfile">,
  previousHemisphere: CameraHemisphere | null
): CameraQaAttributes {
  const hemisphere = cameraHemisphereForLayout(layout);
  return {
    hemisphere,
    spatialProfile: layout.planeProfile ? "source-foundation" : "knowledge-upper",
    plane: layout.planeProfile?.active ?? "knowledge",
    path: cameraTransitionPath(previousHemisphere, hemisphere)
  };
}

function applyPolarLimits(controls: OrbitControlsImpl | null, limits: CameraPolarLimits): void {
  if (!controls) return;
  controls.minPolarAngle = limits.min;
  controls.maxPolarAngle = limits.max;
}

export function travelThetaFromWorldPoint(point: [number, number, number] | null | undefined): number | null {
  if (!point) return null;
  const [x, , z] = point;
  if (x * x + z * z < 0.0001) return null;
  return Math.atan2(-x, -z);
}

function isCenteredFamilyCollection(layout: WorldLayout): boolean {
  return layout.perspective === "quadrants" && layout.level >= 2 && Boolean(layout.group?.startsWith("family:"));
}

export function centeredCollectionCameraTheta(layout: WorldLayout, travelTheta: number | null): number | null {
  return isCenteredFamilyCollection(layout) ? 0 : travelTheta;
}

export function centeredGroupCameraLift(layout: WorldLayout): number {
  if (layout.perspective !== "quadrants" || layout.level < 1) return 0;
  const center = layout.nodes.find((node) => node.isRoot && node.isGroup);
  if (!center && isCenteredFamilyCollection(layout)) return 1.6;
  if (!center) return 0;
  return Math.min(Math.max(center.scale * 0.65, 0.22), 0.58);
}

export function centeredGroupSafeAreaDistanceMultiplier(layout: WorldLayout): number {
  if (layout.perspective !== "quadrants" || layout.level < 1) return 1;
  const center = layout.nodes.find((node) => node.isRoot && node.isGroup);
  const memberCount = center?.groupMemberIds?.length ?? (isCenteredFamilyCollection(layout) ? Math.max(layout.nodes.length - 1, 0) : 0);
  if ((!center && !isCenteredFamilyCollection(layout)) || memberCount < 18) return 1;
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
  if (!center && isCenteredFamilyCollection(layout)) {
    return Number((Math.max(layout.rOuter * 1.6, 5.8) * centeredGroupSafeAreaDistanceMultiplier(layout)).toFixed(4));
  }
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

export type CameraMotionState = "pending" | "settled";

export type CameraSettlementSubject = {
  sequence: number;
  active: boolean;
  start: number | null;
};

/**
 * Complete the exact camera subject even when user control interrupts it
 * before the R3F clock has supplied a first sample. A null subject is an
 * intentional no-op/cut acknowledgement for the current transaction.
 */
export function settleCameraMotion(
  subject: CameraSettlementSubject | null,
  fallbackSequence: number,
  report: (sequence: number, state: CameraMotionState) => void
): number {
  const sequence = subject?.sequence ?? fallbackSequence;
  if (subject) subject.active = false;
  report(sequence, "settled");
  return sequence;
}

export function interruptCameraMotion(
  subject: CameraSettlementSubject | null,
  currentSequence: number,
  report: (sequence: number, state: CameraMotionState) => void
): number {
  const activeSubject = subject?.active ? subject : null;
  if (activeSubject) activeSubject.sequence = currentSequence;
  return settleCameraMotion(activeSubject, currentSequence, report);
}

export function cameraRequestMustWait(layoutRequestResolved: boolean): boolean {
  return !layoutRequestResolved;
}

export function CameraDirector({
  layout,
  layoutRequestResolved,
  lockedNode,
  flyToNode = null,
  travelVia = null,
  enableIntro,
  motion,
  motionScale = 1,
  transition,
  onMotionState
}: {
  layout: WorldLayout;
  layoutRequestResolved: boolean;
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
  onMotionState: (sequence: number, state: CameraMotionState) => void;
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
    sequence: number;
    // Destination hemisphere of this camera subject; its polar limits are
    // applied on settlement (or interruption), never before.
    hemisphere: CameraHemisphere;
    // Present only on a registered hemisphere crossing: the §11.3 outer arc.
    arc: { from: CameraPose; to: CameraPose; clearance: number } | null;
  } | null>(null);
  const lastKey = useRef("");
  const lastTransitionSequence = useRef(0);
  const lastMotionReport = useRef<{ sequence: number; state: CameraMotionState } | null>(null);
  const reportMotionState = useCallback((sequence: number, state: CameraMotionState) => {
    const previous = lastMotionReport.current;
    if (previous?.sequence === sequence && previous.state === state) return;
    lastMotionReport.current = { sequence, state };
    onMotionState(sequence, state);
  }, [onMotionState]);

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
    // Hemisphere comes from the RESOLVED layout (§11.2); the default lower
    // framing (§6.4) applies when nothing more specific frames the world.
    const hemisphere = cameraHemisphereForLayout(layout);
    const foundationPose =
      !lockedNode && !flyToNode && !regionTarget ? foundationCameraPose(layout, fitDistance) : null;
    const baseDesiredTarget = regionTarget
      ? regionTarget.clone().multiplyScalar(lockedNode ? 0.72 : 0.62)
      : lockedNode
        ? new THREE.Vector3(...lockedNode.position)
        : flyToNode
          ? new THREE.Vector3(...flyToNode.position)
          : quadrantGroupTarget
            ? quadrantGroupTarget.clone().setY(groupCameraLift)
            : new THREE.Vector3(0, 0, 0);
    const desiredTarget = foundationPose ? new THREE.Vector3(...foundationPose.target) : baseDesiredTarget;
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
    const desiredDistance = foundationPose ? foundationPose.distance : baseDesiredDistance;
    const centerId = layout.nodes.find((node) => node.isRoot)?.id ?? "";
    const key = `${hemisphere}:${layout.perspective}:${layout.level}:${layout.group ?? ""}:${centerId}:${lockedNode?.id ?? ""}:${flyToNode?.id ?? ""}:${(layout.cameraTarget ?? []).map((n) => n.toFixed(1)).join(",")}:${(travelVia ?? []).map((n) => n.toFixed(1)).join(",")}:${fitDistance.toFixed(2)}`;
    if (cameraRequestMustWait(layoutRequestResolved)) {
      // Route state is ahead of the exact worker result. Cancel the obsolete
      // camera subject and keep this sequence pending; neither a moving old
      // camera, a no-op nor a reduced-motion cut against old geometry may
      // acknowledge any new semantic subject. The request-bound commit will
      // rerun this effect.
      if (animation.current) animation.current.active = false;
      animation.current = null;
      reportMotionState(transition.sequence, "pending");
      return;
    }
    if (key === lastKey.current && motion) {
      // An exact resolved request may intentionally leave the camera key
      // untouched (overlay or semantic no-op). If an older camera is still
      // moving, the newest sequence inherits that physical subject.
      const currentAnimation = animation.current;
      if (currentAnimation?.active) {
        // A newer semantic transaction inherits the camera that is physically
        // still moving; the eventual acknowledgement belongs to the newest
        // sequence, never to the obsolete cue.
        currentAnimation.sequence = transition.sequence;
        lastTransitionSequence.current = transition.sequence;
        reportMotionState(transition.sequence, "pending");
      } else {
        lastTransitionSequence.current = transition.sequence;
        settleCameraMotion(null, transition.sequence, reportMotionState);
      }
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
    const desiredTheta = regionTheta ?? centeredCollectionCameraTheta(layout, groupTravelTheta);
    const upperProfilePhi = regionTarget
        ? lockedNode
          ? 1.02
          : 1.08
        : quadrantGroupTarget
          ? centeredGroupCameraPhi(layout)
          : lockedNode || flyToNode
            ? 0.95
            : 0.72;
    // Framing poses mirror across the horizon in the lower profile and are
    // always clamped inside the view's own hemisphere (§11.2).
    const targetPhi = foundationPose
      ? foundationPose.phi
      : clampPhiToHemisphere(mirrorPhiForHemisphere(upperProfilePhi, hemisphere), hemisphere);
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
    reportMotionState(transition.sequence, "pending");
    // A hemisphere crossing is decided by the PHYSICAL camera phi, so an
    // interrupted or deep-linked pose still travels the outer arc instead of
    // lerping straight through world geometry (§11.3).
    const path = cameraTransitionPath(phiHemisphere(currentSpherical.phi), phiHemisphere(targetPhi));
    const arc =
      path === "outer_arc"
        ? {
            from: {
              target: [currentTarget.x, currentTarget.y, currentTarget.z] as [number, number, number],
              distance: currentDistance,
              phi: currentSpherical.phi,
              theta: currentSpherical.theta
            },
            to: {
              target: [desiredTarget.x, desiredTarget.y, desiredTarget.z] as [number, number, number],
              distance: desiredDistance,
              phi: targetPhi,
              theta: desiredTheta ?? currentSpherical.theta
            },
            clearance: outerArcClearanceRadius(layout.rOuter, fitDistance, currentDistance)
          }
        : null;
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
      intent: motionIntent,
      sequence: transition.sequence,
      hemisphere,
      arc
    };
    // Same clock, same handshake: the crossing only widens the polar corridor
    // while its own subject is active; every other subject keeps the exact
    // limits of its destination hemisphere.
    applyPolarLimits(controls, arc ? HEMISPHERE_CROSSING_POLAR_LIMITS : polarLimitsForHemisphere(hemisphere));
    if ("fov" in camera) {
      (camera as THREE.PerspectiveCamera).fov = 40;
      (camera as THREE.PerspectiveCamera).updateProjectionMatrix();
    }
    if (!motion) {
      // Reduced motion / test mode: instant CUT — no arc, straight to the
      // destination hemisphere pose with its exact polar limits, settled in
      // the same sequence so labels are already correct on first paint (§11.5).
      applyPolarLimits(controls, polarLimitsForHemisphere(hemisphere));
      const spherical = new THREE.Spherical(desiredDistance, targetPhi, desiredTheta ?? currentSpherical.theta);
      camera.position.copy(desiredTarget.clone().add(new THREE.Vector3().setFromSpherical(spherical)));
      controls?.target.copy(desiredTarget);
      camera.lookAt(desiredTarget);
      controls?.update();
      settleCameraMotion(animation.current, transition.sequence, reportMotionState);
      animation.current = null;
      invalidate();
    }
    invalidate();
  }, [camera, cameraTargetKey, enableIntro, fitDistance, flyToNode, invalidate, layout, layout.group, layout.level, layout.perspective, layoutRequestResolved, lockedNode, motion, motionScale, reportMotionState, transition.duration, transition.intent, transition.sequence, travelVia]);

  useFrame((state) => {
    const anim = animation.current;
    const controls = controlsRef.current;
    if (!anim?.active) return;
    if (anim.start === null) anim.start = state.clock.elapsedTime;
    const t = Math.min((state.clock.elapsedTime - anim.start) / anim.duration, 1);
    const eased = motionProgress(anim.intent, t);
    if (anim.arc) {
      // Registered hemisphere crossing (§11.3): follow the outer arc on the
      // shared clock/sequence. Limits are re-asserted before update() every
      // frame so an intermediate render can never clamp the crossing pose.
      applyPolarLimits(controls, HEMISPHERE_CROSSING_POLAR_LIMITS);
      const pose = outerArcPose(anim.arc.from, anim.arc.to, anim.arc.clearance, eased);
      const arcTarget = new THREE.Vector3(...pose.target);
      const arcSpherical = new THREE.Spherical(pose.distance, pose.phi, pose.theta);
      controls?.target.copy(arcTarget);
      camera.position.copy(arcTarget.clone().add(new THREE.Vector3().setFromSpherical(arcSpherical)));
      camera.lookAt(arcTarget);
      controls?.update();
      state.invalidate();
      if (t >= 1) {
        applyPolarLimits(controls, polarLimitsForHemisphere(anim.hemisphere));
        settleCameraMotion(anim, transition.sequence, reportMotionState);
      }
      return;
    }
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
    const offset = camera.position.clone().sub(controls?.target ?? anim.fromTarget);
    const spherical = new THREE.Spherical().setFromVector3(
      offset.lengthSq() > 0.0001 ? offset : new THREE.Vector3(0, 1, 1)
    );
    spherical.radius = distance;
    spherical.phi = THREE.MathUtils.lerp(anim.fromPhi, anim.toPhi, eased);
    if (anim.toTheta !== null) {
      spherical.theta = lerpAngle(anim.fromTheta, anim.toTheta, eased) + travelArc * anim.thetaArc;
    }
    controls?.target.copy(target);
    camera.position.copy(target.clone().add(new THREE.Vector3().setFromSpherical(spherical)));
    camera.lookAt(target);
    controls?.update();
    state.invalidate();
    if (t >= 1) settleCameraMotion(anim, transition.sequence, reportMotionState);
  });

  // Dynamic per-view polar constraints (§11.2): the user orbits strictly
  // inside the resolved view's hemisphere; no manual gesture can cross the
  // horizon (allowUserHemisphereCrossing=false on both registered profiles).
  const viewPolarLimits = polarLimitsForHemisphere(cameraHemisphereForLayout(layout));
  return (
    <OrbitControls
      ref={controlsRef}
      enablePan={false}
      minDistance={fitDistance * 0.18}
      maxDistance={fitDistance * 1.6}
      minPolarAngle={viewPolarLimits.min}
      maxPolarAngle={viewPolarLimits.max}
      enableDamping
      onStart={() => {
        // User input interrupts any camera choreography immediately. An
        // interrupted crossing settles into the view's own hemisphere: its
        // widened corridor is withdrawn before the user gesture is applied.
        lastTransitionSequence.current = transition.sequence;
        applyPolarLimits(controlsRef.current, viewPolarLimits);
        interruptCameraMotion(animation.current, transition.sequence, reportMotionState);
      }}
    />
  );
}
