// Spatial/camera profile registration (plan §7.1/§11.2): every view declares
// its profile explicitly; only `sources` activates the source-foundation
// plane and the lower-hemisphere camera profile. The lower polar limits are
// the exact mirror of the upper ones, and no profile permits free manual
// hemisphere crossing — only a registered view change crosses the horizon.

import { describe, expect, it } from "vitest";
import {
  LOWER_MAX_POLAR_ANGLE,
  LOWER_MIN_POLAR_ANGLE,
  SOURCE_FOUNDATION_CAMERA,
  SOURCE_FOUNDATION_LEVELS,
  UPPER_MAX_POLAR_ANGLE,
  UPPER_MIN_POLAR_ANGLE,
  VIEW_IDS
} from "../contracts";
import { createDefaultKernel } from "./RegistryKernel";

describe("registry spatial/camera profiles", () => {
  const kernel = createDefaultKernel();

  it("gives sources the source-foundation profile and every other view knowledge-upper", () => {
    VIEW_IDS.forEach((view) => {
      const definition = kernel.views.get(view)!;
      expect(definition.spatialProfile, view).toBe(view === "sources" ? "source-foundation" : "knowledge-upper");
      expect(definition.cameraProfile.hemisphere, view).toBe(view === "sources" ? "lower" : "upper");
      expect(definition.cameraProfile.transitionPath, view).toBe(view === "sources" ? "outer_arc" : "direct");
      expect(definition.cameraProfile.allowUserHemisphereCrossing, view).toBe(false);
    });
  });

  it("mirrors the lower polar limits from the upper profile across the horizon", () => {
    const sources = kernel.views.get("sources")!;
    expect(sources.cameraProfile.minPolarAngle).toBeCloseTo(Math.PI - UPPER_MAX_POLAR_ANGLE, 10);
    expect(sources.cameraProfile.maxPolarAngle).toBeCloseTo(Math.PI - UPPER_MIN_POLAR_ANGLE, 10);
    expect(LOWER_MIN_POLAR_ANGLE).toBeGreaterThan(Math.PI / 2);
    expect(LOWER_MAX_POLAR_ANGLE).toBeLessThan(Math.PI);
    const quadrants = kernel.views.get("quadrants")!;
    expect(quadrants.cameraProfile.minPolarAngle).toBe(UPPER_MIN_POLAR_ANGLE);
    expect(quadrants.cameraProfile.maxPolarAngle).toBe(UPPER_MAX_POLAR_ANGLE);
  });

  it("anchors the lower pose on the named band tokens, not repeated literals", () => {
    const sources = kernel.views.get("sources")!;
    expect(sources.cameraProfile.targetLevel).toBe("foundation");
    expect(sources.cameraProfile.defaultPhi).toBeCloseTo(SOURCE_FOUNDATION_CAMERA.phi, 10);
    expect(SOURCE_FOUNDATION_CAMERA.targetY).toBeCloseTo(SOURCE_FOUNDATION_LEVELS.foundation + 0.25, 10);
    // Band order is structural: core above knowledge above provenance above foundation.
    expect(SOURCE_FOUNDATION_LEVELS.core).toBeGreaterThan(SOURCE_FOUNDATION_LEVELS.knowledge);
    expect(SOURCE_FOUNDATION_LEVELS.knowledge).toBeGreaterThan(SOURCE_FOUNDATION_LEVELS.provenance);
    expect(SOURCE_FOUNDATION_LEVELS.provenance).toBeGreaterThan(SOURCE_FOUNDATION_LEVELS.foundation);
  });
});
