// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BriefRecord, CodexCapability, CodexJobRecord } from "../types";

const { data, cancelCodexJob, discardBrief } = vi.hoisted(() => ({
  data: { jobs: [] as unknown[], briefs: [] as unknown[] },
  cancelCodexJob: vi.fn(async () => null),
  discardBrief: vi.fn(async () => ({}))
}));

vi.mock("../data/snapshot", () => ({
  listCodexJobs: vi.fn(async () => data.jobs),
  listBriefs: vi.fn(async () => data.briefs),
  streamCodexLog: vi.fn(async () => "line 1\nline 2\n"),
  cancelCodexJob,
  discardBrief
}));

import { WorkTray } from "./WorkTray";

const cap: CodexCapability = {
  enabled: true,
  installed: true,
  runnable: true,
  authed: true,
  auth_mode: "chatgpt",
  version: "1",
  usable: true,
  reason: ""
};

function noop() {
  /* no-op */
}

const job = (over: Partial<CodexJobRecord> = {}): CodexJobRecord => ({
  job_id: "j1",
  brief_id: "b1",
  brief_sha: "sha",
  parent_job_id: null,
  theme: "fix-root",
  status: "delivered",
  steps: [
    { id: "ground", label: "Ground", status: "complete" },
    { id: "codex", label: "Run Codex", status: "complete" }
  ],
  branch: "wiki/fix-root",
  draft_pr_url: "https://github.com/x/y/pull/9",
  ...over
});

afterEach(() => {
  cleanup();
  data.jobs = [];
  data.briefs = [];
  vi.clearAllMocks();
});

describe("WorkTray", () => {
  it("shows the honest demo state without hitting the operator", () => {
    render(<WorkTray capability={cap} demo onResumeBrief={noop} onNotice={noop} onClose={noop} />);
    expect(screen.getByText(/demo/i)).toBeTruthy();
  });

  it("renders a job row with its status, steps and draft-PR link", async () => {
    data.jobs = [job()];
    render(<WorkTray capability={cap} demo={false} onResumeBrief={noop} onNotice={noop} onClose={noop} />);
    await waitFor(() => expect(screen.getByText("fix-root")).toBeTruthy());
    expect(screen.getByText("delivered")).toBeTruthy();
    expect(screen.getByText("Run Codex")).toBeTruthy();
    const link = screen.getByRole("link", { name: /Open draft PR/ }) as HTMLAnchorElement;
    expect(link.href).toContain("/pull/9");
  });

  it("offers Cancel only on active jobs and calls the API", async () => {
    data.jobs = [job({ job_id: "j2", status: "running", draft_pr_url: null })];
    render(<WorkTray capability={cap} demo={false} onResumeBrief={noop} onNotice={noop} onClose={noop} />);
    await waitFor(() => expect(screen.getByText("running")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Cancel/ }));
    expect(cancelCodexJob).toHaveBeenCalledWith("j2");
  });

  it("resumes a saved draft brief", async () => {
    data.briefs = [
      {
        brief_id: "b9",
        status: "draft",
        spec: { theme: "top-problems", grounding: {}, intent: "triage" },
        brief_sha: "s",
        size_chars: 1,
        snapshot_generated_at: "2026-07-01",
        target_paths: [],
        context_pages: [],
        job_id: null,
        text: ""
      }
    ];
    const onResumeBrief = vi.fn();
    render(<WorkTray capability={cap} demo={false} onResumeBrief={onResumeBrief} onNotice={noop} onClose={noop} />);
    await waitFor(() => expect(screen.getByText("top-problems")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /^Open$/ }));
    expect(onResumeBrief).toHaveBeenCalledWith("b9");
  });

  it("surfaces an honest unavailable pill when Codex cannot run", async () => {
    render(
      <WorkTray capability={{ ...cap, usable: false }} demo={false} onResumeBrief={noop} onNotice={noop} onClose={noop} />
    );
    await waitFor(() => expect(screen.getByText(/no jobs can run/i)).toBeTruthy());
  });
});
