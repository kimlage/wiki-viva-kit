import type { ActionCard, FreshnessState, GitState, PageRecord, SnapshotBundle } from "../types";

export function freshnessTone(state: FreshnessState): "good" | "warn" | "muted" {
  if (state === "fresh") return "good";
  if (state === "stale") return "warn";
  return "muted";
}

export function gitGateLabel(git: GitState): string {
  if (!git.available) return "Git unavailable";
  if (git.current_branch === git.default_branch) {
    return git.worktree.clean ? "Approved wiki" : "Main has local changes";
  }
  if (git.proposal.is_proposal_branch) {
    if (git.proposal.draft_pr_url) return "Draft PR gate";
    return "Local proposal branch";
  }
  return "Outside proposal flow";
}

export function topActions(bundle: SnapshotBundle): ActionCard[] {
  const priority = new Map([
    ["run-honesty-gates", 0],
    ["pr-summary", 1],
    ["review-local-changes", 2],
    ["refresh-cockpit-check", 3],
    ["git-status", 4]
  ]);
  return [...bundle.actions.actions]
    .sort((a, b) => (priority.get(a.id) ?? 99) - (priority.get(b.id) ?? 99))
    .slice(0, 5);
}

export function pageById(pages: PageRecord[], id: string | undefined): PageRecord | undefined {
  if (!id) return pages[0];
  return pages.find((page) => page.id === id || page.path === id) ?? pages[0];
}

export function reviewChecklist(bundle: SnapshotBundle): { label: string; ok: boolean }[] {
  const git = bundle.git;
  return [
    { label: "Work is isolated for review", ok: git.proposal.is_proposal_branch },
    { label: "Changed content is visible", ok: git.worktree.changed_files.length > 0 || git.worktree.clean },
    { label: "Automated checks are available", ok: bundle.gates.gates.length > 0 },
    { label: "Approval summary can be regenerated", ok: bundle.actions.actions.some((action) => action.id === "pr-summary") },
    { label: "Final approval stays in the Pull Request", ok: true }
  ];
}

export function qualityFlagCount(bundle: SnapshotBundle): number {
  const flags = bundle.quality.quality_flags;
  if (!flags) return 0;
  return Object.values(flags).reduce((total, entries) => total + (Array.isArray(entries) ? entries.length : 0), 0);
}
