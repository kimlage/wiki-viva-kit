import { describe, expect, it } from "vitest";
import type { PerspectiveId } from "../../router";
import { visibleCompatibilityPerspectives } from "./CommandBar";

describe("visibleCompatibilityPerspectives", () => {
  it("adds only the active hidden compatibility view as current context", () => {
    const offered = ["quadrants", "atlas", "focus"] as PerspectiveId[];

    expect(visibleCompatibilityPerspectives("districts", offered)).toEqual([
      "atlas",
      "districts",
      "quadrants"
    ]);
    expect(offered).toEqual(["quadrants", "atlas", "focus"]);
  });

  it("does not duplicate an offered active view or reveal unrelated hidden views", () => {
    const offered = ["quadrants", "atlas"] as PerspectiveId[];

    expect(visibleCompatibilityPerspectives("atlas", offered)).toEqual(["atlas", "quadrants"]);
    expect(visibleCompatibilityPerspectives("sources", offered)).toEqual(["atlas", "quadrants"]);
  });
});
