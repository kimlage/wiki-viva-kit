// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GateRecord, SnapshotBundle } from "../types";
import { CreateDock } from "./CreateDock";
import { GateChecks } from "./GateChecks";
import { GateDock } from "./GateDock";
import { IntakeDock } from "./IntakeDock";

const gate: GateRecord = {
  id: "wiki_audit",
  status: "not_run",
  argv: ["python3", "scripts/wiki_audit.py", "--check"],
  finished_at: null
};

const createBundle = {
  pages: { pages: [] },
  freshness: { by_context: { demo: { fresh: 0, stale: 0, unknown: 0 } } },
  templates: {
    schema_version: "wiki_templates.v1",
    facets_order: ["intencao", "pratica", "relacoes", "sistemas"],
    types: { person: { creatable: true, pinned_fields: [] } }
  },
  sourceEntities: { sources: [] },
  sources: { sources: [] }
} as unknown as SnapshotBundle;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("read-only demo controls", () => {
  it("disables individual and aggregate gate POST controls", () => {
    const runGate = vi.fn();
    render(
      <GateChecks
        gates={[gate]}
        demo
        runGate={runGate}
        onNotice={vi.fn()}
        onRefetch={vi.fn()}
      />
    );

    const runOne = screen.getByRole("button", { name: /Run Honesty audit.*read-only demo/i });
    const runAll = screen.getByRole("button", { name: /Run checks.*read-only demo/i });
    expect((runOne as HTMLButtonElement).disabled).toBe(true);
    expect((runAll as HTMLButtonElement).disabled).toBe(true);
    expect(runOne.getAttribute("title")).toMatch(/sends nothing/i);
    fireEvent.click(runOne);
    fireEvent.click(runAll);
    expect(runGate).not.toHaveBeenCalled();
  });

  it("disables draft-PR preparation even when the snapshot is otherwise ready", () => {
    const onWorkflow = vi.fn();
    const loadFileDiff = vi.fn();
    const bundle = {
      pages: { pages: [] },
      gates: { status: "not_run", gates: [gate] },
      diff: {
        summary: {
          file_count: 1,
          branch_file_count: 1,
          working_tree_file_count: 0,
          insertions: 2,
          deletions: 0,
          status_counts: { M: 1 },
          privacy_review_required: false
        },
        files: [{
          path: "memories/example.md",
          status: "M",
          category: "memory",
          change_sources: ["branch"],
          additions: 2,
          deletions: 0,
          known_generated: false,
          staged: false,
          unstaged: false,
          risk_hints: [],
          preview: []
        }]
      },
      git: {
        current_branch: "wiki/demo-preview",
        proposal: { draft_pr_url: null, human_gate_state: "not_opened", is_proposal_branch: true }
      }
    } as unknown as SnapshotBundle;

    render(
      <GateDock
        bundle={bundle}
        busy={false}
        demo
        loadFileDiff={loadFileDiff}
        runGate={vi.fn()}
        onWorkflow={onWorkflow}
        onNotice={vi.fn()}
        onRefetch={vi.fn()}
        onClose={vi.fn()}
      />
    );

    const prepare = screen.getByRole("button", { name: /Prepare draft PR.*read-only demo/i });
    expect((prepare as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(prepare);
    expect(onWorkflow).not.toHaveBeenCalled();
    const diff = screen.getByRole("button", { name: /View diff.*read-only demo/i });
    expect((diff as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(diff);
    expect(loadFileDiff).not.toHaveBeenCalled();
  });

  it("keeps intake and Create inspectable while their mutation submits remain inert", () => {
    const intakeCopy = vi.fn();
    const onComposeBrief = vi.fn();
    const intake = render(
      <IntakeDock
        bundle={createBundle}
        demo
        intakeCopy={intakeCopy}
        onComposeBrief={onComposeBrief}
        onNotice={vi.fn()}
        onClose={vi.fn()}
      />
    );
    fireEvent.change(screen.getByPlaceholderText(/statement\.pdf/i), { target: { value: "/tmp/demo.pdf" } });
    const add = screen.getByRole("button", { name: /Add file.*read-only demo/i });
    expect((add as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(add);
    expect(intakeCopy).not.toHaveBeenCalled();
    intake.unmount();

    const { container } = render(
      <CreateDock
        bundle={createBundle}
        demo
        onComposeBrief={onComposeBrief}
        onClose={vi.fn()}
      />
    );
    const title = container.querySelector<HTMLInputElement>(".createForm input");
    expect(title).not.toBeNull();
    fireEvent.change(title!, { target: { value: "Demo person" } });
    const preview = screen.getByRole("button", { name: /Preview only.*read-only demo/i });
    expect((preview as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/never composes a brief, writes a file, or opens a PR/i)).toBeTruthy();
    fireEvent.click(preview);
    expect(onComposeBrief).not.toHaveBeenCalled();
  });
});
