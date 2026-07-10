export type RuntimeDeviceClass = "desktop" | "mobile";
export type RuntimeScenarioClass = "walking_skeleton" | "normal" | "stress";

export type DensityBudget = {
  interactiveNodes: number;
  relationLines: number;
  labels: number;
  particles: number;
  targetFps: number;
  minimumFps: number;
  routeUsabilityMs: number;
  interactionFeedbackMs: number;
};

export type RuntimeRenderCounters = {
  sourceNodes: number;
  interactiveNodes: number;
  relationLines: number;
  labels: number;
  particles: number;
  fallbackReason: string | null;
  frameTimeMedianMs: number | null;
  frameTimeP95Ms: number | null;
  routeUsabilityMs: number | null;
  interactionFeedbackMs: number | null;
};

export type RuntimeBudgetEvaluation = {
  status: "within_budget" | "compact" | "fallback" | "blocked";
  budget: DensityBudget;
  violations: string[];
  degradationReasons: string[];
};

export type FrameSamplePolicy = {
  capacity: number;
  warmupFrames: number;
  minimumSamples: number;
  publishEvery: number;
};

export const FRAME_SAMPLE_POLICY: Readonly<FrameSamplePolicy> = Object.freeze({
  capacity: 120,
  warmupFrames: 12,
  minimumSamples: 30,
  publishEvery: 30
});

// Diagnostics and browser QA can open a new bounded measurement window after
// the renderer, shaders and route transition are warm. The event never changes
// world state; it only discards the previous telemetry window so a sustained
// interaction verdict is not polluted by cold-start/navigation frames.
export const RUNTIME_PERFORMANCE_RESET_EVENT = "wiki-viva:runtime-performance-reset";

export type RuntimeBudgetMatrix = Record<
  RuntimeDeviceClass,
  Record<"normal" | "stress", RuntimeBudgetEvaluation>
>;

export type RuntimePerformanceEvidence = {
  schema_version: "wiki_runtime_performance.v1";
  activeDevice: RuntimeDeviceClass;
  samplePolicy: Readonly<FrameSamplePolicy>;
  sampleCount: number;
  counters: RuntimeRenderCounters;
  evaluations: Partial<RuntimeBudgetMatrix>;
};

const COMMON_DESKTOP = {
  relationLines: 600,
  labels: 80,
  particles: 300,
  targetFps: 60,
  minimumFps: 30,
  routeUsabilityMs: 3_000,
  interactionFeedbackMs: 100
} as const;

const COMMON_MOBILE = {
  relationLines: 220,
  labels: 35,
  particles: 80,
  targetFps: 45,
  minimumFps: 24,
  routeUsabilityMs: 4_000,
  interactionFeedbackMs: 150
} as const;

export const RUNTIME_DENSITY_BUDGETS: Record<RuntimeDeviceClass, Record<RuntimeScenarioClass, DensityBudget>> = {
  desktop: {
    walking_skeleton: { ...COMMON_DESKTOP, interactiveNodes: 250 },
    normal: { ...COMMON_DESKTOP, interactiveNodes: 250 },
    stress: { ...COMMON_DESKTOP, interactiveNodes: 800 }
  },
  mobile: {
    walking_skeleton: { ...COMMON_MOBILE, interactiveNodes: 120 },
    normal: { ...COMMON_MOBILE, interactiveNodes: 120 },
    stress: { ...COMMON_MOBILE, interactiveNodes: 350 }
  }
};

function rounded(value: number): number {
  return Math.round(value * 100) / 100;
}

export function percentile(values: number[], fraction: number): number | null {
  const ordered = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (ordered.length === 0) return null;
  const clamped = Math.min(1, Math.max(0, fraction));
  const index = Math.ceil(clamped * ordered.length) - 1;
  return rounded(ordered[Math.max(0, index)]);
}

export function summarizeFrameTimes(frameTimesMs: number[]): {
  samples: number;
  medianMs: number | null;
  p95Ms: number | null;
  approximateFps: number | null;
} {
  const usable = frameTimesMs.filter((value) => Number.isFinite(value) && value > 0 && value < 1_000);
  const medianMs = percentile(usable, 0.5);
  return {
    samples: usable.length,
    medianMs,
    p95Ms: percentile(usable, 0.95),
    approximateFps: medianMs ? rounded(1_000 / medianMs) : null
  };
}

export function evaluateRuntimeBudget(
  counters: RuntimeRenderCounters,
  device: RuntimeDeviceClass,
  scenario: RuntimeScenarioClass
): RuntimeBudgetEvaluation {
  const budget = RUNTIME_DENSITY_BUDGETS[device][scenario];
  const violations: string[] = [];
  const degradationReasons: string[] = [];
  const countChecks: [keyof RuntimeRenderCounters, number][] = [
    ["interactiveNodes", budget.interactiveNodes],
    ["relationLines", budget.relationLines],
    ["labels", budget.labels],
    ["particles", budget.particles]
  ];
  for (const [key, limit] of countChecks) {
    const value = counters[key];
    if (typeof value === "number" && value > limit) violations.push(`${key}:${value}>${limit}`);
  }
  if (counters.routeUsabilityMs !== null && counters.routeUsabilityMs > budget.routeUsabilityMs) {
    violations.push(`routeUsabilityMs:${rounded(counters.routeUsabilityMs)}>${budget.routeUsabilityMs}`);
  }
  if (counters.interactionFeedbackMs !== null && counters.interactionFeedbackMs > budget.interactionFeedbackMs) {
    violations.push(`interactionFeedbackMs:${rounded(counters.interactionFeedbackMs)}>${budget.interactionFeedbackMs}`);
  }
  const maximumFrameMs = 1_000 / budget.minimumFps;
  if (counters.frameTimeP95Ms !== null && counters.frameTimeP95Ms > maximumFrameMs) {
    violations.push(`frameTimeP95Ms:${rounded(counters.frameTimeP95Ms)}>${rounded(maximumFrameMs)}`);
  }
  if (counters.sourceNodes > budget.interactiveNodes && counters.interactiveNodes <= budget.interactiveNodes) {
    degradationReasons.push(`summarized:${counters.sourceNodes}->${counters.interactiveNodes}`);
  }
  if (counters.fallbackReason) degradationReasons.push(`fallback:${counters.fallbackReason}`);
  const status = counters.fallbackReason
    ? "fallback"
    : violations.length > 0
      ? "blocked"
      : degradationReasons.length > 0
        ? "compact"
        : "within_budget";
  return { status, budget, violations, degradationReasons };
}

export function runtimeDeviceClass(width: number): RuntimeDeviceClass {
  return width < 640 ? "mobile" : "desktop";
}

export function evaluateRuntimeBudgetMatrix(counters: RuntimeRenderCounters): RuntimeBudgetMatrix {
  return {
    desktop: {
      normal: evaluateRuntimeBudget(counters, "desktop", "normal"),
      stress: evaluateRuntimeBudget(counters, "desktop", "stress")
    },
    mobile: {
      normal: evaluateRuntimeBudget(counters, "mobile", "normal"),
      stress: evaluateRuntimeBudget(counters, "mobile", "stress")
    }
  };
}

export function runtimePerformanceEvidence(
  counters: RuntimeRenderCounters,
  width: number,
  sampleCount: number,
  samplePolicy: Readonly<FrameSamplePolicy> = FRAME_SAMPLE_POLICY
): RuntimePerformanceEvidence {
  const activeDevice = runtimeDeviceClass(width);
  return {
    schema_version: "wiki_runtime_performance.v1",
    activeDevice,
    samplePolicy,
    sampleCount,
    counters: { ...counters },
    // Device profiles change the renderer itself (LOD, particles, labels), so
    // only evaluate the counters against the device that produced them. The
    // Playwright desktop/mobile projects together prove the full matrix.
    evaluations: {
      [activeDevice]: {
        normal: evaluateRuntimeBudget(counters, activeDevice, "normal"),
        stress: evaluateRuntimeBudget(counters, activeDevice, "stress")
      }
    }
  };
}

// A bounded, allocation-light sampler for the render loop. record() never
// reaches React state. It returns true only at evidence publication milestones;
// callers may then serialize one snapshot directly into a DOM output element.
export class BoundedFrameTimeSampler {
  readonly #capacity: number;
  readonly #minimumSamples: number;
  readonly #publishEvery: number;
  #warmupRemaining: number;
  readonly #warmupFrames: number;
  readonly #samples: number[] = [];

  constructor(policy: Partial<FrameSamplePolicy> = {}) {
    this.#capacity = Math.max(1, Math.floor(policy.capacity ?? FRAME_SAMPLE_POLICY.capacity));
    this.#warmupFrames = Math.max(0, Math.floor(policy.warmupFrames ?? FRAME_SAMPLE_POLICY.warmupFrames));
    this.#warmupRemaining = this.#warmupFrames;
    this.#minimumSamples = Math.min(
      this.#capacity,
      Math.max(1, Math.floor(policy.minimumSamples ?? FRAME_SAMPLE_POLICY.minimumSamples))
    );
    this.#publishEvery = Math.max(1, Math.floor(policy.publishEvery ?? FRAME_SAMPLE_POLICY.publishEvery));
  }

  record(frameTimeMs: number): boolean {
    if (!Number.isFinite(frameTimeMs) || frameTimeMs <= 0 || frameTimeMs >= 1_000) return false;
    if (this.#warmupRemaining > 0) {
      this.#warmupRemaining -= 1;
      return false;
    }
    if (this.#samples.length >= this.#capacity) return false;
    this.#samples.push(frameTimeMs);
    const count = this.#samples.length;
    return count >= this.#minimumSamples && (count % this.#publishEvery === 0 || count === this.#capacity);
  }

  summary(): ReturnType<typeof summarizeFrameTimes> {
    return summarizeFrameTimes(this.#samples);
  }

  get sampleCount(): number {
    return this.#samples.length;
  }

  get complete(): boolean {
    return this.#samples.length >= this.#capacity;
  }

  get policy(): Readonly<FrameSamplePolicy> {
    return {
      capacity: this.#capacity,
      warmupFrames: this.#warmupFrames,
      minimumSamples: this.#minimumSamples,
      publishEvery: this.#publishEvery
    };
  }

  reset(): void {
    this.#samples.length = 0;
    this.#warmupRemaining = this.#warmupFrames;
  }
}

const EMPTY_COUNTERS: RuntimeRenderCounters = {
  sourceNodes: 0,
  interactiveNodes: 0,
  relationLines: 0,
  labels: 0,
  particles: 0,
  fallbackReason: null,
  frameTimeMedianMs: null,
  frameTimeP95Ms: null,
  routeUsabilityMs: null,
  interactionFeedbackMs: null
};

export class RuntimePerformanceTelemetry {
  readonly #frames: BoundedFrameTimeSampler;
  #counters: RuntimeRenderCounters = { ...EMPTY_COUNTERS };

  constructor(policy: Partial<FrameSamplePolicy> = {}) {
    this.#frames = new BoundedFrameTimeSampler(policy);
  }

  updateCounters(patch: Partial<RuntimeRenderCounters>, width: number): RuntimePerformanceEvidence {
    this.#counters = { ...this.#counters, ...patch };
    return runtimePerformanceEvidence(this.#counters, width, this.#frames.sampleCount, this.#frames.policy);
  }

  recordFrame(frameTimeMs: number, width: number): RuntimePerformanceEvidence | null {
    if (!this.#frames.record(frameTimeMs)) return null;
    const summary = this.#frames.summary();
    this.#counters = {
      ...this.#counters,
      frameTimeMedianMs: summary.medianMs,
      frameTimeP95Ms: summary.p95Ms
    };
    return runtimePerformanceEvidence(this.#counters, width, this.#frames.sampleCount, this.#frames.policy);
  }

  snapshot(width: number): RuntimePerformanceEvidence {
    return runtimePerformanceEvidence(this.#counters, width, this.#frames.sampleCount, this.#frames.policy);
  }

  resetFrames(): void {
    this.#frames.reset();
    this.#counters = { ...this.#counters, frameTimeMedianMs: null, frameTimeP95Ms: null };
  }
}
