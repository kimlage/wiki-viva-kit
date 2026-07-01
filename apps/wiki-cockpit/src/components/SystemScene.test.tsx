// @vitest-environment happy-dom

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { canUseWebGL, SystemScene } from "./SystemScene";
import type { GitState, GraphNode } from "../types";

const nodes: GraphNode[] = [
  {
    id: "root",
    path: "memories/index.md",
    title: "Root",
    page_type: "root_index",
    context: "system",
    freshness_state: "fresh",
    approved_state: "approved",
    risk_flags: [],
    metrics: { inbound_links: 0, outbound_links: 1, source_ref_count: 0 }
  }
];

const git: GitState = {
  available: true,
  default_branch: "main",
  current_branch: "wiki/fallback",
  branch_prefix: "wiki/",
  worktree: { clean: true, changed_files: [] },
  upstream: { remote: "origin", ahead: 0, behind: 0, name: "", last_fetch_at: null },
  proposal: {
    is_proposal_branch: true,
    theme: "fallback",
    draft_pr_url: null,
    human_gate_state: "not_opened"
  }
};

describe("SystemScene fallback", () => {
  it("uses the 2D fallback when WebGL is unavailable", () => {
    expect(canUseWebGL()).toBe(false);

    render(<SystemScene nodes={nodes} git={git} />);

    expect(screen.getByLabelText("Content map")).toBeTruthy();
    expect(screen.getByText("Draft change")).toBeTruthy();
    expect(screen.getByText("Root")).toBeTruthy();
  });
});
