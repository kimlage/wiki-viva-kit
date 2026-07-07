// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PageContent, SnapshotBundle } from "../types";

const contentByCase: { current: PageContent } = {
  current: { ok: false, error: "sem conteúdo" }
};

vi.mock("../data/snapshot", () => ({
  loadPageContent: vi.fn(async () => contentByCase.current),
  sidecarName: (id: string) => `${id}.json`
}));

import { PageReader } from "./PageReader";

function page(id: string, over: Record<string, unknown> = {}) {
  return {
    id,
    path: `memories/x/${id}.md`,
    title: id,
    page_type: "context_note",
    context: "x",
    visibility: "private_self",
    status: "",
    updated_at: "2026-07-01",
    stale_after_days: "30",
    freshness_state: "fresh" as const,
    approved_state: "approved",
    risk_flags: [],
    source_refs: [],
    moc_parent: "",
    summary: "resumo",
    summary_truncated: false,
    ...over
  };
}

const bundle = {
  pages: { pages: [page("alpha"), page("beta", { moc_parent: "memories/x/alpha.md" })] },
  graph: { nodes: [], edges: [] },
  actions: { actions: [] },
  timeline: { events: [], bands: {}, summary: { event_count: 0, first_at: "", last_at: "", by_kind: {}, by_context: {} }, schema_version: "", repo_id: "", generated_at: "" }
} as unknown as SnapshotBundle;

const baseProps = {
  bundle,
  demo: false,
  trail: [],
  packetIds: [] as string[],
  onNavigatePage: vi.fn(),
  onClose: vi.fn(),
  onTogglePacket: vi.fn()
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PageReader", () => {
  it("sanitizes hostile markdown: scripts and event handlers never reach the DOM", async () => {
    contentByCase.current = {
      ok: true,
      body: [
        "# Alpha",
        "",
        '<script>window.__pwned = true;</script>',
        '<img src="x" onerror="window.__pwned2 = true;">',
        "Texto <b>seguro</b> com [link](beta.md).",
        '<a href="javascript:alert(1)">mal</a>'
      ].join("\n"),
      resolved_links: [
        {
          kind: "page",
          text: "link",
          href: "beta.md",
          page_id: "beta",
          path: "memories/x/beta.md",
          title: "beta",
          context: "x",
          page_type: "context_note",
          freshness_state: "fresh",
          approved_state: "approved"
        }
      ],
      backlinks: [],
      source_refs: []
    };
    const { container } = render(<PageReader {...baseProps} pageId="alpha" />);
    await waitFor(() => expect(container.querySelector(".readerBody")).toBeTruthy());
    expect(container.querySelector("script")).toBeNull();
    expect(container.innerHTML).not.toContain("onerror");
    expect(container.innerHTML).not.toContain("javascript:alert");
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
    expect(screen.getByText("seguro")).toBeTruthy();
  });

  it("navigates the world through wiki-links instead of leaving the app", async () => {
    contentByCase.current = {
      ok: true,
      body: "Veja [beta](beta.md).",
      resolved_links: [
        {
          kind: "page",
          text: "beta",
          href: "beta.md",
          page_id: "beta",
          path: "memories/x/beta.md",
          title: "beta",
          context: "x",
          page_type: "context_note",
          freshness_state: "fresh",
          approved_state: "approved"
        }
      ],
      backlinks: [],
      source_refs: []
    };
    const { container } = render(<PageReader {...baseProps} pageId="alpha" />);
    await waitFor(() => expect(container.querySelector("a.readerWikiLink")).toBeTruthy());
    fireEvent.click(container.querySelector("a.readerWikiLink")!);
    expect(baseProps.onNavigatePage).toHaveBeenCalledWith("beta");
  });

  it("degrades honestly when content is unavailable: summary + operator notice, no dead end", async () => {
    contentByCase.current = { ok: false, error: "404" };
    render(
      <PageReader
        {...baseProps}
        pageId="alpha"
        bundle={{
          ...bundle,
          pages: { pages: [page("alpha", { summary: "resumo parcial da página", summary_truncated: true })] }
        } as unknown as SnapshotBundle}
      />
    );
    expect(await screen.findByText(/resumo parcial da página/)).toBeTruthy();
    expect(screen.getByText("partial summary")).toBeTruthy();
    expect(screen.getByText(/full text available with the local operator/)).toBeTruthy();
  });

  it("shows grouped typed relations with true counts (Hierarchy counts the child)", async () => {
    contentByCase.current = { ok: true, body: "corpo", resolved_links: [], backlinks: [], source_refs: [] };
    render(<PageReader {...baseProps} pageId="alpha" />);
    await screen.findByText("Hierarchy");
    expect(screen.getByText("Evidence")).toBeTruthy();
    expect(screen.getByText("Cited by")).toBeTruthy();
    // beta has moc_parent = alpha → shows under Hierarquia as "abaixo".
    expect(screen.getByRole("button", { name: /beta/ })).toBeTruthy();
  });

  it("shows quadrant projection details for the active center", async () => {
    contentByCase.current = { ok: false, error: "static" };
    const projectionBundle = {
      ...bundle,
      blockStacks: {
        schema_version: "wiki_web_block_stacks.v1",
        anchor_tree: { roots: ["root"], nodes: { root: { id: "root", path: "memories/index.md", title: "Root", page_type: "root_entity", parent: "", children: [] } } },
        anchors: {
          root: {
            stack: [],
            interface: {},
            identity: {},
            derived: {
              missions: [],
              warnings: [],
              quadrant_projections: {
                alpha: [
                  {
                    center: "root",
                    page: "alpha",
                    quadrant: "q4",
                    facet: "sistemas",
                    sub_lens: "governanca",
                    basis: "nested_center_projection",
                    subject_center: "company",
                    through_center: "company",
                    local_quadrant_under_subject: "q1",
                    local_facet_under_subject: "intencao",
                    local_sub_lens_under_subject: "percepcao",
                    reason: "company system"
                  }
                ]
              }
            }
          }
        }
      }
    } as unknown as SnapshotBundle;

    render(<PageReader {...baseProps} bundle={projectionBundle} pageId="alpha" activeCenterId="root" />);

    expect(await screen.findByText("Quadrant projection")).toBeTruthy();
    expect(screen.getByText("Root")).toBeTruthy();
    expect(screen.getByText("q4 · governanca")).toBeTruthy();
    expect(screen.getByText("q1 · percepcao")).toBeTruthy();
    expect(screen.getByText(/nested_center_projection/)).toBeTruthy();
  });
});
