import { describe, expect, it, vi } from "vitest";
import {
  buildTakezoPortal,
  portalLinksRevealed,
  TAKEZO_PORTAL_LINK_COUNT,
  TAKEZO_PORTAL_RADIUS,
  TAKEZO_RENDER_ORDER,
  takezoPortalLinkTransforms
} from "./TakezoPortal";

describe("takezoPortalLinkTransforms (plan §15.4)", () => {
  it("is deterministic — the arc never depends on time or randomness", () => {
    expect(takezoPortalLinkTransforms()).toEqual(takezoPortalLinkTransforms());
  });

  it("places every link on an arch above the ground plane", () => {
    const transforms = takezoPortalLinkTransforms();
    expect(transforms).toHaveLength(TAKEZO_PORTAL_LINK_COUNT);
    for (const transform of transforms) {
      expect(transform.position[1]).toBeGreaterThanOrEqual(0);
      const radius = Math.hypot(transform.position[0], transform.position[1] - 0.04);
      expect(radius).toBeCloseTo(TAKEZO_PORTAL_RADIUS, 5);
    }
  });

  it("spans the arch symmetrically from one side to the other", () => {
    const transforms = takezoPortalLinkTransforms();
    const first = transforms[0].position;
    const last = transforms[transforms.length - 1].position;
    expect(first[0]).toBeCloseTo(-last[0], 5);
    expect(first[1]).toBeCloseTo(last[1], 5);
  });
});

describe("portalLinksRevealed — the chain draw is bounded and monotonic", () => {
  it("reveals nothing before the phase and the whole chain at the end", () => {
    expect(portalLinksRevealed(0)).toBe(0);
    expect(portalLinksRevealed(-1)).toBe(0);
    expect(portalLinksRevealed(1)).toBe(TAKEZO_PORTAL_LINK_COUNT);
    expect(portalLinksRevealed(2)).toBe(TAKEZO_PORTAL_LINK_COUNT);
  });

  it("never removes links as progress advances", () => {
    let previous = 0;
    for (let step = 0; step <= 20; step += 1) {
      const revealed = portalLinksRevealed(step / 20);
      expect(revealed).toBeGreaterThanOrEqual(previous);
      expect(revealed).toBeLessThanOrEqual(TAKEZO_PORTAL_LINK_COUNT);
      previous = revealed;
    }
  });
});

describe("buildTakezoPortal — one instanced draw call, disposed cleanly (plan §22.3)", () => {
  it("keeps the whole chain in a single instanced mesh", () => {
    const build = buildTakezoPortal();
    expect(build.drawCalls).toBe(1);
    expect(build.mesh.count).toBe(TAKEZO_PORTAL_LINK_COUNT);
    expect(build.mesh.renderOrder).toBe(TAKEZO_RENDER_ORDER);
    expect(build.mesh.material).toMatchObject({ depthWrite: true });
    build.dispose();
  });

  it("disposes geometry and material on teardown", () => {
    const build = buildTakezoPortal();
    const geometrySpy = vi.spyOn(build.mesh.geometry, "dispose");
    const materialSpy = vi.spyOn(build.mesh.material as { dispose: () => void }, "dispose");
    build.dispose();
    expect(geometrySpy).toHaveBeenCalledTimes(1);
    expect(materialSpy).toHaveBeenCalledTimes(1);
  });
});
