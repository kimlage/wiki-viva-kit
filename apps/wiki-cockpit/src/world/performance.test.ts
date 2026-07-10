import { describe, expect, it } from "vitest";
import {
  evaluateRuntimeBudget,
  evaluateRuntimeBudgetMatrix,
  BoundedFrameTimeSampler,
  FRAME_SAMPLE_POLICY,
  percentile,
  RUNTIME_DENSITY_BUDGETS,
  runtimeDeviceClass,
  runtimeFrameMeasurementAllowed,
  RuntimePerformanceTelemetry,
  runtimePerformanceEvidence,
  sustainedPerformanceFallbackRequired,
  summarizeFrameTimes,
  type RuntimeRenderCounters
} from "./performance";

const counters = (patch: Partial<RuntimeRenderCounters> = {}): RuntimeRenderCounters => ({
  sourceNodes: 100,
  interactiveNodes: 100,
  relationLines: 200,
  labels: 30,
  particles: 60,
  fallbackReason: null,
  frameTimeMedianMs: 16.67,
  frameTimeP95Ms: 20,
  routeUsabilityMs: 900,
  interactionFeedbackMs: 40,
  ...patch
});

describe("v8 runtime performance contract", () => {
  it("encodes the plan's desktop/mobile normal and stress limits", () => {
    expect(RUNTIME_DENSITY_BUDGETS.desktop.normal.interactiveNodes).toBe(250);
    expect(RUNTIME_DENSITY_BUDGETS.desktop.stress.interactiveNodes).toBe(800);
    expect(RUNTIME_DENSITY_BUDGETS.mobile.normal.interactiveNodes).toBe(120);
    expect(RUNTIME_DENSITY_BUDGETS.mobile.stress.interactiveNodes).toBe(350);
    expect(RUNTIME_DENSITY_BUDGETS.mobile.normal.particles).toBe(80);
  });

  it("reports compact rendering separately from a budget violation", () => {
    expect(evaluateRuntimeBudget(counters({ sourceNodes: 700, interactiveNodes: 160 }), "desktop", "normal")).toMatchObject({
      status: "compact",
      violations: [],
      degradationReasons: ["summarized:700->160"]
    });
  });

  it("blocks unexplained count, latency and sustained-frame regressions", () => {
    const result = evaluateRuntimeBudget(
      counters({ relationLines: 601, routeUsabilityMs: 3_001, interactionFeedbackMs: 101, frameTimeP95Ms: 34 }),
      "desktop",
      "normal"
    );
    expect(result.status).toBe("blocked");
    expect(result.violations).toEqual(expect.arrayContaining([
      "relationLines:601>600",
      "routeUsabilityMs:3001>3000",
      "interactionFeedbackMs:101>100",
      "frameTimeP95Ms:34>33.33"
    ]));
  });

  it("names an explicit fallback without pretending it is a rich-mode pass", () => {
    expect(evaluateRuntimeBudget(counters({ fallbackReason: "reduced_motion" }), "mobile", "normal")).toMatchObject({
      status: "fallback",
      degradationReasons: ["fallback:reduced_motion"]
    });
  });

  it("summarizes bounded samples deterministically with median and p95", () => {
    expect(percentile([30, 10, 20, 40], 0.5)).toBe(20);
    expect(percentile([30, 10, 20, 40], 0.95)).toBe(40);
    expect(summarizeFrameTimes([16, 17, 15, 18, Number.NaN])).toEqual({
      samples: 4,
      medianMs: 16,
      p95Ms: 18,
      approximateFps: 62.5
    });
    expect(runtimeDeviceClass(390)).toBe("mobile");
    expect(runtimeDeviceClass(1280)).toBe("desktop");
  });

  it("evaluates normal and stress budgets for both device classes", () => {
    const matrix = evaluateRuntimeBudgetMatrix(counters());
    expect(matrix.desktop.normal.status).toBe("within_budget");
    expect(matrix.desktop.stress.status).toBe("within_budget");
    expect(matrix.mobile.normal.status).toBe("within_budget");
    expect(matrix.mobile.stress.status).toBe("within_budget");
    const mobileEvidence = runtimePerformanceEvidence(counters(), 390, 30);
    expect(mobileEvidence).toMatchObject({
      schema_version: "wiki_runtime_performance.v1",
      activeDevice: "mobile",
      sampleCount: 30
    });
    expect(mobileEvidence.evaluations.mobile?.normal.status).toBe("within_budget");
    expect(mobileEvidence.evaluations.desktop).toBeUndefined();
  });

  it("requests 2D fallback only after a full window proves a frame-time-only block", () => {
    const slow = counters({ frameTimeMedianMs: 80, frameTimeP95Ms: 171 });
    const complete = runtimePerformanceEvidence(slow, 390, FRAME_SAMPLE_POLICY.capacity);
    expect(sustainedPerformanceFallbackRequired(complete)).toBe(true);

    const transientSpikes = runtimePerformanceEvidence(
      counters({ frameTimeMedianMs: 16, frameTimeP95Ms: 171 }),
      390,
      FRAME_SAMPLE_POLICY.capacity
    );
    expect(sustainedPerformanceFallbackRequired(transientSpikes)).toBe(false);

    expect(
      sustainedPerformanceFallbackRequired(
        runtimePerformanceEvidence(slow, 390, FRAME_SAMPLE_POLICY.capacity - 1)
      )
    ).toBe(false);
    expect(
      sustainedPerformanceFallbackRequired(
        runtimePerformanceEvidence(
          counters({ frameTimeP95Ms: 171, relationLines: 221 }),
          390,
          FRAME_SAMPLE_POLICY.capacity
        )
      )
    ).toBe(false);
    expect(
      sustainedPerformanceFallbackRequired(
        runtimePerformanceEvidence(
          counters({ frameTimeP95Ms: 171, fallbackReason: "webgl_unavailable" }),
          390,
          FRAME_SAMPLE_POLICY.capacity
        )
      )
    ).toBe(false);
  });

  it("bounds render-loop samples, skips warmup and publishes only at fixed milestones", () => {
    const sampler = new BoundedFrameTimeSampler({ capacity: 4, warmupFrames: 2, minimumSamples: 2, publishEvery: 2 });
    expect(sampler.record(99)).toBe(false);
    expect(sampler.record(88)).toBe(false);
    expect(sampler.record(10)).toBe(false);
    expect(sampler.record(20)).toBe(true);
    expect(sampler.record(30)).toBe(false);
    expect(sampler.record(40)).toBe(true);
    expect(sampler.record(50)).toBe(false);
    expect(sampler.sampleCount).toBe(4);
    expect(sampler.summary()).toMatchObject({ samples: 4, medianMs: 20, p95Ms: 40 });
    sampler.reset();
    expect(sampler.sampleCount).toBe(0);
  });

  it("does not publish telemetry on every frame", () => {
    const telemetry = new RuntimePerformanceTelemetry({ warmupFrames: 0 });
    telemetry.updateCounters(counters({ frameTimeMedianMs: null, frameTimeP95Ms: null }), 1280);
    const publications: NonNullable<ReturnType<RuntimePerformanceTelemetry["recordFrame"]>>[] = [];
    for (let index = 0; index < 90; index += 1) {
      const evidence = telemetry.recordFrame(16 + (index % 3), 1280, "visible");
      if (evidence) publications.push(evidence);
    }
    expect(publications.map((evidence) => ({
      sampleCount: evidence.sampleCount,
      medianMs: evidence.counters.frameTimeMedianMs,
      p95Ms: evidence.counters.frameTimeP95Ms
    }))).toEqual([
      { sampleCount: 30, medianMs: 17, p95Ms: 18 },
      { sampleCount: 60, medianMs: 17, p95Ms: 18 },
      { sampleCount: 90, medianMs: 17, p95Ms: 18 }
    ]);
    expect(telemetry.snapshot(1280).counters.frameTimeP95Ms).toBe(18);
    expect(telemetry.snapshot(1280).samplePolicy.capacity).toBe(FRAME_SAMPLE_POLICY.capacity);
    expect(telemetry.snapshot(1280).sampleCount).toBe(90);
  });

  it("never counts visibility-throttled frames as renderer evidence", () => {
    const telemetry = new RuntimePerformanceTelemetry({ warmupFrames: 0 });
    telemetry.updateCounters(counters({ frameTimeMedianMs: null, frameTimeP95Ms: null }), 1280);

    expect(runtimeFrameMeasurementAllowed("visible")).toBe(true);
    expect(runtimeFrameMeasurementAllowed("hidden")).toBe(false);
    for (let index = 0; index < FRAME_SAMPLE_POLICY.capacity; index += 1) {
      expect(telemetry.recordFrame(171, 1280, "hidden")).toBeNull();
    }
    expect(telemetry.snapshot(1280).sampleCount).toBe(0);

    for (let index = 0; index < FRAME_SAMPLE_POLICY.minimumSamples; index += 1) {
      telemetry.recordFrame(16, 1280, "visible");
    }
    expect(telemetry.snapshot(1280).sampleCount).toBe(FRAME_SAMPLE_POLICY.minimumSamples);
  });
});
