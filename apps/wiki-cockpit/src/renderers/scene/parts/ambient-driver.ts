import * as THREE from "three";

export type AmbientPulseTargets = {
  stale: THREE.SpriteMaterial[];
  highlight: THREE.SpriteMaterial[];
  staleMaterials: THREE.MeshStandardMaterial[];
};

type ScalarRecord = {
  base: number;
  lastApplied: number;
};

type ScaleRecord = {
  target: THREE.Mesh;
  base: THREE.Vector3;
  lastApplied: THREE.Vector3;
};

export type AmbientDriverState = {
  root: ScaleRecord | null;
  stale: Map<THREE.SpriteMaterial, ScalarRecord>;
  highlight: Map<THREE.SpriteMaterial, ScalarRecord>;
  staleMaterials: Map<THREE.MeshStandardMaterial, ScalarRecord>;
};

const EPSILON = 1e-7;

function sameScalar(left: number, right: number): boolean {
  return Math.abs(left - right) <= EPSILON;
}

function sameScale(left: THREE.Vector3, right: THREE.Vector3): boolean {
  return (
    sameScalar(left.x, right.x) &&
    sameScalar(left.y, right.y) &&
    sameScalar(left.z, right.z)
  );
}

export function createAmbientDriverState(): AmbientDriverState {
  return {
    root: null,
    stale: new Map(),
    highlight: new Map(),
    staleMaterials: new Map()
  };
}

function restoreScale(record: ScaleRecord): void {
  // A semantic layout update may have written a new scale after our last
  // frame. In that case the newer value owns the mesh and must not be undone.
  if (sameScale(record.target.scale, record.lastApplied)) {
    record.target.scale.copy(record.base);
  }
}

function reconcileRoot(
  state: AmbientDriverState,
  target: THREE.Mesh | null,
  factor: number
): void {
  if (state.root?.target !== target) {
    if (state.root) restoreScale(state.root);
    state.root = target
      ? {
          target,
          base: target.scale.clone(),
          lastApplied: target.scale.clone()
        }
      : null;
  }
  const record = state.root;
  if (!record) return;

  // React Three Fiber or a semantic transition can update the same object
  // without replacing it. Adopt that external value as the new baseline.
  if (!sameScale(record.target.scale, record.lastApplied)) {
    record.base.copy(record.target.scale);
  }
  record.target.scale.copy(record.base).multiplyScalar(factor);
  record.lastApplied.copy(record.target.scale);
}

function restoreScalar<T extends object>(
  target: T,
  record: ScalarRecord,
  read: (value: T) => number,
  write: (value: T, next: number) => void
): void {
  if (sameScalar(read(target), record.lastApplied)) write(target, record.base);
}

function reconcileScalars<T extends object>(
  records: Map<T, ScalarRecord>,
  targets: readonly T[],
  factor: number,
  read: (value: T) => number,
  write: (value: T, next: number) => void,
  clamp: (value: number) => number
): void {
  const active = new Set(targets);
  for (const [target, record] of records) {
    if (active.has(target)) continue;
    restoreScalar(target, record, read, write);
    records.delete(target);
  }

  for (const target of active) {
    let record = records.get(target);
    if (!record) {
      const current = read(target);
      record = { base: current, lastApplied: current };
      records.set(target, record);
    } else if (!sameScalar(read(target), record.lastApplied)) {
      // Overlay interpolation runs independently of ambient motion. If it
      // writes a new value, that semantic value becomes the next baseline.
      record.base = read(target);
    }
    const next = clamp(record.base * factor);
    write(target, next);
    record.lastApplied = next;
  }
}

const readOpacity = (material: THREE.SpriteMaterial) => material.opacity;
const writeOpacity = (material: THREE.SpriteMaterial, opacity: number) => {
  material.opacity = opacity;
};
const readEmissive = (material: THREE.MeshStandardMaterial) => material.emissiveIntensity;
const writeEmissive = (material: THREE.MeshStandardMaterial, intensity: number) => {
  material.emissiveIntensity = intensity;
};
const clampOpacity = (value: number) => THREE.MathUtils.clamp(value, 0, 1);
const clampIntensity = (value: number) => Math.max(0, value);

/**
 * Apply one bounded ambient frame relative to the semantic values currently
 * owned by layout and visual encoding. The state contains only live targets;
 * targets that leave the scene are restored and removed on the same frame.
 */
export function applyAmbientDriverFrame(
  state: AmbientDriverState,
  root: THREE.Mesh | null,
  pulses: AmbientPulseTargets,
  elapsed: number,
  glow: number
): void {
  const rootFactor = 1 + Math.sin(elapsed * Math.PI * 0.5) * (0.02 + 0.015 * glow);
  reconcileRoot(state, root, rootFactor);

  const staleWave = Math.sin((elapsed * Math.PI * 2) / 2.4);
  const highlightWave = Math.sin((elapsed * Math.PI * 2) / 1.5);
  // These relative amplitudes preserve the old visual strength when the
  // semantic baseline is 0.5/0.9, while no longer replacing other baselines.
  const staleFactor = 1 + 0.24 * glow * staleWave;
  const staleEmissiveFactor = 1 + (0.35 / 0.9) * glow * staleWave;
  const highlightFactor = 1 + 0.36 * glow * highlightWave;

  reconcileScalars(state.stale, pulses.stale, staleFactor, readOpacity, writeOpacity, clampOpacity);
  reconcileScalars(
    state.staleMaterials,
    pulses.staleMaterials,
    staleEmissiveFactor,
    readEmissive,
    writeEmissive,
    clampIntensity
  );
  reconcileScalars(
    state.highlight,
    pulses.highlight,
    highlightFactor,
    readOpacity,
    writeOpacity,
    clampOpacity
  );
}

/** Restore every value still owned by ambient motion and release references. */
export function restoreAmbientDriverState(state: AmbientDriverState): void {
  if (state.root) restoreScale(state.root);
  state.root = null;
  for (const [target, record] of state.stale) {
    restoreScalar(target, record, readOpacity, writeOpacity);
  }
  for (const [target, record] of state.highlight) {
    restoreScalar(target, record, readOpacity, writeOpacity);
  }
  for (const [target, record] of state.staleMaterials) {
    restoreScalar(target, record, readEmissive, writeEmissive);
  }
  state.stale.clear();
  state.highlight.clear();
  state.staleMaterials.clear();
}
