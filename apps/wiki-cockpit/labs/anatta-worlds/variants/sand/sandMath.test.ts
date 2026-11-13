import { describe, expect, it } from "vitest";
import { Vector3 } from "three";
import {
  SAND_PLANET_RADIUS,
  applySandBrush,
  createSandPlanetGeometry,
  sandPlanetDisplacement
} from "./sandMath";

describe("sand planet heightfield", () => {
  it("is deterministic and finite around the sphere", () => {
    expect(sandPlanetDisplacement(0.62, 0.28, 0.73)).toBe(
      sandPlanetDisplacement(0.62, 0.28, 0.73)
    );
    expect(Number.isFinite(sandPlanetDisplacement(-1, 0, 0))).toBe(true);
    expect(Number.isFinite(sandPlanetDisplacement(0, 1, 0))).toBe(true);
  });

  it("keeps a sculpt gesture localized on the globe", () => {
    const geometry = createSandPlanetGeometry(32, 20);
    const position = geometry.attributes.position;
    const center = new Vector3(1, 0, 0).multiplyScalar(SAND_PLANET_RADIUS);
    let nearest = 0;
    let opposite = 0;
    let nearestDot = -Infinity;
    let oppositeDot = Infinity;
    const vertex = new Vector3();

    for (let index = 0; index < position.count; index += 1) {
      vertex.fromBufferAttribute(position, index).normalize();
      const dot = vertex.dot(center.clone().normalize());
      if (dot > nearestDot) {
        nearest = index;
        nearestDot = dot;
      }
      if (dot < oppositeDot) {
        opposite = index;
        oppositeDot = dot;
      }
    }

    const nearBefore = new Vector3().fromBufferAttribute(position, nearest).length();
    const oppositeBefore = new Vector3().fromBufferAttribute(position, opposite).length();
    expect(applySandBrush(geometry, center, 0.2, 0.3)).toBe(true);
    expect(new Vector3().fromBufferAttribute(position, nearest).length()).toBeGreaterThan(nearBefore);
    expect(new Vector3().fromBufferAttribute(position, opposite).length()).toBeCloseTo(oppositeBefore, 8);
    geometry.dispose();
  });
});
