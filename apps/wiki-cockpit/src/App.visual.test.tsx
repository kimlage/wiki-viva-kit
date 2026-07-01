// @vitest-environment happy-dom

import { cleanup, render, screen } from "@testing-library/react";
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
    expect(screen.getByTestId("scene-fallback")).toBeTruthy();
    cleanup();

    await renderRoute("/review");
    expect(await screen.findByRole("heading", { name: "Human Gate" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Git Workflow" })).toBeTruthy();
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
  });
});
