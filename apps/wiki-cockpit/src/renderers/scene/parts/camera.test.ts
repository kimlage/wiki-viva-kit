import { describe, expect, it, vi } from "vitest";
import {
  FOUNDATION_PROFILE_FOG_DENSITY,
  HEMISPHERE_CROSSING_POLAR_LIMITS,
  OUTER_ARC_CROSSING_END,
  OUTER_ARC_RETREAT_END,
  UPPER_PROFILE_FOG_DENSITY,
  cameraHemisphereForLayout,
  cameraPositionForPose,
  cameraQaAttributes,
  cameraRequestMustWait,
  cameraTransitionPath,
  centeredCollectionCameraTheta,
  centeredGroupCameraDistance,
  centeredGroupCameraLift,
  centeredGroupCameraPhi,
  centeredGroupSafeAreaDistanceMultiplier,
  clampPhiToHemisphere,
  FOUNDATION_BAND_FRAME_DISTANCE_MULTIPLIER,
  foundationBandFramePose,
  foundationCameraPose,
  foundationSelectionReleaseHold,
  hoverInspectionCameraTarget,
  hoverInspectionCameraWeight,
  hoverInspectionDistanceMultiplier,
  interruptCameraMotion,
  mirrorPhiForHemisphere,
  outerArcClearanceRadius,
  outerArcPose,
  phiHemisphere,
  polarLimitsForHemisphere,
  sceneFogDensity,
  settleCameraMotion,
  travelThetaFromWorldPoint
} from "./camera";
import type { CameraPose } from "./camera";
import type { LayoutNode } from "../../../scene/layout";
import type { WorldLayout } from "../../../scene/perspectives";
import {
  LOWER_MAX_POLAR_ANGLE,
  LOWER_MIN_POLAR_ANGLE,
  SOURCE_FOUNDATION_CAMERA,
  SOURCE_FOUNDATION_LEVELS,
  UPPER_MAX_POLAR_ANGLE,
  UPPER_MIN_POLAR_ANGLE
} from "../../../world/contracts";
import { createDefaultKernel } from "../../../world/registries/RegistryKernel";

function quadrantLayout(scale: number, level: 1 | 2, memberCount = 1): WorldLayout {
  return {
    perspective: "quadrants",
    level,
    group: level === 1 ? "region:pratica" : "region:pratica:family:source",
    radial: "orbit",
    nodes: [
      {
        id: level === 1 ? "region:pratica" : "region:pratica:family:source",
        path: level === 1 ? "region:pratica" : "region:pratica:family:source",
        title: "Outputs & evidence",
        context: "system",
        page_type: level === 1 ? "visual_group_region" : "visual_group_source",
        freshness_state: "fresh",
        approved_state: "approved",
        risk_flags: [],
        source_ref_count: 0,
        inbound_links: 0,
        outbound_links: 0,
        ageDays: 0,
        overdueRatio: 0,
        isHub: true,
        isRoot: true,
        position: [0, 0, 0],
        scale,
        isGroup: true,
        groupKind: level === 1 ? "quadrant" : "region_family",
        groupMemberIds: Array.from({ length: memberCount }, (_, index) => `member-${index}`)
      }
    ],
    wedges: [],
    wedgeKind: "group",
    guides: [],
    groups: [],
    clusterStars: [],
    beacons: [],
    rInner: 1.7,
    rOuter: 3.6,
    deadlineF: 0.7,
    unknownR: null,
    totals: { total: 1, shown: 1, hidden: 0 },
    truncated: 0
  };
}

function layoutNode(overrides: Partial<LayoutNode> & Pick<LayoutNode, "id">): LayoutNode {
  const { id, ...rest } = overrides;
  return {
    id,
    path: overrides.path ?? id,
    title: overrides.title ?? id,
    context: overrides.context ?? "system",
    page_type: overrides.page_type ?? "artifact",
    freshness_state: overrides.freshness_state ?? "fresh",
    approved_state: overrides.approved_state ?? "approved",
    risk_flags: overrides.risk_flags ?? [],
    source_ref_count: overrides.source_ref_count ?? 0,
    inbound_links: overrides.inbound_links ?? 0,
    outbound_links: overrides.outbound_links ?? 0,
    ageDays: overrides.ageDays ?? 0,
    overdueRatio: overrides.overdueRatio ?? 0,
    isHub: overrides.isHub ?? false,
    isRoot: overrides.isRoot ?? false,
    position: overrides.position ?? [0, 0, 0],
    scale: overrides.scale ?? 0.2,
    ...rest
  };
}

describe("quadrant camera travel", () => {
  it("aims drill travel from the selected object's previous world position", () => {
    expect(travelThetaFromWorldPoint([0, 0, -3])).toBeCloseTo(0);
    expect(travelThetaFromWorldPoint([3, 0, 0])).toBeCloseTo(-Math.PI / 2);
    expect(travelThetaFromWorldPoint([0, 0, 0])).toBeNull();
  });

  it("lifts the camera target onto the centered group body during quadrant drill", () => {
    expect(centeredGroupCameraLift(quadrantLayout(0.62, 1))).toBeGreaterThan(0.36);
    expect(centeredGroupCameraLift({ ...quadrantLayout(0.62, 1), perspective: "radar", level: 0 })).toBe(0);
  });

  it("keeps enough distance to see the central group and its surrounding drill context", () => {
    const shallow = centeredGroupCameraDistance(quadrantLayout(0.62, 1), 8);
    const deep = centeredGroupCameraDistance(quadrantLayout(0.7, 2), 8);

    expect(shallow).toBeGreaterThan(5.2);
    expect(deep).toBeGreaterThan(5.5);
    expect(deep).toBeGreaterThan(0.7 * 3.25 * 3.4);
  });

  it("centers a real-page family collection after travelling from its quadrant", () => {
    const layout = quadrantLayout(0.46, 2, 13);
    layout.group = "family:source";
    layout.nodes = [
      layoutNode({ id: "root-alex-rivera", isRoot: true, isHub: true, scale: 0.46 }),
      ...Array.from({ length: 13 }, (_, index) => layoutNode({ id: `source-${index}`, page_type: "source" }))
    ];

    expect(centeredCollectionCameraTheta(layout, -Math.PI / 2)).toBe(0);
    expect(centeredGroupCameraLift(layout)).toBeGreaterThan(0);
    expect(centeredGroupCameraDistance(layout, 9)).toBeGreaterThanOrEqual(5.8);
    expect(centeredGroupCameraDistance(layout, 9)).toBeLessThan(9);
  });

  it("adds bounded safe-area breathing room for dense grouped drills", () => {
    const sparse = quadrantLayout(0.7, 2, 8);
    const dense = quadrantLayout(0.7, 2, 45);
    const nonQuadrant: WorldLayout = { ...dense, perspective: "radar", level: 0 };

    expect(centeredGroupSafeAreaDistanceMultiplier(sparse)).toBe(1);
    expect(centeredGroupSafeAreaDistanceMultiplier(dense)).toBeGreaterThan(1);
    expect(centeredGroupSafeAreaDistanceMultiplier(dense)).toBeGreaterThan(1.2);
    expect(centeredGroupSafeAreaDistanceMultiplier(dense)).toBeLessThanOrEqual(1.34);
    expect(centeredGroupSafeAreaDistanceMultiplier(nonQuadrant)).toBe(1);
    expect(centeredGroupCameraDistance(dense, 8)).toBeGreaterThan(centeredGroupCameraDistance(sparse, 8));
    expect(centeredGroupCameraPhi(dense)).toBeLessThan(centeredGroupCameraPhi(sparse));
    expect(centeredGroupCameraPhi(dense)).toBeLessThan(0.7);
  });

  it("keeps hover as inspection only and never biases the camera", () => {
    const center = quadrantLayout(0.7, 2, 42);
    const navigable = layoutNode({
      id: "region:pratica:family:event",
      page_type: "visual_group_event",
      isGroup: true,
      groupDrill: { group: "region:pratica:family:event" },
      position: [3, 0.2, -1],
      scale: 0.36
    });
    const conceptual = layoutNode({
      id: "region:sistemas",
      page_type: "visual_group_region",
      isGroup: true,
      position: [-2, 0, 1],
      scale: 0.32
    });
    const practicalPage = layoutNode({
      id: "source-a",
      page_type: "source",
      source_ref_count: 12,
      position: [1.5, 0, 2],
      scale: 0.22
    });
    const root = layoutNode({
      id: "region:pratica:family:source",
      isRoot: true,
      isGroup: true
    });

    expect(hoverInspectionCameraWeight(center, navigable)).toBe(0);
    expect(hoverInspectionCameraWeight(center, conceptual)).toBe(0);
    expect(hoverInspectionCameraWeight(center, practicalPage)).toBe(0);
    expect(hoverInspectionCameraWeight(quadrantLayout(0.7, 1, 42), practicalPage)).toBe(0);
    expect(hoverInspectionCameraWeight({ ...center, perspective: "radar", level: 0 }, navigable)).toBe(0);
    expect(hoverInspectionCameraWeight(center, root)).toBe(0);

    expect(hoverInspectionCameraTarget(center, navigable)).toBeNull();
    expect(hoverInspectionDistanceMultiplier(center, navigable)).toBe(1);
    expect(hoverInspectionDistanceMultiplier(center, conceptual)).toBe(1);
    expect(hoverInspectionDistanceMultiplier(center, root)).toBe(1);
  });
});

// --- Lower-hemisphere camera profile (§11, tests per §19.5) -----------------

const FOUNDATION_R_OUTER = 5.75;

function foundationLayout(): WorldLayout {
  return {
    ...quadrantLayout(0.4, 1),
    perspective: "sources",
    level: 0,
    group: undefined,
    rInner: 1.0,
    rOuter: FOUNDATION_R_OUTER,
    planeProfile: {
      active: "foundation",
      levels: { ...SOURCE_FOUNDATION_LEVELS },
      cameraHemisphere: "lower",
      transitionPath: "outer_arc",
      occlusionPolicy: "foundation-first",
      labelPolicy: "camera-facing"
    }
  };
}

function upperLayout(): WorldLayout {
  return { ...quadrantLayout(0.4, 1), level: 0, group: undefined };
}

describe("hemisphere resolution (§11.2)", () => {
  it("resolves sources to the lower hemisphere and every other view to upper", () => {
    const kernel = createDefaultKernel();
    for (const view of kernel.views.values()) {
      expect(view.cameraProfile.hemisphere).toBe(view.id === "sources" ? "lower" : "upper");
      expect(view.cameraProfile.allowUserHemisphereCrossing).toBe(false);
    }
    expect(cameraHemisphereForLayout(foundationLayout())).toBe("lower");
    expect(cameraHemisphereForLayout(upperLayout())).toBe("upper");
    // A sources layout WITHOUT the foundation payload is the v8 compat world
    // and stays upper.
    expect(cameraHemisphereForLayout({ ...foundationLayout(), planeProfile: undefined })).toBe("upper");
  });

  it("applies dynamic per-view polar limits mirrored across the horizon", () => {
    expect(polarLimitsForHemisphere("upper")).toEqual({ min: 0.3, max: 1.25 });
    expect(polarLimitsForHemisphere("lower")).toEqual({ min: Math.PI - 1.25, max: Math.PI - 0.3 });
    expect(polarLimitsForHemisphere("upper")).toEqual({ min: UPPER_MIN_POLAR_ANGLE, max: UPPER_MAX_POLAR_ANGLE });
    expect(polarLimitsForHemisphere("lower")).toEqual({ min: LOWER_MIN_POLAR_ANGLE, max: LOWER_MAX_POLAR_ANGLE });
  });

  it("makes manual hemisphere crossing impossible inside either profile", () => {
    // The horizon sits strictly between the two bands…
    expect(UPPER_MAX_POLAR_ANGLE).toBeLessThan(Math.PI / 2);
    expect(LOWER_MIN_POLAR_ANGLE).toBeGreaterThan(Math.PI / 2);
    // …so any user phi, clamped to the view's own limits, keeps its hemisphere.
    expect(phiHemisphere(clampPhiToHemisphere(Math.PI - 0.05, "upper"))).toBe("upper");
    expect(phiHemisphere(clampPhiToHemisphere(0.05, "lower"))).toBe("lower");
    expect(clampPhiToHemisphere(Math.PI / 2, "upper")).toBe(UPPER_MAX_POLAR_ANGLE);
    expect(clampPhiToHemisphere(Math.PI / 2, "lower")).toBe(LOWER_MIN_POLAR_ANGLE);
  });

  it("mirrors the upper framing poses across the horizon for the lower profile", () => {
    expect(mirrorPhiForHemisphere(0.95, "lower")).toBeCloseTo(Math.PI - 0.95);
    expect(mirrorPhiForHemisphere(0.95, "upper")).toBe(0.95);
    // Every upper framing pose lands inside the lower limits once mirrored.
    for (const phi of [0.72, 0.95, 1.02, 1.08]) {
      const mirrored = clampPhiToHemisphere(mirrorPhiForHemisphere(phi, "lower"), "lower");
      expect(mirrored).toBeGreaterThanOrEqual(LOWER_MIN_POLAR_ANGLE);
      expect(mirrored).toBeLessThanOrEqual(LOWER_MAX_POLAR_ANGLE);
      expect(mirrored).toBeCloseTo(Math.PI - phi);
    }
  });

  it("frames the foundation from below at the registered §6.4 pose on any viewport fit", () => {
    const wide = foundationCameraPose(foundationLayout(), 17.6);
    const mobile = foundationCameraPose(foundationLayout(), 11.2);
    expect(wide).not.toBeNull();
    expect(wide!.target).toEqual([0, SOURCE_FOUNDATION_LEVELS.foundation + 0.25, 0]);
    expect(wide!.target[1]).toBe(SOURCE_FOUNDATION_CAMERA.targetY);
    expect(wide!.phi).toBeCloseTo(Math.PI - 0.72);
    expect(wide!.distance).toBeCloseTo(17.6 * SOURCE_FOUNDATION_CAMERA.distanceMultiplier);
    // R3 framing: the resting pose frames the CONTENT (station ring foreground,
    // core up-frame), noticeably closer than the full retreat fit but always
    // safely above the orbit minimum, so nothing clips against the near plane.
    expect(SOURCE_FOUNDATION_CAMERA.distanceMultiplier).toBeLessThan(1);
    expect(SOURCE_FOUNDATION_CAMERA.distanceMultiplier).toBeGreaterThan(0.18 * 2);
    // Resize/aspect: the pose scales with the layout fit, nothing else.
    expect(mobile!.distance).toBeCloseTo(11.2 * SOURCE_FOUNDATION_CAMERA.distanceMultiplier);
    expect(mobile!.phi).toBe(wide!.phi);
    // The camera really sits below the foundation band, looking up.
    const eye = cameraPositionForPose({ target: wide!.target, distance: wide!.distance, phi: wide!.phi, theta: 0 });
    expect(eye[1]).toBeLessThan(SOURCE_FOUNDATION_LEVELS.foundation);
    // The core anchor stays inside the 40° vertical FOV at the resting pose:
    // the angle between the view axis and the core direction is < vFov/2.
    const target = wide!.target;
    const core: [number, number, number] = [0, SOURCE_FOUNDATION_LEVELS.core, 0];
    const view = [target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]];
    const toCore = [core[0] - eye[0], core[1] - eye[1], core[2] - eye[2]];
    const dot = view[0] * toCore[0] + view[1] * toCore[1] + view[2] * toCore[2];
    const angle = Math.acos(dot / (Math.hypot(...view) * Math.hypot(...toCore)));
    expect(angle).toBeLessThan((40 / 2) * (Math.PI / 180));
    expect(foundationCameraPose(upperLayout(), 17.6)).toBeNull();
  });

  it("frames a clicked band at ITS structural level with the registered pose (R4 — no free flight)", () => {
    const layout = foundationLayout();
    for (const plane of ["core", "knowledge", "provenance", "foundation"] as const) {
      const pose = foundationBandFramePose(layout, 17.6, plane)!;
      expect(pose).not.toBeNull();
      // Target rides the band's exact structural Y — never an invented level.
      expect(pose.target).toEqual([0, SOURCE_FOUNDATION_LEVELS[plane], 0]);
      // Same registered lower phi as the resting pose: framing, not free flight.
      expect(pose.phi).toBe(SOURCE_FOUNDATION_CAMERA.phi);
      expect(phiHemisphere(pose.phi)).toBe("lower");
      // Tighter than the resting fit but above the orbit minimum (0.18 × fit).
      expect(pose.distance).toBeCloseTo(17.6 * FOUNDATION_BAND_FRAME_DISTANCE_MULTIPLIER);
      expect(FOUNDATION_BAND_FRAME_DISTANCE_MULTIPLIER).toBeLessThan(SOURCE_FOUNDATION_CAMERA.distanceMultiplier);
      expect(FOUNDATION_BAND_FRAME_DISTANCE_MULTIPLIER).toBeGreaterThan(0.18);
    }
    // Null without a band, outside the foundation profile, or in the upper world.
    expect(foundationBandFramePose(layout, 17.6, null)).toBeNull();
    expect(foundationBandFramePose(upperLayout(), 17.6, "foundation")).toBeNull();
  });

  it("holds the exact camera pose when a foundation selection is released (R3)", () => {
    // Click on empty space / Escape releases the lock ONLY: same base framing
    // subject, lock removed → the camera must not retreat or change zoom.
    expect(
      foundationSelectionReleaseHold({
        foundationProfile: true,
        previousLockedId: "source-a",
        lockedId: "",
        flyToId: "",
        baseKeyUnchanged: true
      })
    ).toBe(true);
    // Selecting another station is a focus glide, never a hold.
    expect(
      foundationSelectionReleaseHold({
        foundationProfile: true,
        previousLockedId: "source-a",
        lockedId: "source-b",
        flyToId: "",
        baseKeyUnchanged: true
      })
    ).toBe(false);
    // A world change (view/level/fit) re-frames even when the lock drops.
    expect(
      foundationSelectionReleaseHold({
        foundationProfile: true,
        previousLockedId: "source-a",
        lockedId: "",
        flyToId: "",
        baseKeyUnchanged: false
      })
    ).toBe(false);
    // Outside the foundation profile the existing contract stays untouched.
    expect(
      foundationSelectionReleaseHold({
        foundationProfile: false,
        previousLockedId: "page-1",
        lockedId: "",
        flyToId: "",
        baseKeyUnchanged: true
      })
    ).toBe(false);
    // A newborn being witnessed still owns the camera.
    expect(
      foundationSelectionReleaseHold({
        foundationProfile: true,
        previousLockedId: "source-a",
        lockedId: "",
        flyToId: "born-1",
        baseKeyUnchanged: true
      })
    ).toBe(false);
    // No previous lock: entering the view frames normally.
    expect(
      foundationSelectionReleaseHold({
        foundationProfile: true,
        previousLockedId: "",
        lockedId: "",
        flyToId: "",
        baseKeyUnchanged: true
      })
    ).toBe(false);
  });
});

describe("outer_arc transition (§11.3)", () => {
  const from: CameraPose = { target: [0, 0, 0], distance: 8, phi: 0.72, theta: 0.4 };
  const to: CameraPose = {
    target: [0, SOURCE_FOUNDATION_CAMERA.targetY, 0],
    distance: 19,
    phi: Math.PI - 0.72,
    theta: -0.6
  };
  const clearance = outerArcClearanceRadius(FOUNDATION_R_OUTER, 17.6, from.distance);

  it("registers outer_arc exactly for hemisphere changes, in both directions", () => {
    expect(cameraTransitionPath("upper", "lower")).toBe("outer_arc");
    expect(cameraTransitionPath("lower", "upper")).toBe("outer_arc");
    expect(cameraTransitionPath("upper", "upper")).toBe("direct");
    expect(cameraTransitionPath("lower", "lower")).toBe("direct");
    // The physical boot pose is upper: a deep link into sources still arcs.
    expect(cameraTransitionPath(null, "lower")).toBe("outer_arc");
    expect(cameraTransitionPath(null, "upper")).toBe("direct");
  });

  it("retreats beyond the world before crossing and lands exactly on both endpoints", () => {
    expect(clearance).toBeGreaterThan(FOUNDATION_R_OUTER + 1.5);
    const start = outerArcPose(from, to, clearance, 0);
    const end = outerArcPose(from, to, clearance, 1);
    expect(start).toEqual(from);
    expect(end.target).toEqual(to.target);
    expect(end.distance).toBeCloseTo(to.distance);
    expect(end.phi).toBeCloseTo(to.phi);
    // During the whole crossing phase the orbit radius holds the clearance.
    for (let t = OUTER_ARC_RETREAT_END + 0.001; t < OUTER_ARC_CROSSING_END; t += 0.05) {
      expect(outerArcPose(from, to, clearance, t).distance).toBeCloseTo(clearance);
    }
  });

  it("crosses the horizon outside world bounds, away from the center and the label plane", () => {
    for (let t = 0; t <= 1.0001; t += 0.01) {
      const pose = outerArcPose(from, to, clearance, t);
      const eye = cameraPositionForPose(pose);
      const eyeHorizontal = Math.hypot(eye[0], eye[2]);
      const bandTop = SOURCE_FOUNDATION_LEVELS.core + 0.4;
      const bandBottom = SOURCE_FOUNDATION_LEVELS.foundation - 0.4;
      if (eye[1] < bandTop && eye[1] > bandBottom) {
        // Whenever the camera's height is inside the world's band span it must
        // be far outside the world's horizontal extent.
        expect(eyeHorizontal).toBeGreaterThan(FOUNDATION_R_OUTER + 1);
      }
      if (t > OUTER_ARC_RETREAT_END && t < OUTER_ARC_CROSSING_END) {
        // The look target rides the outer corridor: never the world center.
        const targetHorizontal = Math.hypot(pose.target[0], pose.target[2]);
        expect(targetHorizontal).toBeGreaterThan(FOUNDATION_R_OUTER);
      }
    }
  });

  it("runs the return trip lower→upper as the same safe arc", () => {
    const start = outerArcPose(to, from, clearance, 0);
    const end = outerArcPose(to, from, clearance, 1);
    expect(start).toEqual(to);
    expect(end.phi).toBeCloseTo(from.phi);
    expect(end.target).toEqual(from.target);
    for (let t = 0; t <= 1.0001; t += 0.01) {
      const eye = cameraPositionForPose(outerArcPose(to, from, clearance, t));
      if (eye[1] < SOURCE_FOUNDATION_LEVELS.core + 0.4 && eye[1] > SOURCE_FOUNDATION_LEVELS.foundation - 0.4) {
        expect(Math.hypot(eye[0], eye[2])).toBeGreaterThan(FOUNDATION_R_OUTER + 1);
      }
    }
    // Round trip sources→quadrants→sources restores the hemisphere contract.
    const trip = ["lower", "upper", "lower"] as const;
    expect(cameraTransitionPath(trip[0], trip[1])).toBe("outer_arc");
    expect(cameraTransitionPath(trip[1], trip[2])).toBe("outer_arc");
    expect(polarLimitsForHemisphere(trip[2])).toEqual(polarLimitsForHemisphere(trip[0]));
  });

  it("only the crossing corridor spans both hemispheres and it is bounded by the profile limits", () => {
    expect(HEMISPHERE_CROSSING_POLAR_LIMITS).toEqual({ min: UPPER_MIN_POLAR_ANGLE, max: LOWER_MAX_POLAR_ANGLE });
  });
});

describe("settlement handshake (§11.4/§11.5)", () => {
  it("settles an interrupted transition into the interrupting sequence", () => {
    const reports: Array<[number, string]> = [];
    const subject = { sequence: 3, active: true, start: 0.25 };
    const settled = interruptCameraMotion(subject, 5, (sequence, state) => reports.push([sequence, state]));
    expect(settled).toBe(5);
    expect(subject.active).toBe(false);
    expect(reports).toEqual([[5, "settled"]]);
  });

  it("acknowledges a no-op with the newest sequence when nothing is moving", () => {
    const report = vi.fn();
    expect(interruptCameraMotion(null, 7, report)).toBe(7);
    expect(settleCameraMotion(null, 7, report)).toBe(7);
    expect(report).toHaveBeenCalledWith(7, "settled");
  });

  it("never confirms a stale request: an unresolved layout keeps the camera pending", () => {
    expect(cameraRequestMustWait(false)).toBe(true);
    expect(cameraRequestMustWait(true)).toBe(false);
  });

  it("reduced motion cuts straight to the destination pose with no residual arc", () => {
    // The instant cut is by definition the t=1 pose of the same subject: one
    // clock, one sequence, labels correct on first paint.
    const from: CameraPose = { target: [0, 0, 0], distance: 8, phi: 0.72, theta: 0 };
    const to: CameraPose = { target: [0, SOURCE_FOUNDATION_CAMERA.targetY, 0], distance: 19, phi: SOURCE_FOUNDATION_CAMERA.phi, theta: 0 };
    const cut = outerArcPose(from, to, outerArcClearanceRadius(FOUNDATION_R_OUTER, 17.6), 1);
    expect(cut.target).toEqual(to.target);
    expect(cut.phi).toBe(to.phi);
    expect(cut.distance).toBe(to.distance);
    expect(phiHemisphere(cut.phi)).toBe("lower");
  });
});

describe("near/far/fog and QA diagnostics (§11.6/§11.7)", () => {
  it("thins the fog only inside the sources foundation profile", () => {
    expect(sceneFogDensity(foundationLayout())).toBe(FOUNDATION_PROFILE_FOG_DENSITY);
    expect(sceneFogDensity(upperLayout())).toBe(UPPER_PROFILE_FOG_DENSITY);
    expect(FOUNDATION_PROFILE_FOG_DENSITY).toBeLessThan(UPPER_PROFILE_FOG_DENSITY);
  });

  it("exposes hemisphere/profile/plane/path readback for the resolved layout only", () => {
    expect(cameraQaAttributes(foundationLayout(), "upper")).toEqual({
      hemisphere: "lower",
      spatialProfile: "source-foundation",
      plane: "foundation",
      path: "outer_arc"
    });
    expect(cameraQaAttributes(upperLayout(), "lower")).toEqual({
      hemisphere: "upper",
      spatialProfile: "knowledge-upper",
      plane: "knowledge",
      path: "outer_arc"
    });
    expect(cameraQaAttributes(upperLayout(), "upper").path).toBe("direct");
    expect(cameraQaAttributes(upperLayout(), null).path).toBe("direct");
    expect(cameraQaAttributes(foundationLayout(), null).path).toBe("outer_arc");
  });
});
