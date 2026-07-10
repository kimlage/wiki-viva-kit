import { describe, expect, it } from "vitest";
import {
  DEFAULT_MOTION_SPEED,
  MOTION_EASING,
  MOTION_BEZIER,
  MOTION_INTENTS,
  motionCssVariables,
  motionDurationMs,
  motionDurationSeconds,
  overlayResolveDurationMs,
  motionProgress,
  motionStagger,
  type MotionIntent
} from "./motionGrammar";

describe("motion grammar", () => {
  it("gives each semantic intent a distinct, deliberate duration", () => {
    expect(motionDurationMs("feedback", 1)).toBe(160);
    expect(motionDurationMs("overlay", 1)).toBe(320);
    expect(motionDurationMs("surfaceEnter", 1)).toBe(420);
    expect(motionDurationMs("surfaceExit", 1)).toBe(250);
    expect(motionDurationMs("lens", 1)).toBe(540);
    expect(motionDurationMs("view", 1)).toBe(720);
    expect(motionDurationMs("travel", 1)).toBe(980);
    expect(motionDurationMs("retreat", 1)).toBe(760);
  });

  it("uses the calmer default as a speed multiplier, not an amplitude guess", () => {
    expect(DEFAULT_MOTION_SPEED).toBe(0.78);
    expect(motionDurationMs("view")).toBe(923);
    expect(motionDurationMs("view", 0.5)).toBe(1440);
    expect(motionDurationMs("view", 1.4)).toBe(514);
    expect(motionDurationSeconds("travel")).toBe(1.256);
  });

  it("collapses every duration for reduced motion or an explicit off setting", () => {
    for (const intent of MOTION_INTENTS) {
      expect(motionDurationMs(intent, DEFAULT_MOTION_SPEED, true)).toBe(0);
      expect(motionDurationMs(intent, 0)).toBe(0);
      expect(motionDurationSeconds(intent, 0)).toBe(0);
    }
    expect(overlayResolveDurationMs(0)).toBe(0);
    expect(overlayResolveDurationMs(DEFAULT_MOTION_SPEED, true)).toBe(0);
  });

  it("keeps overlay resolution atomic and inside its interaction window", () => {
    expect(overlayResolveDurationMs()).toBe(400);
    expect(overlayResolveDurationMs(1.4)).toBe(300);
    expect(overlayResolveDurationMs(0.2)).toBe(400);
  });

  it("exports a complete easing vocabulary instead of one generic curve", () => {
    expect(Object.keys(MOTION_EASING)).toEqual(MOTION_INTENTS);
    expect(new Set(Object.values(MOTION_EASING)).size).toBeGreaterThan(3);
    expect(MOTION_EASING.surfaceEnter).not.toBe(MOTION_EASING.surfaceExit);
    expect(MOTION_EASING.travel).not.toBe(MOTION_EASING.view);
  });

  it("shares bounded semantic progress curves with the WebGL choreography", () => {
    for (const intent of MOTION_INTENTS) {
      expect(motionProgress(intent, -1)).toBe(0);
      expect(motionProgress(intent, 0)).toBe(0);
      expect(motionProgress(intent, 1)).toBe(1);
      expect(motionProgress(intent, 2)).toBe(1);
      expect(motionProgress(intent, 0.25)).toBeLessThan(motionProgress(intent, 0.75));
    }
    expect(motionProgress("control", 0.5)).toBeGreaterThan(motionProgress("view", 0.5));
    expect(motionProgress("surfaceExit", 0.5)).toBeLessThan(motionProgress("surfaceEnter", 0.5));
    expect(motionProgress("view", 0.5)).toBeCloseTo(0.5, 2);
    expect(motionProgress("travel", 0.5)).toBeCloseTo(0.5, 2);
    expect(MOTION_EASING.view).toBe(`cubic-bezier(${MOTION_BEZIER.view.join(", ")})`);
  });

  it("stagger is stable, bounded and independent from translated context copy", () => {
    expect(motionStagger("page-a")).toBe(motionStagger("page-a"));
    expect(motionStagger("page-a")).not.toBe(motionStagger("page-b"));
    expect(motionStagger("page-a")).toBeGreaterThanOrEqual(0);
    expect(motionStagger("page-a")).toBeLessThanOrEqual(0.1);
    expect(motionStagger("page-a", 99)).toBeLessThanOrEqual(0.14);
  });

  it("builds CSS variables for all durations and curves", () => {
    const variables = motionCssVariables(0.5);
    expect(variables["--motion-speed"]).toBe("0.5");
    expect(variables["--motion-duration-control"]).toBe("440ms");
    expect(variables["--motion-duration-travel"]).toBe("1960ms");
    expect(variables["--motion-easing-surfaceEnter"]).toBe(MOTION_EASING.surfaceEnter);

    for (const intent of MOTION_INTENTS as readonly MotionIntent[]) {
      expect(variables[`--motion-duration-${intent}`]).toMatch(/^\d+ms$/);
      expect(variables[`--motion-easing-${intent}`]).toBe(MOTION_EASING[intent]);
    }
  });

  it("makes the CSS bridge motion-free when reduced or off", () => {
    for (const variables of [motionCssVariables(DEFAULT_MOTION_SPEED, true), motionCssVariables(0)]) {
      expect(variables["--motion-speed"]).toBe("0");
      for (const intent of MOTION_INTENTS) {
        expect(variables[`--motion-duration-${intent}`]).toBe("0ms");
      }
    }
  });
});
