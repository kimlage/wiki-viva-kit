export const MOTION_INTENTS = [
  "feedback",
  "control",
  "overlay",
  "surfaceEnter",
  "surfaceExit",
  "lens",
  "view",
  "travel",
  "retreat"
] as const;

export type MotionIntent = (typeof MOTION_INTENTS)[number];

/**
 * Visual-control motion is a speed multiplier: values below one create a more
 * deliberate rhythm. Zero is an explicit request for no motion.
 */
export const DEFAULT_MOTION_SPEED = 0.78;

const MIN_ACTIVE_MOTION_SPEED = 0.2;
const MAX_MOTION_SPEED = 1.4;

const BASE_DURATION_MS: Readonly<Record<MotionIntent, number>> = {
  feedback: 160,
  control: 220,
  overlay: 320,
  surfaceEnter: 420,
  surfaceExit: 250,
  lens: 540,
  view: 720,
  travel: 980,
  retreat: 760
};

type CubicBezier = readonly [x1: number, y1: number, x2: number, y2: number];

/**
 * The control points are the source of truth for both CSS and WebGL. Spatial
 * moves are intentionally symmetric around their midpoint: the world remains
 * legible while it travels instead of visually finishing in the first half.
 */
export const MOTION_BEZIER: Readonly<Record<MotionIntent, CubicBezier>> = {
  feedback: [0.2, 0, 0, 1],
  control: [0.2, 0, 0, 1],
  overlay: [0.32, 0, 0.22, 1],
  surfaceEnter: [0.22, 0.65, 0.3, 1],
  surfaceExit: [0.4, 0, 1, 1],
  lens: [0.42, 0, 0.3, 1],
  view: [0.45, 0, 0.55, 1],
  travel: [0.5, 0, 0.5, 1],
  retreat: [0.4, 0, 0.6, 1]
};

/** Easing is semantic too: exits yield quickly while spatial moves settle. */
export const MOTION_EASING: Readonly<Record<MotionIntent, string>> = Object.fromEntries(
  MOTION_INTENTS.map((intent) => [intent, `cubic-bezier(${MOTION_BEZIER[intent].join(", ")})`])
) as Record<MotionIntent, string>;

function activeMotionSpeed(speed: number): number {
  if (!Number.isFinite(speed) || speed <= 0) return 0;
  return Math.min(MAX_MOTION_SPEED, Math.max(MIN_ACTIVE_MOTION_SPEED, speed));
}

export function motionDurationMs(
  intent: MotionIntent,
  speed = DEFAULT_MOTION_SPEED,
  reduced = false
): number {
  if (reduced) return 0;
  const normalizedSpeed = activeMotionSpeed(speed);
  if (normalizedSpeed === 0) return 0;
  return Math.round(BASE_DURATION_MS[intent] / normalizedSpeed);
}

export function motionDurationSeconds(
  intent: MotionIntent,
  speed = DEFAULT_MOTION_SPEED,
  reduced = false
): number {
  return motionDurationMs(intent, speed, reduced) / 1000;
}

/** Overlay encoding is an atomic, short resolve even at very slow presets. */
export function overlayResolveDurationMs(
  speed = DEFAULT_MOTION_SPEED,
  reduced = false
): number {
  const duration = motionDurationMs("overlay", speed, reduced);
  return duration === 0 ? 0 : Math.min(400, Math.max(300, duration));
}

function cubicCoordinate(t: number, first: number, second: number): number {
  const inverse = 1 - t;
  return 3 * inverse * inverse * t * first + 3 * inverse * t * t * second + t * t * t;
}

function cubicBezierProgress(progress: number, bezier: CubicBezier): number {
  if (progress <= 0) return 0;
  if (progress >= 1) return 1;
  const [x1, y1, x2, y2] = bezier;
  // CSS timing functions map time through the x axis first. A short binary
  // solve is stable for every valid cubic-bezier and cheap at our scene size.
  let low = 0;
  let high = 1;
  let parameter = progress;
  for (let index = 0; index < 10; index += 1) {
    const x = cubicCoordinate(parameter, x1, x2);
    if (x < progress) low = parameter;
    else high = parameter;
    parameter = (low + high) / 2;
  }
  return cubicCoordinate(parameter, y1, y2);
}

/**
 * Shared progress curve for CSS and WebGL. Both layers consume the exact same
 * cubic-bezier rather than merely sharing a duration and drifting mid-flight.
 */
export function motionProgress(intent: MotionIntent, progress: number): number {
  const t = Math.min(1, Math.max(0, progress));
  return cubicBezierProgress(t, MOTION_BEZIER[intent]);
}

/** Stable, tightly bounded staggering prevents a whole dense world from
 * moving in lockstep without making timing depend on translated copy. */
export function motionStagger(key: string, maximum = 0.1): number {
  let hash = 2166136261;
  for (let index = 0; index < key.length; index += 1) {
    hash ^= key.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  const boundedMaximum = Math.min(0.14, Math.max(0, maximum));
  return ((hash >>> 0) / 4294967295) * boundedMaximum;
}

export type MotionCssVariables = Record<
  | "--motion-speed"
  | `--motion-duration-${MotionIntent}`
  | `--motion-easing-${MotionIntent}`,
  string
>;

/**
 * One bridge for component styles: durations collapse to zero for both the
 * OS reduced-motion preference and the explicit zero-speed setting.
 */
export function motionCssVariables(
  speed = DEFAULT_MOTION_SPEED,
  reduced = false
): MotionCssVariables {
  const effectiveSpeed = reduced ? 0 : activeMotionSpeed(speed);
  const variables = {
    "--motion-speed": String(effectiveSpeed)
  } as MotionCssVariables;

  for (const intent of MOTION_INTENTS) {
    variables[`--motion-duration-${intent}`] = `${motionDurationMs(intent, speed, reduced)}ms`;
    variables[`--motion-easing-${intent}`] = MOTION_EASING[intent];
  }

  return variables;
}
