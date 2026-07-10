// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PageContent, SnapshotBundle } from "../types";

const contentByCase: { current: PageContent } = {
  current: { ok: false, error: "sem conteúdo" }
};

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
  loadPageContent: vi.fn(async () => contentByCase.current),
  onNavigatePage: vi.fn(),
  onClose: vi.fn(),
  onTogglePacket: vi.fn()
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PageReader", () => {
  it("keeps one page title when the Markdown starts with the same H1", async () => {
    contentByCase.current = {
      ok: true,
      body: "# alpha\n\nThe useful summary starts here.",
      resolved_links: [],
      backlinks: [],
      source_refs: []
    };
    const { container } = render(<PageReader {...baseProps} pageId="alpha" />);

    await screen.findByText("The useful summary starts here.");
    expect(screen.getAllByRole("heading", { name: "alpha" })).toHaveLength(1);
    expect(container.querySelector(".readerBody h1")).toBeNull();
    expect(screen.getByRole("dialog").getAttribute("aria-modal")).toBe("true");
    expect(screen.getByRole("button", { name: "Comfortable reading (F)" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Close reader (Esc)" })).toBeTruthy();
  });

  it("puts compiled action state and next action before prose and omits empty relation groups", async () => {
    contentByCase.current = {
      ok: true,
      body: "# Human decision\n\nSupporting prose.",
      resolved_links: [],
      backlinks: [],
      source_refs: []
    };
    const actionPage = page("human-decision", {
      title: "Human decision",
      page_type: "action",
      source_refs: []
    });
    const actionBundle = {
      ...bundle,
      actions: {
        actions: [{
          id: "graph-check",
          kind: "command",
          title: "Connections",
          human_reason: "Inspect links",
          risk_level: "read",
          default_dry_run: true,
          commands: []
        }]
      },
      pages: { pages: [actionPage] },
      workItems: {
        schema_version: "wiki_web_work_items.v1",
        actions: [{
          action_id: "human-decision",
          page_id: "human-decision",
          state: "waiting_human",
          due_at: "2026-06-15",
          overdue: true,
          next_action: "Review the evidence and leave a receipt.",
          owner: { kind: "human", ref: "reviewer" },
          priority: "high",
          evidence_refs: ["artifact-1"]
        }]
      }
    } as unknown as SnapshotBundle;
    const { container } = render(
      <PageReader {...baseProps} bundle={actionBundle} pageId="human-decision" onRunOperatorCommand={vi.fn()} />
    );

    await screen.findByText("Supporting prose.");
    expect(screen.getByText("Waiting for human")).toBeTruthy();
    expect(screen.getByText("Overdue action")).toBeTruthy();
    expect(screen.getByText("Review the evidence and leave a receipt.")).toBeTruthy();
    expect(screen.getByText("reviewer")).toBeTruthy();
    expect(screen.getByText("High")).toBeTruthy();
    const summary = container.querySelector(".actionSummaryPanel");
    const body = container.querySelector(".readerBody");
    expect(summary).toBeTruthy();
    expect(body).toBeTruthy();
    expect(summary!.compareDocumentPosition(body!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(container.querySelector(".readerRelations")).toBeNull();
    expect(container.querySelector(".readerActionBar")).toBeTruthy();

    const dock = container.querySelector<HTMLElement>(".pageReader")!;
    const firstControl = container.querySelector<HTMLElement>(".readerTypeChip")!;
    const more = screen.getByText("More").closest("summary") as HTMLElement;
    firstControl.focus();
    fireEvent.keyDown(dock, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(more);
    fireEvent.keyDown(dock, { key: "Tab" });
    expect(document.activeElement).toBe(firstControl);
  });

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

  it("shows populated typed relations with true counts and omits empty groups", async () => {
    contentByCase.current = { ok: true, body: "corpo", resolved_links: [], backlinks: [], source_refs: [] };
    render(<PageReader {...baseProps} pageId="alpha" />);
    await screen.findByText("Hierarchy");
    expect(screen.queryByText("Evidence")).toBeNull();
    expect(screen.queryByText("Cited by")).toBeNull();
    // beta has moc_parent = alpha → shows under Hierarquia as "abaixo".
    expect(screen.getByRole("button", { name: /beta/ })).toBeTruthy();
  });

  it("renders collection membership as structure in both directions without cited-by duplication", async () => {
    const collectionBundle = {
      ...bundle,
      pages: {
        pages: [
          page("claims-index", { title: "Claims collection", page_type: "ontology_index" }),
          page("claim-a", { title: "Claim A", page_type: "claim" })
        ]
      },
      graph: {
        nodes: [],
        edges: [
          { source: "claim-a", target: "claims-index", type: "collection_member", status: "valid", weight: 1 }
        ]
      }
    } as unknown as SnapshotBundle;
    contentByCase.current = {
      ok: true,
      body: "Collection body",
      resolved_links: [],
      backlinks: [{
        page_id: "claim-a",
        path: "memories/x/claim-a.md",
        title: "Claim A",
        context: "x",
        page_type: "claim",
        freshness_state: "fresh",
        approved_state: "approved",
        relation: "collection_member"
      }],
      source_refs: []
    };
    const first = render(
      <PageReader {...baseProps} bundle={collectionBundle} pageId="claims-index" />
    );

    await screen.findByText(/member of this collection/);
    expect(screen.getAllByRole("button", { name: /Claim A/ })).toHaveLength(1);
    expect(screen.queryByText("Cited by")).toBeNull();
    first.unmount();

    contentByCase.current = {
      ok: true,
      body: "Member body",
      resolved_links: [],
      backlinks: [],
      source_refs: []
    };
    render(<PageReader {...baseProps} bundle={collectionBundle} pageId="claim-a" />);

    await screen.findByText(/in collection/);
    expect(screen.getAllByRole("button", { name: /Claims collection/ })).toHaveLength(1);
    expect(screen.queryByText("Cited by")).toBeNull();
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
