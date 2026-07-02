// Derive the honest approval view from the snapshot — the model behind the Gate
// dock (?dock=approve). It separates CONTENT changes (memory pages, the reason a
// human gate exists) from CODE changes (collapsed into one "workshop crate"),
// reads the real PR state, the honest gate status, and only genuine privacy
// concerns (the diff.py anchor fix already killed the false-alarm class). Pure
// and deterministic → unit-testable.

import type { DiffFile, SnapshotBundle } from "../types";

export type ApprovalDecision = "clean" | "ready" | "review" | "checks";

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
