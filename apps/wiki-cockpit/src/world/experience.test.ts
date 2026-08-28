import { describe, expect, it } from "vitest";
import {
  QUADRANT_LENS_IDS,
  WORLD_EXPERIENCE_AXES,
  WORLD_EXPERIENCE_KEYS,
  WORLD_OVERLAY_EXPERIENCES,
  WORLD_QUADRANT_LENS_EXPERIENCES,
  WORLD_VIEW_EXPERIENCES,
  activeQuadrantLensOption,
  isNativeWorldViewId,
  isQuadrantLensId,
  isWorldOverlayId,
  registeredWorldOverlayExperiences,
  registeredWorldViewExperiences
} from "./experience";
import { RegistryKernel } from "./registries/RegistryKernel";

describe("world experience metadata", () => {
  it("defines one coherent, unique set of five views, six overlays and five quadrant choices", () => {
    expect(WORLD_VIEW_EXPERIENCES.map((entry) => entry.id)).toEqual(["quadrants", "radar", "sources", "work", "timeline"]);
    expect(WORLD_OVERLAY_EXPERIENCES.map((entry) => entry.id)).toEqual([
      "attention",
      "freshness",
      "actions",
      "ownership",
      "evidence",
      "quality"
    ]);
    expect(WORLD_QUADRANT_LENS_EXPERIENCES.map((entry) => entry.id)).toEqual([
      "all",
      "q1_intencao",
      "q2_pratica",
      "q3_relacoes",
      "q4_sistemas"
    ]);
    expect(new Set(WORLD_VIEW_EXPERIENCES.map((entry) => entry.id)).size).toBe(5);
    expect(new Set(WORLD_OVERLAY_EXPERIENCES.map((entry) => entry.id)).size).toBe(6);
  });

  it("keeps every piece of user-facing copy in named translation slots", () => {
    const optionKeys = [
      ...WORLD_EXPERIENCE_AXES.flatMap((entry) => [entry.labelKey, entry.descriptionKey]),
      ...WORLD_VIEW_EXPERIENCES.flatMap((entry) => [entry.labelKey, entry.questionKey, entry.descriptionKey]),
      ...WORLD_OVERLAY_EXPERIENCES.flatMap((entry) => [entry.labelKey, entry.questionKey, entry.descriptionKey]),
      ...WORLD_QUADRANT_LENS_EXPERIENCES.flatMap((entry) => [entry.labelKey, entry.descriptionKey]),
      ...Object.values(WORLD_EXPERIENCE_KEYS)
    ];

    expect(optionKeys.every((key) => key.startsWith("world."))).toBe(true);
    expect(optionKeys.every((key) => !/\s/.test(key))).toBe(true);
    expect(new Set(WORLD_VIEW_EXPERIENCES.flatMap((entry) => [entry.questionKey, entry.descriptionKey])).size).toBe(10);
    expect(new Set(WORLD_OVERLAY_EXPERIENCES.flatMap((entry) => [entry.questionKey, entry.descriptionKey])).size).toBe(12);
  });

  it("treats non-quadrant runtime lenses as the unscoped All choice", () => {
    expect(activeQuadrantLensOption(null)).toBe("all");
    expect(activeQuadrantLensOption("type")).toBe("all");
    expect(activeQuadrantLensOption("source_state")).toBe("all");
    expect(activeQuadrantLensOption("q3_relacoes")).toBe("q3_relacoes");
    expect(QUADRANT_LENS_IDS.every((lens) => isQuadrantLensId(lens))).toBe(true);
  });

  it("guards native view, overlay and quadrant values at integration boundaries", () => {
    expect(isNativeWorldViewId("radar")).toBe(true);
    expect(isNativeWorldViewId("timeline")).toBe(true);
    expect(isNativeWorldViewId("atlas")).toBe(false);
    expect(isWorldOverlayId("evidence")).toBe(true);
    expect(isWorldOverlayId("trust")).toBe(false);
    expect(isQuadrantLensId("q4_sistemas")).toBe(true);
    expect(isQuadrantLensId("relations")).toBe(false);
  });

  it("derives navigator availability from the installed runtime registries", () => {
    const kernel = new RegistryKernel();
    kernel.overlays.register({
      id: "evidence",
      metric: "evidence_state",
      fallbackText: "Evidence"
    });
    kernel.views.register({
      id: "sources",
      defaultLens: "all",
      defaultOverlay: "evidence",
      allowedOverlays: ["evidence"]
    });

    expect(registeredWorldViewExperiences(kernel).map((entry) => entry.id)).toEqual([
      "sources"
    ]);
    expect(
      registeredWorldOverlayExperiences(kernel).map((entry) => entry.id)
    ).toEqual(["evidence"]);
  });
});
