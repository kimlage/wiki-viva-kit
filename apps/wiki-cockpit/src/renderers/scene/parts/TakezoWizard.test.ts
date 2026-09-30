import { describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import {
  buildTakezoWizard,
  TAKEZO_MAX_DRAW_CALLS,
  TAKEZO_PALETTE,
  takezoRitualTimeline
} from "./TakezoWizard";
import { buildTakezoPortal, TAKEZO_CHAIN_COLOR, TAKEZO_RENDER_ORDER } from "./TakezoPortal";
import { contextStyle, pageTypeStyle, registerContextPalette, trustColor } from "../../../data/presentation";
import type { TrustColors } from "../../../data/presentation";

describe("buildTakezoWizard — procedural render (plan §15.4, §22.3)", () => {
  it("builds the full costume in a handful of merged-material meshes", () => {
    const build = buildTakezoWizard();
    // Fur (head/ears/tail), robe, hat, ribbons, eyes — one mesh per material.
    expect(build.meshes).toHaveLength(5);
    expect(build.drawCalls).toBe(5);
    for (const mesh of build.meshes) {
      expect(mesh.geometry.getAttribute("position").count).toBeGreaterThan(0);
      expect(mesh.renderOrder).toBe(TAKEZO_RENDER_ORDER);
      expect((mesh.material as THREE.Material).depthWrite).toBe(true);
    }
    build.dispose();
  });

  it("stays inside the ~8 extra draw call ritual budget with the portal included", () => {
    const wizard = buildTakezoWizard();
    const portal = buildTakezoPortal();
    expect(wizard.drawCalls + portal.drawCalls).toBeLessThanOrEqual(TAKEZO_MAX_DRAW_CALLS);
    wizard.dispose();
    portal.dispose();
  });

  it("wears the mandated identity: blue robe, blue hat, red ribbons", () => {
    const build = buildTakezoWizard();
    const colors = build.meshes.map((mesh) =>
      `#${((mesh.material as THREE.MeshStandardMaterial).color ?? new THREE.Color()).getHexString()}`
    );
    expect(colors).toContain(TAKEZO_PALETTE.robe);
    expect(colors).toContain(TAKEZO_PALETTE.hat);
    expect(colors).toContain(TAKEZO_PALETTE.ribbon);
    build.dispose();
  });

  it("is deterministic — two builds produce identical geometry", () => {
    const first = buildTakezoWizard();
    const second = buildTakezoWizard();
    first.meshes.forEach((mesh, index) => {
      const other = second.meshes[index];
      expect(Array.from(mesh.geometry.getAttribute("position").array)).toEqual(
        Array.from(other.geometry.getAttribute("position").array)
      );
    });
    first.dispose();
    second.dispose();
  });

  it("disposes every geometry and material exactly once", () => {
    const build = buildTakezoWizard();
    const geometrySpies = build.meshes.map((mesh) => vi.spyOn(mesh.geometry, "dispose"));
    const materialSpies = build.meshes.map((mesh) => vi.spyOn(mesh.material as THREE.Material, "dispose"));
    build.dispose();
    for (const spy of [...geometrySpies, ...materialSpies]) {
      expect(spy).toHaveBeenCalledTimes(1);
    }
  });
});

describe("takezo colors stay OUTSIDE the data legend (plan §15.4, §22.3)", () => {
  const takezoColors = [...Object.values(TAKEZO_PALETTE), TAKEZO_CHAIN_COLOR].map((hex) => hex.toLowerCase());

  it("collides with no trust color — the ribbons' red is costume, never risk", () => {
    const trustKeys: (keyof TrustColors)[] = ["fresh", "stale", "unknown", "proposal", "root", "risk"];
    const legend = trustKeys.map((key) => trustColor(key).toLowerCase());
    for (const color of takezoColors) {
      expect(legend).not.toContain(color);
    }
    expect(TAKEZO_PALETTE.ribbon.toLowerCase()).not.toBe(trustColor("risk").toLowerCase());
  });

  it("collides with no page-type family accent", () => {
    const familyRepresentatives = [
      "root_index",
      "context_hub",
      "artifact",
      "source",
      "decision",
      "action",
      "operational_rule",
      "ingestion_event",
      "person"
    ];
    const legend = familyRepresentatives.map((type) => pageTypeStyle(type).accent.toLowerCase());
    for (const color of takezoColors) {
      expect(legend).not.toContain(color);
    }
  });

  it("collides with no context identity accent", () => {
    const contexts = Array.from({ length: 12 }, (_, index) => `context-${index}`);
    registerContextPalette(contexts);
    const legend = contexts.map((name) => contextStyle(name).accent.toLowerCase());
    registerContextPalette([]);
    for (const color of takezoColors) {
      expect(legend).not.toContain(color);
    }
  });
});

describe("takezoRitualTimeline — choreography via the motion grammar (plan §15.3)", () => {
  it("orders veil → chain → materialize → plate with grammar durations", () => {
    const timeline = takezoRitualTimeline(false);
    expect(timeline.veilMs).toBeGreaterThan(0);
    expect(timeline.chainMs).toBeGreaterThan(0);
    expect(timeline.wizardMs).toBeGreaterThan(0);
    expect(timeline.chainDelayMs).toBe(timeline.veilMs);
    expect(timeline.wizardDelayMs).toBe(timeline.veilMs + timeline.chainMs);
    expect(timeline.plateDelayMs).toBe(timeline.veilMs + timeline.chainMs + timeline.wizardMs);
  });

  it("collapses completely under reduced motion — static pose, immediate plate focus", () => {
    const timeline = takezoRitualTimeline(true);
    expect(timeline).toEqual({
      veilMs: 0,
      chainDelayMs: 0,
      chainMs: 0,
      wizardDelayMs: 0,
      wizardMs: 0,
      plateDelayMs: 0
    });
  });

  it("collapses when the visual-control motion speed is zero", () => {
    expect(takezoRitualTimeline(false, 0).plateDelayMs).toBe(0);
  });
});
