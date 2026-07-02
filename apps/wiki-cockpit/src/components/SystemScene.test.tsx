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
  },
  {
    id: "alpha",
    path: "memories/example/alpha.md",
    title: "Alpha",
    page_type: "context_note",
    context: "example",
    freshness_state: "stale",
    approved_state: "approved",
    risk_flags: [],
    updated_at: "2026-01-01",
    stale_after_days: "30",
    metrics: { inbound_links: 1, outbound_links: 0, source_ref_count: 1 }
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
  it("uses the 2D fallback with the same topology and URLs when WebGL is unavailable", () => {
    expect(canUseWebGL()).toBe(false);

    render(
      <SystemScene
        nodes={nodes}
        git={git}
        route={{ perspective: "radar", reader: false, filter: "" }}
        highlightedPageIds={["alpha"]}
        makeHref={(patch) => `/w/radar${patch.context ? `/${patch.context}` : ""}`}
      />
    );

    expect(screen.getByLabelText("Content map")).toBeTruthy();
    expect(screen.getByText("Draft change")).toBeTruthy();
    // Groups render as links sharing the world URL grammar.
    const groupLink = screen.getByRole("link", { name: /example · 1/ });
    expect(groupLink.getAttribute("href")).toBe("/w/radar/example");
    // Alpha is stale in the fixture: its accessible name now carries the state
    // chip too (fallback never encodes state in color alone).
    expect(screen.getByRole("link", { name: /Alpha needs refresh/ })).toBeTruthy();
  });
});
