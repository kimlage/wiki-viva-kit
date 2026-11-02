import type { AdminExecuteOutcome } from "../data/admin";

// A transport response is not proof that the requested effect completed.
export function adminOutcomeState(outcome: AdminExecuteOutcome): "success" | "failed" | "uncertain" {
  const output = outcome.output && typeof outcome.output === "object" ? outcome.output as Record<string, unknown> : null;
  if (output?.outcome_uncertain === true || (Array.isArray(output?.uncertain_paths) && output.uncertain_paths.length > 0)) return "uncertain";
  if (outcome.status === "success") return "success";
  return ["failed", "failure", "error"].includes(outcome.status) ? "failed" : "uncertain";
}

