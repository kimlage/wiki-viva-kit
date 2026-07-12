// @vitest-environment happy-dom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { loadSnapshotBundle } from "./data/snapshot";
import { browserApplication } from "./infrastructure/browserApplication";
import type { SnapshotBundle } from "./types";

const mockSnapshotState = vi.hoisted(() => ({
  runtimeMode: "local_operator",
  source: "/api/snapshot"
}));

const bundle: SnapshotBundle = {
  manifest: {
    schema_version: "wiki_web_snapshot.v1",
    compatibility: {
      state: "stale_version",
      warnings: ["Previous snapshot version loaded in compatibility mode"]
    },
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
  temporalGraph: {
    schema_version: "wiki_temporal_graph.v1",
    event_schema_version: "wiki_temporal_event.v1",
    repo_id: "visual-fixture",
    revision: "visual-fixture",
    generated_at: "2026-07-01T00:00:00Z",
    event_count: 0,
    total_count: 0,
    returned_count: 0,
    truncated: false,
    next_cursor: null,
    page: { offset: 0, limit: 0, remaining_count: 0, fingerprint: "visual-fixture-empty" },
    range: { from: null, to: null, from_precision: null, to_precision: null, event_count: 0, dated_count: 0, undated_count: 0, basis: "full_result" },
    returned_range: { from: null, to: null, from_precision: null, to_precision: null, event_count: 0, dated_count: 0, undated_count: 0, basis: "returned_page" },
    summary: { scope: "full_result", event_count: 0, by_kind: {}, by_context: {}, conflict_count: 0, imprecise_count: 0, diagnostic_count: 0 },
    diagnostics: [],
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
  },
  sourceEntities: { schema_version: "wiki_web_source_entities.v1", sources: [] },
  templates: { schema_version: "wiki_templates.v1", facets_order: ["intencao", "pratica", "relacoes", "sistemas"], types: {} },
  blocks: { schema_version: "wiki_web_blocks.v1", blocks: {}, vocabulary: {}, warnings: [] },
  blockStacks: { schema_version: "wiki_web_block_stacks.v1", anchors: {} }
};

vi.mock("./components/SystemScene", () => ({
  canUseWebGL: () => false,
  sceneFallbackPreferred: () => true,
  SystemScene: ({ children }: { children?: import("react").ReactNode }) => (
    <div data-testid="scene-fallback">{children}</div>
  )
}));

vi.mock("./data/snapshot", () => ({
  loadSnapshotBundle: vi.fn(async () => ({
    bundle,
    source: mockSnapshotState.source,
    runtime: {
      apiBase: "/api",
      snapshotBase: "",
      repoLabel: "",
      mode: mockSnapshotState.runtimeMode,
      language: "",
      strings: {},
      presentation: {},
      codexEnabled: true
    }
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
  loadTemporalGraphForBundle: vi.fn(async () => {
    throw Object.assign(new Error("temporal graph unavailable in v1 fixture"), { code: "partial" });
  }),
  sidecarName: (id: string) => `${id}.json`,
  runOperatorCommand: vi.fn(),
  runGitWorkflow: vi.fn(),
  buildIngestionPlan: vi.fn(),
  runIngestionStep: vi.fn(),
  composeSourceBrief: vi.fn(async () => ({ ok: false })),
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
  render(<App ports={browserApplication} />);
}

afterEach(() => {
  mockSnapshotState.runtimeMode = "local_operator";
  mockSnapshotState.source = "/api/snapshot";
  cleanup();
});

describe("visual route contract", () => {
  it("renders the world shell with HUD, perspectives and 2D routes", async () => {
    await renderRoute("/w/radar");
    expect(
      await screen.findByLabelText("3D knowledge world", {}, { timeout: 3_000 })
    ).toBeTruthy();
    expect(await screen.findByText("Galaxy")).toBeTruthy();
    expect(screen.getByRole("group", { name: "Perspectives (keys 1–5)" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Districts/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Trails/ })).toBeTruthy();
    expect(screen.getByLabelText("Search content")).toBeTruthy();
    // The packet collector only exists while it HAS pages — empty is invisible.
    expect(screen.queryByRole("button", { name: /Packet/ })).toBeNull();
    expect(screen.getByTestId("scene-fallback")).toBeTruthy();
    expect(screen.getByText(/Previous snapshot contract|Contrato de snapshot anterior/)).toBeTruthy();
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
    expect(await screen.findByText(/Read-only demo with synthetic data/)).toBeTruthy();
  });

  it("redirects legacy /pages/:id bookmarks into the world with the reader open", async () => {
    await renderRoute("/pages/root");
    await waitFor(() => {
      expect(window.location.pathname).toBe("/w");
    });
    expect(window.location.search).toContain("view=atlas");
    expect(window.location.search).toContain("page=root");
    expect(window.location.search).toContain("reader=1");
    expect(window.location.search).toContain("runtime=compat");
    expect(await screen.findByLabelText("Reader: Root")).toBeTruthy();
    // Full markdown body rendered inside the world shell — no truncation.
    expect(await screen.findByText(/Corpo completo da página/)).toBeTruthy();
  });

  it("keeps search as URL state and lists results in the mission card", async () => {
    await renderRoute("/w/radar?q=Source");
    expect(
      await screen.findByLabelText("3D knowledge world", {}, { timeout: 3_000 })
    ).toBeTruthy();
    expect(await screen.findByText(/1 result/)).toBeTruthy();
    const hit = screen.getByRole("option", { name: /Source Fixture/ });
    fireEvent.click(hit);
    await waitFor(() => {
      expect(window.location.pathname).toBe("/w");
      expect(window.location.search).toContain("view=radar");
      expect(window.location.search).toContain("page=source-fixture");
    });
    expect(window.location.search).toContain("reader=1");
  });

  it("keeps the search surface operable over the temporal view with URL-owned facets", async () => {
    await renderRoute("/w?view=timeline&q=Source");
    expect(
      await screen.findByLabelText("3D knowledge world", {}, { timeout: 3_000 })
    ).toBeTruthy();

    const search = screen.getByRole("combobox", { name: "Search content" });
    expect(search.getAttribute("aria-expanded")).toBe("true");
    expect(search.getAttribute("aria-controls")).toBe("world-search-results");
    expect(await screen.findByRole("listbox", { name: /1 result/ })).toBeTruthy();
    expect(screen.getByRole("option", { name: /Source Fixture/ })).toBeTruthy();

    fireEvent.change(screen.getByRole("combobox", { name: "Type" }), {
      target: { value: "source" }
    });
    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get("search_type")).toBe("source");
    });
    expect(screen.getByRole("option", { name: /Source Fixture/ })).toBeTruthy();
  });

  it("keeps pointer and keyboard search selection coherent across result-window changes", async () => {
    const loadSnapshotMock = vi.mocked(loadSnapshotBundle);
    const defaultImplementation = loadSnapshotMock.getMockImplementation();
    expect(defaultImplementation).toBeTruthy();
    const densePages = Array.from({ length: 18 }, (_, index) => {
      const ordinal = String(index + 1).padStart(3, "0");
      return {
        ...bundle.pages.pages[0],
        id: `dense-action-${ordinal}`,
        path: `memories/actions/dense-action-${ordinal}.md`,
        title: `Dense canonical action ${ordinal}`,
        page_type: "action",
        context: "clients",
        moc_parent: "memories/index.md",
        summary: `Dense action ${ordinal}`
      };
    });
    const denseNodes = densePages.map((page) => ({
      ...bundle.graph.nodes[0],
      id: page.id,
      path: page.path,
      title: page.title,
      page_type: page.page_type,
      context: page.context
    }));
    loadSnapshotMock.mockImplementation(async (options) => {
      const loaded = await defaultImplementation!(options);
      return {
        ...loaded,
        bundle: {
          ...bundle,
          pages: { pages: [bundle.pages.pages[0], ...densePages] },
          graph: { ...bundle.graph, nodes: [bundle.graph.nodes[0], ...denseNodes] }
        }
      };
    });

    const scrollIntoView = vi.fn();
    const originalScrollIntoView = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "scrollIntoView"
    );
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView
    });

    try {
      await renderRoute("/w?view=radar&q=dense-canonical%20action");
      expect(
        await screen.findByLabelText("3D knowledge world", {}, { timeout: 3_000 })
      ).toBeTruthy();
      const search = screen.getByRole("combobox", { name: "Search content" });
      let options = await screen.findAllByRole("option", { name: /Dense canonical action/ });
      expect(options).toHaveLength(10);

      fireEvent.click(screen.getByRole("button", { name: /Show 8 more/ }));
      await waitFor(() => {
        expect(screen.getAllByRole("option", { name: /Dense canonical action/ })).toHaveLength(18);
      });
      options = screen.getAllByRole("option", { name: /Dense canonical action/ });
      fireEvent.pointerMove(options[15]);
      expect(search.getAttribute("aria-activedescendant")).toBe("world-search-results-option-15");

      // Back/route hydration can shrink the visible window while preserving
      // the full result set. The selected option disappeared, so all ARIA and
      // keyboard state must reset to the first real visible option.
      window.history.pushState({}, "", "/w?view=radar&q=dense-canonical%20action");
      window.dispatchEvent(new PopStateEvent("popstate"));
      await waitFor(() => {
        expect(screen.getAllByRole("option", { name: /Dense canonical action/ })).toHaveLength(10);
        expect(search.getAttribute("aria-activedescendant")).toBe("world-search-results-option-0");
      });
      options = screen.getAllByRole("option", { name: /Dense canonical action/ });
      expect(options.filter((option) => option.getAttribute("aria-selected") === "true")).toEqual([
        options[0]
      ]);

      // Merely moving/reflowing an option under a stationary cursor must not
      // claim keyboard selection; a real pointer move still may.
      fireEvent.mouseEnter(options[6]);
      expect(search.getAttribute("aria-activedescendant")).toBe("world-search-results-option-0");

      fireEvent.pointerMove(options[6]);
      expect(search.getAttribute("aria-activedescendant")).toBe("world-search-results-option-6");

      // Keep all three input events in one React turn. This reproduces the
      // browser path where no render is guaranteed between edit, ArrowDown and
      // Enter, while the old pointer-owned index is still 6.
      act(() => {
        fireEvent.change(search, { target: { value: "dense canonical action" } });
        fireEvent.keyDown(search, { key: "ArrowDown" });
        fireEvent.keyDown(search, { key: "Enter" });
      });

      await waitFor(() => {
        expect(new URLSearchParams(window.location.search).get("page")).toBe("dense-action-002");
        expect(new URLSearchParams(window.location.search).get("reader")).toBe("1");
      });
      expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest", inline: "nearest" });
    } finally {
      loadSnapshotMock.mockImplementation(defaultImplementation!);
      if (originalScrollIntoView) {
        Object.defineProperty(HTMLElement.prototype, "scrollIntoView", originalScrollIntoView);
      } else {
        delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;
      }
    }
  });

  it("blocks sample fallback outside demo so real validation cannot impersonate sample data", async () => {
    mockSnapshotState.runtimeMode = "sample_fallback";
    mockSnapshotState.source = "/sample-snapshot";

    await renderRoute("/w/radar");

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/Real snapshot required/);
    expect(alert.textContent).toMatch(/Sample fallback is blocked outside \/demo/);
    expect(screen.queryByLabelText("3D knowledge world")).toBeNull();
  });

  it("reloads the demo bundle when the allowlisted scenario changes without reloading the document", async () => {
    const loadSnapshotMock = vi.mocked(loadSnapshotBundle);
    loadSnapshotMock.mockClear();
    await renderRoute("/demo/world?demo_scenario=dense_stress&tour=0");

    await waitFor(() => {
      expect(loadSnapshotMock).toHaveBeenCalledWith({
        demo: true,
        stage: null,
        demoScenario: "dense_stress"
      });
    });
    // The loader mock resolves immediately. Wait for the route subscription and
    // world shell to commit before simulating an in-document navigation; under
    // the full parallel suite, dispatching on the loader call alone can race the
    // navigation effect and turn this regression test into a timing flake.
    expect(
      await screen.findByLabelText("3D knowledge world", {}, { timeout: 3_000 })
    ).toBeTruthy();

    browserApplication.navigation.dispatch({
      type: "navigate",
      target: "/demo/world?demo_scenario=normal_operations&tour=0"
    });

    await waitFor(() => {
      expect(loadSnapshotMock).toHaveBeenCalledWith({
        demo: true,
        stage: null,
        demoScenario: "normal_operations"
      });
    });
    const demoCalls = loadSnapshotMock.mock.calls
      .map(([options]) => options)
      .filter((options) => options?.demo);
    expect(loadSnapshotMock.mock.calls.some(([options]) => options?.demo === false)).toBe(false);
    expect(demoCalls.map((options) => options?.demoScenario)).toEqual([
      "dense_stress",
      "normal_operations"
    ]);
  });

  it("silently adopts a newer real snapshot on focus without losing URL, reader, or focus", async () => {
    const loadSnapshotMock = vi.mocked(loadSnapshotBundle);
    const defaultImplementation = loadSnapshotMock.getMockImplementation();
    expect(defaultImplementation).toBeTruthy();
    const now = vi.spyOn(Date, "now").mockReturnValue(1_000);
    const bundleA = {
      ...bundle,
      manifest: { ...bundle.manifest, snapshot_id: "fixture-A", bundle_hash: "bundle-A" }
    } as SnapshotBundle;
    const bundleB = {
      ...bundle,
      manifest: {
        ...bundle.manifest,
        // Same snapshot id with a different bundle hash is still a different
        // immutable revision and must be adopted.
        snapshot_id: "fixture-A",
        bundle_hash: "bundle-B",
        repo: { ...bundle.manifest.repo, repo_id: "visual-fixture-refreshed" }
      },
      pages: {
        pages: bundle.pages.pages.map((page) =>
          page.id === "root" ? { ...page, title: "Root refreshed" } : page
        )
      }
    } as SnapshotBundle;
    let realCalls = 0;
    loadSnapshotMock.mockClear();
    loadSnapshotMock.mockImplementation(async (options) => {
      const loaded = await defaultImplementation!(options);
      if (options?.demo) return loaded;
      realCalls += 1;
      return { ...loaded, bundle: realCalls === 1 ? bundleA : bundleB };
    });

    try {
      await renderRoute("/w?view=atlas&page=root&reader=1&runtime=compat");
      const dialog = await screen.findByLabelText("Reader: Root");
      expect(loadSnapshotMock.mock.calls.filter(([options]) => options?.demo === false)).toHaveLength(1);
      dialog.focus();
      expect(document.activeElement).toBe(dialog);
      const routeBefore = `${window.location.pathname}${window.location.search}`;

      now.mockReturnValue(6_001);
      window.dispatchEvent(new Event("focus"));
      document.dispatchEvent(new Event("visibilitychange"));
      expect(loadSnapshotMock.mock.calls.filter(([options]) => options?.demo === false)).toHaveLength(2);

      const refreshedDialog = await screen.findByLabelText("Reader: Root refreshed");
      expect(await screen.findByText(/visual-fixture-refreshed/)).toBeTruthy();
      expect(`${window.location.pathname}${window.location.search}`).toBe(routeBefore);
      expect(refreshedDialog).toBe(dialog);
      expect(document.activeElement).toBe(refreshedDialog);
      expect(loadSnapshotMock.mock.calls.filter(([options]) => options?.demo === false)).toHaveLength(2);

      // A further visibility signal after completion is also throttled, so a
      // noisy browser cannot turn revalidation into a request loop.
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
      expect(loadSnapshotMock.mock.calls.filter(([options]) => options?.demo === false)).toHaveLength(2);
    } finally {
      now.mockRestore();
      loadSnapshotMock.mockImplementation(defaultImplementation!);
    }
  });

  it("revalidates once, without throttle or loading flash, when returning from demo to a changed real wiki", async () => {
    const loadSnapshotMock = vi.mocked(loadSnapshotBundle);
    const defaultImplementation = loadSnapshotMock.getMockImplementation();
    expect(defaultImplementation).toBeTruthy();
    const bundleBeforeDemo = {
      ...bundle,
      manifest: {
        ...bundle.manifest,
        snapshot_id: "real-before-demo",
        bundle_hash: "bundle-before-demo",
        repo: { ...bundle.manifest.repo, repo_id: "repo-before-demo" }
      }
    } as SnapshotBundle;
    const bundleAfterDemo = {
      ...bundle,
      manifest: {
        ...bundle.manifest,
        snapshot_id: "real-after-demo",
        bundle_hash: "bundle-after-demo",
        repo: { ...bundle.manifest.repo, repo_id: "repo-after-demo" }
      }
    } as SnapshotBundle;
    let realCalls = 0;
    let resolveReturn: (() => void) | undefined;
    loadSnapshotMock.mockClear();
    loadSnapshotMock.mockImplementation(async (options) => {
      const loaded = await defaultImplementation!(options);
      if (options?.demo) return loaded;
      realCalls += 1;
      if (realCalls === 1) return { ...loaded, bundle: bundleBeforeDemo };
      return new Promise((resolve) => {
        resolveReturn = () => resolve({ ...loaded, bundle: bundleAfterDemo });
      });
    });

    try {
      await renderRoute("/w?view=radar");
      expect(await screen.findByText(/repo-before-demo/)).toBeTruthy();

      browserApplication.navigation.dispatch({
        type: "navigate",
        target: "/demo/w?view=radar&demo_scenario=normal_operations&tour=0"
      });
      expect(await screen.findByText(/Read-only demo with synthetic data/)).toBeTruthy();

      // The real repository changes while the synthetic universe is open.
      // Returning must read immediately even though the previous real load is
      // much newer than the normal focus throttle.
      browserApplication.navigation.dispatch({ type: "navigate", target: "/w?view=radar" });
      await waitFor(() => expect(resolveReturn).toBeTruthy());
      expect(screen.getByText(/repo-before-demo/)).toBeTruthy();
      expect(screen.queryByText(/Loading world/)).toBeNull();
      window.dispatchEvent(new Event("focus"));
      expect(loadSnapshotMock.mock.calls.filter(([options]) => options?.demo === false)).toHaveLength(2);

      resolveReturn!();
      expect(await screen.findByText(/repo-after-demo/)).toBeTruthy();
      expect(loadSnapshotMock.mock.calls.filter(([options]) => options?.demo === false)).toHaveLength(2);
    } finally {
      loadSnapshotMock.mockImplementation(defaultImplementation!);
    }
  });

  it("keeps old real data but exposes a bounded failed-refresh signal with the last success time", async () => {
    const loadSnapshotMock = vi.mocked(loadSnapshotBundle);
    const defaultImplementation = loadSnapshotMock.getMockImplementation();
    expect(defaultImplementation).toBeTruthy();
    const verifiedAt = Date.parse("2026-07-11T12:00:00Z");
    const now = vi.spyOn(Date, "now").mockReturnValue(verifiedAt);
    const bundleA = {
      ...bundle,
      manifest: {
        ...bundle.manifest,
        snapshot_id: "failure-A",
        bundle_hash: "failure-bundle-A",
        repo: { ...bundle.manifest.repo, repo_id: "failure-fixture-A" }
      }
    } as SnapshotBundle;
    const bundleB = {
      ...bundle,
      manifest: {
        ...bundle.manifest,
        snapshot_id: "failure-B",
        bundle_hash: "failure-bundle-B",
        repo: { ...bundle.manifest.repo, repo_id: "failure-fixture-B" }
      }
    } as SnapshotBundle;
    let realCalls = 0;
    loadSnapshotMock.mockClear();
    loadSnapshotMock.mockImplementation(async (options) => {
      const loaded = await defaultImplementation!(options);
      if (options?.demo) return loaded;
      realCalls += 1;
      if (realCalls === 1) return { ...loaded, bundle: bundleA };
      if (realCalls === 2) throw new Error("bounded synthetic refresh failure");
      return { ...loaded, bundle: bundleB };
    });

    try {
      await renderRoute("/w?view=radar");
      expect(await screen.findByText(/failure-fixture-A/)).toBeTruthy();
      const routeBefore = `${window.location.pathname}${window.location.search}`;

      now.mockReturnValue(verifiedAt + 5_001);
      window.dispatchEvent(new Event("focus"));
      expect(await screen.findByText(/Live snapshot refresh failed/)).toBeTruthy();
      expect(screen.getByText(/Refresh failed · verified 2026-07-11T12:00:00Z/)).toBeTruthy();
      expect(screen.getByText(/failure-fixture-A/)).toBeTruthy();
      expect(`${window.location.pathname}${window.location.search}`).toBe(routeBefore);

      // A later successful focus bounds the warning lifecycle and replaces the
      // retained old data with the now-verified revision.
      now.mockReturnValue(verifiedAt + 10_002);
      window.dispatchEvent(new Event("focus"));
      expect(await screen.findByText(/failure-fixture-B/)).toBeTruthy();
      await waitFor(() => {
        expect(screen.queryByText(/Refresh failed · verified/)).toBeNull();
        expect(screen.queryByText(/Live snapshot refresh failed/)).toBeNull();
      });
    } finally {
      now.mockRestore();
      loadSnapshotMock.mockImplementation(defaultImplementation!);
    }
  });

  it("never installs live focus revalidation inside the synthetic demo universe", async () => {
    const loadSnapshotMock = vi.mocked(loadSnapshotBundle);
    loadSnapshotMock.mockClear();
    await renderRoute("/demo/world?demo_scenario=normal_operations&tour=0");
    expect(
      await screen.findByLabelText("3D knowledge world", {}, { timeout: 3_000 })
    ).toBeTruthy();

    window.dispatchEvent(new Event("focus"));
    document.dispatchEvent(new Event("visibilitychange"));
    await Promise.resolve();

    expect(loadSnapshotMock.mock.calls.filter(([options]) => options?.demo === false)).toHaveLength(0);
    expect(loadSnapshotMock.mock.calls.filter(([options]) => options?.demo === true)).toHaveLength(1);
  });

  it("replace-normalizes a bad reader deep link and leaves mouse and keyboard navigation operable", async () => {
    window.history.pushState({}, "", "/w?view=radar&page=does-not-exist&reader=1");
    const historyLength = window.history.length;
    render(<App ports={browserApplication} />);

    expect(
      await screen.findByLabelText("3D knowledge world", {}, { timeout: 3_000 })
    ).toBeTruthy();
    await waitFor(() => {
      const params = new URLSearchParams(window.location.search);
      expect(params.has("page")).toBe(false);
      expect(params.has("reader")).toBe(false);
    });
    expect(window.history.length).toBe(historyLength);
    expect(screen.queryByRole("dialog", { name: /Reader:/ })).toBeNull();

    const search = screen.getByLabelText("Search content");
    const commandBar = search.closest<HTMLElement>(".worldCommandBar");
    expect(commandBar?.inert).toBe(false);
    const sourcesView = document.querySelector<HTMLButtonElement>('[data-view-option="sources"]');
    expect(sourcesView).toBeTruthy();
    fireEvent.click(sourcesView!);
    await waitFor(() => expect(window.location.search).toContain("view=sources"));
    search.focus();
    expect(document.activeElement).toBe(search);
    fireEvent.change(search, { target: { value: "Root" } });
    fireEvent.keyDown(search, { key: "Enter" });
    await waitFor(() => {
      expect(window.location.search).toContain("page=root");
      expect(window.location.search).toContain("reader=1");
    });
    expect(await screen.findByLabelText("Reader: Root")).toBeTruthy();
  });

  it("recovers mouse and keyboard control when a focused reader page disappears on refresh", async () => {
    const loadSnapshotMock = vi.mocked(loadSnapshotBundle);
    const defaultImplementation = loadSnapshotMock.getMockImplementation();
    expect(defaultImplementation).toBeTruthy();
    const now = vi.spyOn(Date, "now").mockReturnValue(1_000);
    const bundleA = {
      ...bundle,
      manifest: { ...bundle.manifest, snapshot_id: "delete-A", bundle_hash: "delete-bundle-A" }
    } as SnapshotBundle;
    const bundleB = {
      ...bundle,
      manifest: { ...bundle.manifest, snapshot_id: "delete-B", bundle_hash: "delete-bundle-B" },
      pages: { pages: bundle.pages.pages.filter((page) => page.id !== "source-fixture") }
    } as SnapshotBundle;
    let realCalls = 0;
    loadSnapshotMock.mockClear();
    loadSnapshotMock.mockImplementation(async (options) => {
      const loaded = await defaultImplementation!(options);
      if (options?.demo) return loaded;
      realCalls += 1;
      return { ...loaded, bundle: realCalls === 1 ? bundleA : bundleB };
    });

    try {
      await renderRoute("/w?view=radar&page=source-fixture&reader=1");
      const reader = await screen.findByLabelText("Reader: Source Fixture");
      reader.focus();
      expect(document.activeElement).toBe(reader);

      now.mockReturnValue(6_001);
      window.dispatchEvent(new Event("focus"));
      await waitFor(() => {
        const params = new URLSearchParams(window.location.search);
        expect(params.has("page")).toBe(false);
        expect(params.has("reader")).toBe(false);
      });

      // Finish the visual exit deterministically; the same event is emitted by
      // the production CSS animation, with a timeout fallback for hidden tabs.
      const closingReader = document.querySelector<HTMLElement>(".readerSurfacePresence.closing");
      expect(closingReader).toBeTruthy();
      fireEvent.animationEnd(closingReader!);
      await waitFor(() => expect(screen.queryByLabelText("Reader: Source Fixture")).toBeNull());

      const search = screen.getByLabelText("Search content");
      const commandBar = search.closest<HTMLElement>(".worldCommandBar");
      expect(commandBar?.inert).toBe(false);
      const sourcesView = document.querySelector<HTMLButtonElement>('[data-view-option="sources"]');
      expect(sourcesView).toBeTruthy();
      fireEvent.click(sourcesView!);
      await waitFor(() => expect(window.location.search).toContain("view=sources"));
      search.focus();
      expect(document.activeElement).toBe(search);
      fireEvent.change(search, { target: { value: "Root" } });
      fireEvent.keyDown(search, { key: "Enter" });
      expect(await screen.findByLabelText("Reader: Root")).toBeTruthy();
    } finally {
      now.mockRestore();
      loadSnapshotMock.mockImplementation(defaultImplementation!);
    }
  });

  it("aborts a pending real snapshot when navigation crosses into demo", async () => {
    const loadSnapshotMock = vi.mocked(loadSnapshotBundle);
    const defaultImplementation = loadSnapshotMock.getMockImplementation();
    expect(defaultImplementation).toBeTruthy();
    let realSignal: AbortSignal | undefined;
    loadSnapshotMock.mockClear();
    loadSnapshotMock.mockImplementation((options) => {
      if (options?.demo) return defaultImplementation!(options);
      return new Promise((_, reject) => {
        realSignal = options?.signal;
        realSignal?.addEventListener(
          "abort",
          () => reject(new DOMException("aborted", "AbortError")),
          { once: true }
        );
      });
    });

    try {
      await renderRoute("/w/radar");
      await waitFor(() => expect(realSignal).toBeTruthy());
      expect(realSignal!.aborted).toBe(false);

      // A foreign history writer is part of the supported router boundary.
      // The real request must be aborted in the same popstate task, before
      // React commits the demo render and before an operator response wins.
      window.history.pushState({}, "", "/demo/world?tour=0");
      window.dispatchEvent(new PopStateEvent("popstate"));
      expect(realSignal!.aborted).toBe(true);
      expect(await screen.findByText(/Read-only demo with synthetic data/)).toBeTruthy();
      expect(loadSnapshotMock.mock.calls.filter(([options]) => options?.demo === false)).toHaveLength(1);
      expect(loadSnapshotMock.mock.calls.filter(([options]) => options?.demo === true)).toHaveLength(1);
    } finally {
      loadSnapshotMock.mockImplementation(defaultImplementation!);
    }
  });
});
