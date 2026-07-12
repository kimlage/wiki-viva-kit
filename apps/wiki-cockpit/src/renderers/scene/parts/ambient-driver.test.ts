import { describe, expect, it } from "vitest";
import * as THREE from "three";
import {
  applyAmbientDriverFrame,
  createAmbientDriverState,
  restoreAmbientDriverState
} from "./ambient-driver";

function targets(
  stale: THREE.SpriteMaterial[] = [],
  highlight: THREE.SpriteMaterial[] = [],
  staleMaterials: THREE.MeshStandardMaterial[] = []
) {
  return { stale, highlight, staleMaterials };
}

describe("ambient semantic baseline ownership", () => {
  it("animates relative to non-uniform layout and material values, then restores them", () => {
    const state = createAmbientDriverState();
    const root = new THREE.Mesh();
    root.scale.set(0.72, 1.08, 1.44);
    const rootBaseline = root.scale.clone();
    const stale = new THREE.SpriteMaterial({ opacity: 0.73, transparent: true });
    const highlight = new THREE.SpriteMaterial({ opacity: 0.31, transparent: true });
    const body = new THREE.MeshStandardMaterial({ emissiveIntensity: 0.47 });

    applyAmbientDriverFrame(state, root, targets([stale], [highlight], [body]), 0.6, 1);

    // Breathing preserves the semantic aspect ratio instead of imposing a
    // fixed scalar of 0.5, and each pulse starts from its real encoded value.
    expect(root.scale.x / rootBaseline.x).toBeCloseTo(root.scale.y / rootBaseline.y, 8);
    expect(root.scale.y / rootBaseline.y).toBeCloseTo(root.scale.z / rootBaseline.z, 8);
    expect(root.scale.x).not.toBeCloseTo(0.5, 2);
    expect(stale.opacity).toBeGreaterThan(0.73);
    expect(highlight.opacity).not.toBeCloseTo(0.5, 4);
    expect(body.emissiveIntensity).toBeGreaterThan(0.47);

    restoreAmbientDriverState(state);
    expect(root.scale.toArray()).toEqual(rootBaseline.toArray());
    expect(stale.opacity).toBeCloseTo(0.73, 8);
    expect(highlight.opacity).toBeCloseTo(0.31, 8);
    expect(body.emissiveIntensity).toBeCloseTo(0.47, 8);
  });

  it("adopts newer semantic writes and never restores over them", () => {
    const state = createAmbientDriverState();
    const root = new THREE.Mesh();
    root.scale.set(0.8, 0.9, 1.1);
    const stale = new THREE.SpriteMaterial({ opacity: 0.42, transparent: true });
    applyAmbientDriverFrame(state, root, targets([stale]), 0.6, 1);

    // Simulate layout and overlay interpolation writing after the ambient
    // frame. The next frame must rebase, not snap back to the original value.
    root.scale.set(1.2, 1.4, 1.6);
    stale.opacity = 0.81;
    applyAmbientDriverFrame(state, root, targets([stale]), 0.9, 1);
    restoreAmbientDriverState(state);

    expect(root.scale.toArray()).toEqual([1.2, 1.4, 1.6]);
    expect(stale.opacity).toBeCloseTo(0.81, 8);
  });

  it("restores and releases targets on membership changes without touching external replacements", () => {
    const state = createAmbientDriverState();
    const departed = new THREE.SpriteMaterial({ opacity: 0.64, transparent: true });
    const externallyUpdated = new THREE.SpriteMaterial({ opacity: 0.28, transparent: true });
    applyAmbientDriverFrame(state, null, targets([departed, externallyUpdated]), 0.6, 1);
    externallyUpdated.opacity = 0.91;

    applyAmbientDriverFrame(state, null, targets(), 0.7, 1);

    expect(departed.opacity).toBeCloseTo(0.64, 8);
    expect(externallyUpdated.opacity).toBeCloseTo(0.91, 8);
    expect(state.stale.size).toBe(0);
  });
});
