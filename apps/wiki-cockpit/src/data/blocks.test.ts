import { describe, expect, it } from "vitest";
import { anchorDeclaresBlock, anchorDeclaresQuadrants } from "./blocks";
import type { AnchorRecord } from "../types";

function record(origin: string, hasQuadrants = true): AnchorRecord {
  return {
    stack: [{ id: "wiki.block.quadrants.v1", origin, scope: "descendants", kind: "interpretation", config: {}, known: true }],
    interface: {
      views: { available: ["quadrants"], default: "quadrants" },
      missions: { active: false, providers: [], weather_contrib: false, quiet: true },
      create: { catalog: [], arrangement: "by_quadrant", obligations_first: true, obligations: [], disabled_reason: "" },
      intake: { forms: [] },
      score: { loops: [], no_leaderboard: true },
      has_quadrants: hasQuadrants,
      has_relations: false
    },
    identity: { landmark: "", motif: "none", ambient: "none", horizon_label: "title", horizon_text: "", context: "demo" },
    derived: { missions: [], warnings: [] }
  };
}

describe("block stack ownership", () => {
  it("treats page and template block origins as declared by the centered page", () => {
    expect(anchorDeclaresBlock(record("page"), "wiki.block.quadrants.v1")).toBe(true);
    expect(anchorDeclaresBlock(record("template:root_entity"), "wiki.block.quadrants.v1")).toBe(true);
    expect(anchorDeclaresQuadrants(record("page"))).toBe(true);
  });

  it("does not treat inherited anchor blocks as centered-page quadrants", () => {
    expect(anchorDeclaresBlock(record("anchor:company-clearpath-labs"), "wiki.block.quadrants.v1")).toBe(false);
    expect(anchorDeclaresQuadrants(record("anchor:company-clearpath-labs"))).toBe(false);
  });

  it("requires the resolved interface to expose quadrants too", () => {
    expect(anchorDeclaresQuadrants(record("page", false))).toBe(false);
  });
});
