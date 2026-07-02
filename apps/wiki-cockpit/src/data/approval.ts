// Derive the honest approval view from the snapshot — the model behind the Gate
// dock (?dock=approve). It separates CONTENT changes (memory pages, the reason a
// human gate exists) from CODE changes (collapsed into one "workshop crate"),
// reads the real PR state, the honest gate status, and only genuine privacy
// concerns (the diff.py anchor fix already killed the false-alarm class). Pure
// and deterministic → unit-testable.

import type { BriefSpec, DiffFile, SnapshotBundle } from "../types";

export type ApprovalDecision = "clean" | "ready" | "review" | "checks";

// Cap for gate failure output embedded in a fix brief: enough tail to diagnose
// (failures print last), small enough to keep the brief readable.
const GATE_OUTPUT_MAX_CHARS = 2000;

export function trimGateOutput(stdout: string, stderr: string, maxChars = GATE_OUTPUT_MAX_CHARS): string {
  const merged = [stdout?.trim(), stderr?.trim()].filter(Boolean).join("\n--- stderr ---\n");
  if (merged.length <= maxChars) return merged;
  // Keep the TAIL — test runners and audits print the verdict last.
  return `…\n${merged.slice(-maxChars)}`;
}

// Compose the BriefSpec for "fix this failing check with Codex". Pure: the
// caller passes the gate identity + argv and (when a run happened in-session)
// the redacted failure output. The brief grammar has no arbitrary-grounding
// slot, so the evidence rides in `intent` (rendered verbatim in section 4) and
// the audit state_report pins the machine-readable gate statuses.
export function gateFixSpec(gate: { id: string; argv: string[] }, failureOutput?: string): BriefSpec {
  const command = gate.argv.join(" ");
  const lines = [
    `Fix the failing check "${gate.id}" so it passes.`,
    `Reproduce locally with: ${command}`,
    failureOutput
      ? `Failure output from the last run (secret-redacted):\n${failureOutput}`
      : `Run the command first to capture the current failure output.`,
    "Fix the underlying cause — never weaken or skip the check itself."
  ];
  return {
    mission_kind: "verify",
    theme: `fix-${gate.id.replaceAll("_", "-")}`,
    grounding: { state_report: { scope: "audit" }, attach_context_package: true },
    intent: lines.join("\n\n")
  };
}

export type ApprovalView = {
  decision: ApprovalDecision;
  contentFiles: DiffFile[];
  codeFiles: DiffFile[];
  fileCount: number;
  prUrl: string | null;
  humanGateState: string;
  isProposalBranch: boolean;
  gateStatus: string; // pass | fail | partial | not_run
  privacyFiles: DiffFile[]; // genuine public-boundary content only
};

export function deriveApproval(bundle: SnapshotBundle): ApprovalView {
  const files = bundle.diff?.files ?? [];
  const contentFiles = files.filter((f) => f.category === "memory");
  const codeFiles = files.filter((f) => f.category !== "memory");
  const privacyFiles = files.filter((f) => f.risk_hints?.includes("public_boundary"));
  const prUrl = bundle.git?.proposal?.draft_pr_url ?? null;
  const humanGateState = bundle.git?.proposal?.human_gate_state ?? "";
  const isProposalBranch = Boolean(bundle.git?.proposal?.is_proposal_branch);
  const gateStatus = bundle.gates?.status ?? "not_run";
  const fileCount = files.length;

  let decision: ApprovalDecision;
  if (fileCount === 0) {
    decision = "clean";
  } else if (gateStatus === "fail") {
    decision = "checks"; // a red gate blocks readiness regardless of PR state
  } else if (prUrl || humanGateState === "ready_for_review") {
    decision = "review"; // a request is open — it waits at GitHub
  } else {
    decision = "ready"; // changes exist, prepare the review
  }

  return {
    decision,
    contentFiles,
    codeFiles,
    fileCount,
    prUrl,
    humanGateState,
    isProposalBranch,
    gateStatus,
    privacyFiles
  };
}
