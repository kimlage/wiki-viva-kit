// The Codex diagnostics ladder: six honest rungs derived from the live
// capability record. Each rung is a gate that must pass for Codex to be usable;
// exactly ONE rung is "blocked" (the first failing one, carrying the fix), the
// rungs before it are "ok", and the rungs after are "pending" (can't be judged
// until the blocker clears). Pure and deterministic → unit-testable; the
// component maps rung ids to localized labels + copyable fixes.

import type { CodexCapability } from "../types";

export type RungState = "ok" | "blocked" | "pending";
export type CodexRungId = "operator" | "enabled" | "installed" | "runnable" | "authed" | "ready";
export type CodexRung = { id: CodexRungId; state: RungState };

export function codexLadder(cap: CodexCapability): CodexRung[] {
  // Order matters: rung 0 (operator freshness) outranks everything, because a
  // stale operator makes every other field a lie.
  const conditions: [CodexRungId, boolean][] = [
    ["operator", !cap.operator_outdated],
    ["enabled", cap.enabled],
    ["installed", cap.installed],
    ["runnable", cap.runnable],
    ["authed", cap.authed],
    ["ready", cap.usable]
  ];
  let blockedSeen = false;
  return conditions.map(([id, ok]) => {
    // Past the first blocker every reading is untrustworthy → pending.
    if (blockedSeen) return { id, state: "pending" as RungState };
    if (ok) return { id, state: "ok" as RungState };
    blockedSeen = true;
    return { id, state: "blocked" as RungState };
  });
}

// The single blocking rung (the operator's one next action), or null when usable.
export function blockingRung(cap: CodexCapability): CodexRungId | null {
  return codexLadder(cap).find((rung) => rung.state === "blocked")?.id ?? null;
}
