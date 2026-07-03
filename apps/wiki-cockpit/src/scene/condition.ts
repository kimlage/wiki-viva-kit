// The world's CONDITION — one pure selector that turns the snapshot into the
// ambient signals the ops cockpit reads (weather + counted readout). Every field
// traces 1:1 to a real bundle count; nothing here is decorative. It lives in
// scene/ (it shares the scene's purity contract and feeds SystemScene) but is NOT
// part of computeWorldLayout, so the layout worker's determinism is untouched.

import type { SnapshotBundle } from "../types";

export type Weather = "clear" | "aging" | "unverified" | "blocked";

export type WorldCondition = {
  weather: Weather;
  freshRatio: number;
  staleCount: number;
  unknownCount: number;
  gatesFailing: string[];
  gatesNotRun: number;
  // ONLY local, uncommitted memory edits (working_tree/staged) — NOT the whole
  // branch-vs-default diff, which on a long-lived proposal branch would overstate
  // pending approval by hundreds of already-committed pages.
  pendingApproval: number;
  pendingSourceIntake: number;
  agentsActive: number;
};

const AGING_THRESHOLD = 0.15; // stale fraction that tips the weather to "aging"
const UNVERIFIED_THRESHOLD = 0.25; // unknown fraction that tips it to "unverified"

export function computeCondition(bundle: SnapshotBundle, agentsActive = 0): WorldCondition {
  const summary = bundle.freshness?.summary ?? { fresh: 0, stale: 0, unknown: 0 };
  const fresh = summary.fresh ?? 0;
  const stale = summary.stale ?? 0;
  const unknown = summary.unknown ?? 0;
  const total = fresh + stale + unknown;
  const freshRatio = total > 0 ? fresh / total : 1;

  const gates = bundle.gates?.gates ?? [];
  const gatesFailing = gates.filter((g) => g.status === "fail").map((g) => g.id);
  const gatesNotRun = gates.filter((g) => g.status === "not_run").length;

  const pendingApproval = (bundle.diff?.files ?? []).filter(
    (f) => f.category === "memory" && (f.change_sources ?? []).some((s) => s === "working_tree" || s === "staged")
  ).length;

  const pendingSourceIntake = bundle.sourceEntities?.summary?.pending ?? 0;

  // A failing gate dominates (blocked); else too many unverified pages; else too
  // much stale; else clear. Thresholds are on FRACTIONS so a big wiki isn't
  // permanently "aging" just for having some stale pages.
  let weather: Weather = "clear";
  if (gatesFailing.length > 0) weather = "blocked";
  else if (total > 0 && unknown / total > UNVERIFIED_THRESHOLD) weather = "unverified";
  else if (total > 0 && stale / total > AGING_THRESHOLD) weather = "aging";

  return {
    weather,
    freshRatio,
    staleCount: stale,
    unknownCount: unknown,
    gatesFailing,
    gatesNotRun,
    pendingApproval,
    pendingSourceIntake,
    agentsActive
  };
}
