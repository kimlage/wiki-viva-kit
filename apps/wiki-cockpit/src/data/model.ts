import type { SnapshotBundle } from "../types";

export function reviewChecklist(bundle: SnapshotBundle): { label: string; ok: boolean }[] {
  const git = bundle.git;
  return [
    { label: "Work is isolated for review", ok: git.proposal.is_proposal_branch },
    { label: "Changed content is visible", ok: git.worktree.changed_files.length > 0 || git.worktree.clean },
    { label: "Automated checks are available", ok: bundle.gates.gates.length > 0 },
    { label: "Approval summary can be regenerated", ok: bundle.actions.actions.some((action) => action.id === "pr-summary") },
    { label: "Final approval stays in the review request", ok: true }
  ];
}

// Meta-lists that are NOT problems (the roster of deliberately exempt pages),
// and subset flags that would double-count (bad_repetition ⊂ repeated_blocks).
// The old sum counted all of them, inflating "55 warnings" from ~8 real ones.
const QUALITY_FLAGS_IGNORED = new Set(["quality_exempt_pages"]);
const QUALITY_FLAGS_SUBSET = new Set(["bad_repetition_blocks"]);

export function qualityFlagCount(bundle: SnapshotBundle): number {
  const flags = bundle.quality.quality_flags;
  if (!flags) return 0;
  return Object.entries(flags).reduce((total, [key, entries]) => {
    if (QUALITY_FLAGS_IGNORED.has(key) || QUALITY_FLAGS_SUBSET.has(key)) return total;
    return total + (Array.isArray(entries) ? entries.length : 0);
  }, 0);
}
