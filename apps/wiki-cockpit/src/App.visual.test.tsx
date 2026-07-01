// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { SnapshotBundle } from "./types";

const bundle: SnapshotBundle = {
  manifest: {
    schema_version: "wiki_web_snapshot.v1",
    generated_at: "2026-07-01T00:00:00Z",
    mode: "local_operator",
    source_commit: null,
    repo: {
      repo_id: "visual-fixture",
      language: "en",
      memory_root: "memories",
      default_context: "system",
      karma_enabled: true,
      default_branch: "main",
      branch_prefix: "wiki/"
    },
    files: []
  },
  operations: {
    title: "Operations",
    path: "memories/operations.md",
    updated_at: "2026-07-01",
    freshness_state: "fresh",
    sections: [{ title: "Alerts", body: "- No alerts", bullets: ["No alerts"] }]
  },
  graph: {
    nodes: [
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
    ],
    edges: []
  },
  pages: {
    pages: [
      {
        id: "root",
        path: "memories/index.md",
        title: "Root",
        page_type: "root_index",
        context: "system",
        visibility: "private_self",
        status: "",
        updated_at: "2026-07-01",
        stale_after_days: "30",
        freshness_state: "fresh",
        approved_state: "approved",
        risk_flags: [],
        source_refs: [],
        moc_parent: "",
        summary: "Root summary"
      },
      {
        id: "source-fixture",
        path: "memories/sources/source-fixture.md",
        title: "Source Fixture",
        page_type: "source",
        context: "system",
        visibility: "private_self",
        status: "",
        updated_at: "2026-07-01",
        stale_after_days: "30",
        freshness_state: "fresh",
        approved_state: "approved",
        risk_flags: [],
        source_refs: [],
        moc_parent: "",
        summary: "Source summary"
      }
    ]
  },
  actions: {
    actions: [
      {
        id: "run-honesty-gates",
        kind: "review",
        title: "Run local honesty gates",
        human_reason: "Run gates",
        risk_level: "read",
        default_dry_run: false,
        commands: [{ label: "audit", argv: ["python3", "scripts/wiki_audit.py", "--check"], writes: false }]
      },
      {
        id: "pr-summary",
        kind: "approve",
        title: "Generate PR review summary",
        human_reason: "Summarize PR",
        risk_level: "read",
        default_dry_run: false,
        commands: [{ label: "summary", argv: ["python3", "scripts/wiki_pr_summary.py"], writes: false }]
      }
    ]
  },
  freshness: {
    summary: { fresh: 2, stale: 0, unknown: 0 },
    by_context: { system: { fresh: 2, stale: 0, unknown: 0 } },
    stale_pages: []
  },
  gates: {
    status: "not_run",
    gates: [{ id: "audit", status: "not_run", argv: ["python3", "scripts/wiki_audit.py", "--check"] }]
  },
  git: {
    available: true,
    default_branch: "main",
    current_branch: "wiki/visual-fixture",
    branch_prefix: "wiki/",
    worktree: { clean: true, changed_files: [] },
    upstream: { remote: "origin", ahead: 0, behind: 0, name: "", last_fetch_at: null },
    proposal: {
      is_proposal_branch: true,
      theme: "visual-fixture",
      draft_pr_url: null,
      human_gate_state: "not_opened"
    }
  },
  timeline: {
    schema_version: "wiki_web_timeline.v1",
    repo_id: "visual-fixture",
    generated_at: "2026-07-01T00:00:00Z",
    summary: {
      event_count: 2,
      first_at: "2026-07-01T00:00:00Z",
      last_at: "2026-07-01T00:00:00Z",
      by_kind: { page_updated: 1, snapshot: 1 },
      by_context: { system: 2 }
    },
    bands: { last_7_days: 2, last_30_days: 0, older: 0 },
    events: [
      {
        id: "snapshot-generated",
        kind: "snapshot",
        timestamp: "2026-07-01T00:00:00Z",
        label: "Snapshot generated",
        context: "system",
        path: "",
        status: "not_opened",
        weight: 1,
        commit: ""
      },
      {
        id: "page-root",
        kind: "page_updated",
        timestamp: "2026-07-01T00:00:00Z",
        label: "Root",
        context: "system",
        path: "memories/index.md",
        status: "fresh",
        weight: 2,
        commit: ""
      }
    ]
  },
  diff: {
    schema_version: "wiki_web_diff.v1",
    repo_id: "visual-fixture",
    available: true,
    compare: {
      default_branch: "main",
      base_ref: "main",
      merge_base: "abc123",
      head_commit: "def456",
      current_branch: "wiki/visual-fixture"
    },
    summary: {
      file_count: 1,
      branch_file_count: 1,
      working_tree_file_count: 0,
      insertions: 4,
      deletions: 1,
      status_counts: { M: 1 },
      privacy_review_required: true
    },
    commands: [["git", "diff", "--stat", "abc123..HEAD"]],
    files: [
      {
        path: "memories/index.md",
        status: "M",
        category: "memory",
        change_sources: ["branch"],
        additions: 4,
        deletions: 1,
        known_generated: false,
        staged: false,
        unstaged: false,
        risk_hints: ["memory_review"],
        preview: ["@@ -1 +1 @@", "+Root summary"]
      }
    ]
  },
  sources: { sources: [] },
  decisions: { decisions: [] },
  ingestion: {},
  quality: { quality_flags: {} },
  commands: { commands: [] }
};

vi.mock("./components/SystemScene", () => ({
  SystemScene: () => <div data-testid="scene-fallback">Scene fallback</div>
}));

vi.mock("./data/snapshot", () => ({
  loadSnapshotBundle: vi.fn(async () => ({
    bundle,
    source: "/api/snapshot",
    runtime: { apiBase: "/api", snapshotBase: "", repoLabel: "", mode: "local_operator" }
  })),
  runCockpitAction: vi.fn(),
  runGitWorkflow: vi.fn(),
  buildIngestionPlan: vi.fn(),
  runIngestionStep: vi.fn()
}));

async function renderRoute(path: string) {
  window.history.pushState({}, "", path);
  render(<App />);
}

afterEach(() => {
  cleanup();
});

describe("visual route contract", () => {
  it("renders the core cockpit routes with textual fallbacks", async () => {
    await renderRoute("/ops");
    expect(await screen.findByRole("heading", { name: "Operations" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Graph Search" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Page Action Drawer" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Impact Bundle" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Timeline Radar" })).toBeTruthy();
    expect(screen.getByTestId("scene-fallback")).toBeTruthy();
    cleanup();

    await renderRoute("/review");
    expect(await screen.findByRole("heading", { name: "Human Gate" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Git Workflow" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Semantic Diff" })).toBeTruthy();
    cleanup();

    await renderRoute("/sources");
    expect(await screen.findByRole("heading", { name: "Sources" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Ingestion Wizard" })).toBeTruthy();
    cleanup();

    await renderRoute("/health");
    expect(await screen.findByRole("heading", { name: "Context Vitality" })).toBeTruthy();
    cleanup();

    await renderRoute("/pages/root");
    expect(await screen.findByRole("heading", { name: "Root" })).toBeTruthy();
    cleanup();

    await renderRoute("/demo");
    expect(await screen.findByRole("heading", { name: "Operations" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Graph Search" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Timeline Radar" })).toBeTruthy();
  });

  it("adds a searched page to the local impact bundle with shift-click", async () => {
    await renderRoute("/ops");
    const sourceResult = await screen.findByRole("button", { name: /Source Fixture/ });
    fireEvent.click(sourceResult, { shiftKey: true });

    const impactBundle = screen.getByRole("region", { name: "Impact Bundle" });
    expect(within(impactBundle).getByText("Source Fixture")).toBeTruthy();
    expect(within(impactBundle).getByText("memories/sources/source-fixture.md")).toBeTruthy();
    expect(within(impactBundle).getByText(/Human gate: not_opened/)).toBeTruthy();
  });
});
