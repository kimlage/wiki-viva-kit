// Genesis stage ACTIONS — the tutorial never uses mock modals: every step is
// performed through the system's REAL surfaces (the FOUNDING RITE births the
// root, the spatial SeedFlow seeds pages, BlocksDock attaches lenses). In
// genesis the expected action advances the stage (the staged snapshot IS the
// simulated result); in a real wiki the same surfaces compose briefs → PR.
// One affordance, two write paths — never a disconnected mock.

import type { BriefSpec } from "../types";
import type { SceneFacet } from "../scene/facets";

export const GENESIS_FINAL_STAGE = 8;

// Genesis navigation URLs. Raw-string navigation would silently drop the
// visual=1 harness flag (router contract: it "must survive every redirect"),
// so every stage hop and every door out builds through here.
export function genesisUrl(stage: number, opts: { visual?: boolean } = {}): string {
  const params = new URLSearchParams();
  if (stage > 0) params.set("stage", String(Math.min(stage, GENESIS_FINAL_STAGE)));
  if (opts.visual) params.set("visual", "1");
  const qs = params.toString();
  return `/demo/genesis${qs ? `?${qs}` : ""}`;
}

export function demoWorldUrl(opts: { visual?: boolean } = {}): string {
  return opts.visual ? "/demo/world?visual=1" : "/demo/world";
}

export type GenesisAction =
  | { kind: "create"; pageType: string }
  | { kind: "attach"; ids: string[] } // any of these block/package ids satisfies
  | { kind: "quadrant"; facet: SceneFacet } // the quadrant compass is the action
  | { kind: "advance" }; // pure narration step (the card's own button)

// What stage k asks the player to DO (to reach stage k+1).
export const GENESIS_ACTIONS: Record<number, GenesisAction> = {
  0: { kind: "create", pageType: "root_entity" },
  1: { kind: "attach", ids: ["quadrant_lenses", "wiki.block.quadrants.v1"] },
  2: { kind: "create", pageType: "context_hub" },
  3: { kind: "create", pageType: "person" },
  4: { kind: "attach", ids: ["gamification", "wiki.block.ui_missions.v1"] },
  5: { kind: "create", pageType: "source" },
  6: { kind: "quadrant", facet: "pratica" },
  7: { kind: "advance" }
};

export function genesisAction(stage: number): GenesisAction {
  return GENESIS_ACTIONS[stage] ?? { kind: "advance" };
}

// Does a composed CREATE brief satisfy the current stage's expectation?
export function genesisCreateMatches(stage: number, spec: BriefSpec): boolean {
  const action = genesisAction(stage);
  if (action.kind !== "create") return false;
  return (spec.grounding?.create?.page_type ?? "") === action.pageType;
}

// Does attaching this block/package satisfy the current stage's expectation?
export function genesisAttachMatches(stage: number, id: string): boolean {
  const action = genesisAction(stage);
  if (action.kind !== "attach") return false;
  return action.ids.includes(id);
}

// Does flying through the quadrant compass satisfy the current stage?
export function genesisQuadrantMatches(stage: number, facet: SceneFacet): boolean {
  const action = genesisAction(stage);
  if (action.kind !== "quadrant") return false;
  return action.facet === facet;
}

// Where the expected action LIVES — the dock the tutorial CTA opens. Stage 0
// has NO dock: founding happens through the in-world rite (the cards are the
// action), never through the generic create surface.
export function genesisActionDock(stage: number): { dock: "create" | "blocks"; src?: string } | null {
  if (stage === 0) return null;
  const action = genesisAction(stage);
  if (action.kind === "create") return { dock: "create", src: action.pageType };
  if (action.kind === "attach") return { dock: "blocks" };
  return null;
}
