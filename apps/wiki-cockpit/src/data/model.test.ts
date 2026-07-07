import { describe, expect, it } from "vitest";
import { qualityFlagCount, reviewChecklist } from "./model";
import type { SnapshotBundle } from "../types";

const bundle = {
  actions: {
    actions: [
      { id: "review-local-changes", title: "Review", human_reason: "", kind: "review", risk_level: "read", default_dry_run: false, commands: [] },
      { id: "run-honesty-gates", title: "Gates", human_reason: "", kind: "review", risk_level: "read", default_dry_run: false, commands: [] },
      { id: "pr-summary", title: "Build review packet", human_reason: "", kind: "approve", risk_level: "read", default_dry_run: false, commands: [] }
    ]
  },
  gates: { gates: [{ id: "audit", status: "not_run", argv: [] }], status: "not_run" },
  git: {
    available: true,
    branch_prefix: "wiki/",
    current_branch: "wiki/example",
    default_branch: "main",
    proposal: {
      draft_pr_url: null,
      human_gate_state: "not_opened",
      is_proposal_branch: true,
      theme: "example"
    },
    upstream: { ahead: 1, behind: 0, last_fetch_at: null, name: "", remote: "origin" },
    worktree: {
      clean: false,
      changed_files: [
        {
          known_generated: false,
          path: "memories/index.md",
          staged: false,
          status: "M",
          suggested_stage: true,
          unstaged: true
        }
      ]
    }
  },
  quality: {
    quality_flags: {
      low_information_density_pages: ["a.md", "b.md"],
      bad_repetition_blocks: []
    }
  }
} as unknown as SnapshotBundle;

describe("cockpit model", () => {
  it("builds review checklist and counts quality flags", () => {
    expect(reviewChecklist(bundle).map((item) => item.label)).toEqual([
      "Work is isolated for review",
      "Changed content is visible",
      "Automated checks are available",
      "Approval summary can be regenerated",
      "Final approval stays in the review request"
    ]);
    expect(reviewChecklist(bundle).filter((item) => item.ok)).toHaveLength(5);
    expect(qualityFlagCount(bundle)).toBe(2);
  });
});
