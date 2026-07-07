// The tutorial's action contract: every step is a REAL system action, and the
// matcher decides when the world advances. If these break, the tutorial either
// stalls (action never matches) or lies (wrong action advances).

import { describe, expect, it } from "vitest";
import {
  GENESIS_FINAL_STAGE,
  genesisAction,
  genesisActionDock,
  genesisAttachMatches,
  genesisCreateMatches,
  genesisQuadrantMatches
} from "./genesis";
import type { BriefSpec } from "../types";

const createSpec = (pageType: string): BriefSpec => ({
  mission_kind: "create",
  grounding: { create: { page_type: pageType } }
});

describe("genesis actions", () => {
  it("every pre-final stage declares an action, and action stages point at a real dock", () => {
    for (let stage = 1; stage < GENESIS_FINAL_STAGE; stage++) {
      const action = genesisAction(stage);
      expect(["create", "attach", "quadrant", "advance"]).toContain(action.kind);
      const dock = genesisActionDock(stage);
      if (action.kind === "create") expect(dock).toEqual({ dock: "create", src: action.pageType });
      if (action.kind === "attach") expect(dock).toEqual({ dock: "blocks" });
      if (action.kind === "quadrant") expect(dock).toBeNull();
      if (action.kind === "advance") expect(dock).toBeNull();
    }
  });

  it("founding the root is the stage-0 action — through the rite, never a dock", () => {
    expect(genesisCreateMatches(0, createSpec("root_entity"))).toBe(true);
    expect(genesisCreateMatches(0, createSpec("person"))).toBe(false);
    // Stage 0 opens NO dock: the founding cards in the void are the action.
    expect(genesisActionDock(0)).toBeNull();
  });

  it("attaching lenses (stage 1) accepts the package or the bare quadrants block", () => {
    expect(genesisAttachMatches(1, "quadrant_lenses")).toBe(true);
    expect(genesisAttachMatches(1, "wiki.block.quadrants.v1")).toBe(true);
    expect(genesisAttachMatches(1, "gamification")).toBe(false);
  });

  it("the quiet→loud beat: gamification attaches at stage 4, not before", () => {
    expect(genesisAttachMatches(4, "gamification")).toBe(true);
    expect(genesisAttachMatches(3, "gamification")).toBe(false);
    expect(genesisCreateMatches(3, createSpec("person"))).toBe(true);
  });

  it("the wrong surface never advances a create stage", () => {
    expect(genesisCreateMatches(2, createSpec("context_hub"))).toBe(true);
    expect(genesisCreateMatches(2, createSpec("source"))).toBe(false);
    expect(genesisAttachMatches(2, "quadrant_lenses")).toBe(false);
  });

  it("flying to the evidence quadrant is the stage-6 action", () => {
    expect(genesisQuadrantMatches(6, "pratica")).toBe(true);
    expect(genesisQuadrantMatches(6, "intencao")).toBe(false);
    expect(genesisCreateMatches(6, createSpec("source"))).toBe(false);
  });
});
