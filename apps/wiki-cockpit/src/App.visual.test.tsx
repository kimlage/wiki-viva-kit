// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { SnapshotBundle } from "./types";

const bundle: SnapshotBundle = {
  manifest: {
    schema_version: "wiki_web_snapshot.v1",
    generated_at: "2026-07-01T00:00:00Z",
    mode: "local_operator",
    content_sidecars: false,
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
        summary: "Root summary",
        summary_truncated: false
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
        moc_parent: "memories/index.md",
        summary: "Source summary",
        summary_truncated: true
      }
    ]
  },
  actions: {
    actions: [
      {
        id: "run-honesty-gates",
        kind: "review",
        title: "Run approval checks",
        human_reason: "Run checks",
        risk_level: "read",
        default_dry_run: false,
        commands: [{ label: "audit", argv: ["python3", "scripts/wiki_audit.py", "--check"], writes: false }]
      },
      {
        id: "pr-summary",
        kind: "approve",
        title: "Build review packet",
        human_reason: "Summarize approval evidence",
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
      event_count: 1,
      first_at: "2026-07-01T00:00:00Z",
      last_at: "2026-07-01T00:00:00Z",
      by_kind: { snapshot: 1 },
      by_context: { system: 1 }
    },
    bands: { last_7_days: 1, last_30_days: 0, older: 0 },
    events: []
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
  commands: { commands: [] },
  score: {
    schema_version: "wiki_web_score.v1",
    enabled: true,
    event_count: 3,
    total: 12.5,
    level: "jardineiro",
    level_labels: { en: "Gardener", pt: "Jardineiro" },
    by_dimension: { confiabilidade: 6.5, stewardship: 6 },
    badges: [{ id: "first_source", en: "First source", pt: "Primeira fonte" }],
    vitality: {}
  }
};

vi.mock("./components/SystemScene", () => ({
  canUseWebGL: () => false,
  SystemScene: ({ children }: { children?: import("react").ReactNode }) => (
    <div data-testid="scene-fallback">{children}</div>
  )
}));

vi.mock("./data/snapshot", () => ({
  loadSnapshotBundle: vi.fn(async () => ({
    bundle,
    source: "/api/snapshot",
    runtime: { apiBase: "/api", snapshotBase: "", repoLabel: "", mode: "local_operator", presentation: {} }
  })),
  loadPageContent: vi.fn(async () => ({
    ok: true,
    page: {
      page_id: "root",
      path: "memories/index.md",
      title: "Root",
      context: "system",
      page_type: "root_index",
      freshness_state: "fresh",
      approved_state: "approved",
      summary: "Root summary",
      summary_truncated: false,
      updated_at: "2026-07-01",
      moc_parent: ""
    },
    frontmatter: {},
    body: "# Root\n\nCorpo completo da página com [Source Fixture](sources/source-fixture.md).\n\n## Detalhes\n\nMais texto.",
    resolved_links: [
      {
        kind: "page",
        text: "Source Fixture",
        href: "sources/source-fixture.md",
        page_id: "source-fixture",
        path: "memories/sources/source-fixture.md",
        title: "Source Fixture",
        context: "system",
        page_type: "source",
        freshness_state: "fresh",
        approved_state: "approved"
      }
    ],
    backlinks: [],
    source_refs: []
  })),
  sidecarName: (id: string) => `${id}.json`,
  runCockpitAction: vi.fn(),
  runGitWorkflow: vi.fn(),
  buildIngestionPlan: vi.fn(),
  runIngestionStep: vi.fn(),
  loadCodexCapability: vi.fn(async () => ({
    enabled: true,
    installed: false,
    runnable: false,
    authed: false,
    auth_mode: null,
    version: null,
    usable: false,
    reason: "not available in test"
  })),
  composeBrief: vi.fn(),
  saveBriefText: vi.fn(),
  discardBrief: vi.fn(),
  getBrief: vi.fn(),
  spawnCodexJob: vi.fn(),
  returnCodexJob: vi.fn(),
  listCodexJobs: vi.fn(async () => []),
  listBriefs: vi.fn(async () => []),
  streamCodexLog: vi.fn(async () => ""),
  cancelCodexJob: vi.fn(),
  loadFileDiff: vi.fn(async () => ({ ok: true, diff: [] })),
  runGate: vi.fn(async () => ({ ok: true })),
  intakeCopy: vi.fn(async () => ({ ok: true, path: "data/raw/system/x" }))
}));

async function renderRoute(path: string) {
  window.history.pushState({}, "", path);
  render(<App />);
}

afterEach(() => {
  cleanup();
});

describe("visual route contract", () => {
  it("renders the world shell with HUD, perspectives and 2D routes", async () => {
    await renderRoute("/w/radar");
    expect(await screen.findByLabelText("3D knowledge world")).toBeTruthy();
    expect(screen.getByText("Galaxy")).toBeTruthy();
    expect(screen.getByRole("group", { name: "Perspectives (keys 1–4)" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Districts/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Trails/ })).toBeTruthy();
    expect(screen.getByLabelText("Search content")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Packet 0/ })).toBeTruthy();
    expect(screen.getByTestId("scene-fallback")).toBeTruthy();
    cleanup();

    await renderRoute("/review");
    // /review dissolved into the world Gate dock (?dock=approve) — Aprovar died.
    expect(await screen.findByRole("dialog", { name: "Approve changes" })).toBeTruthy();
    cleanup();

    await renderRoute("/sources");
    // /sources dissolved into the world Intake dock (?dock=intake) — Adicionar died.
    expect(await screen.findByRole("dialog", { name: "Add knowledge" })).toBeTruthy();
    cleanup();

    await renderRoute("/health");
    // /health dissolved into the world Gates dock (?dock=gates) — Saúde is weather.
    expect(await screen.findByRole("dialog", { name: "Checks" })).toBeTruthy();
    cleanup();

    await renderRoute("/demo/w/radar");
    expect(await screen.findByText(/Interface demo with synthetic sample data/)).toBeTruthy();
  });

  it("redirects legacy /pages/:id bookmarks into the world with the reader open", async () => {
    await renderRoute("/pages/root");
    await waitFor(() => {
      expect(window.location.pathname).toBe("/w/atlas/system/sem-pai/root");
    });
    expect(window.location.search).toContain("reader=1");
    expect(await screen.findByLabelText("Reader: Root")).toBeTruthy();
    // Full markdown body rendered inside the world shell — no truncation.
    expect(await screen.findByText(/Corpo completo da página/)).toBeTruthy();
  });

  it("keeps search as URL state and lists results in the mission card", async () => {
    await renderRoute("/w/radar?q=Source");
    expect(await screen.findByLabelText("3D knowledge world")).toBeTruthy();
    expect(await screen.findByText(/1 result/)).toBeTruthy();
    const hit = screen.getByRole("button", { name: /Source Fixture/ });
    fireEvent.click(hit);
    await waitFor(() => {
      expect(window.location.pathname).toContain("/w/radar/system/");
      expect(window.location.pathname).toContain("source-fixture");
    });
    expect(window.location.search).toContain("reader=1");
  });
});
