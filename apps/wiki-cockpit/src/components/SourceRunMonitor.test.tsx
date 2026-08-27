// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { configureLanguage } from "../data/i18n";
import type { CodexJobRecord } from "../types";
import { SourceRunMonitor } from "./SourceRunMonitor";

const sourceJob: CodexJobRecord = {
  job_id: "job-source-1",
  brief_id: "brief-1",
  brief_sha: "sha-1",
  parent_job_id: null,
  status: "running",
  agent: "claude",
  theme: "ingest-source-gmail",
  steps: [
    { id: "extract", label: "Extract", status: "done" },
    { id: "integrate", label: "Integrate", status: "running" }
  ],
  branch: null,
  draft_pr_url: null
};

afterEach(() => {
  cleanup();
  configureLanguage("en");
});

describe("SourceRunMonitor", () => {
  it("shows only the selected source run and exposes its safe live log", async () => {
    const onListJobs = vi.fn(async () => [
      sourceJob,
      { ...sourceJob, job_id: "job-other", theme: "ingest-source-drive" }
    ]);
    const onStreamJobLog = vi.fn(async () => "safe deterministic tail");
    const onCancelJob = vi.fn(async () => ({ ...sourceJob, status: "cancelled" }));

    render(
      <SourceRunMonitor
        sourceId="source-gmail"
        demo={false}
        onListJobs={onListJobs}
        onStreamJobLog={onStreamJobLog}
        onCancelJob={onCancelJob}
      />
    );

    expect(await screen.findByText("job-source-1")).toBeTruthy();
    expect(screen.queryByText("job-other")).toBeNull();
    expect(screen.getByText("claude")).toBeTruthy();
    expect(screen.getByText("Extract").getAttribute("data-status")).toBe("done");

    fireEvent.click(screen.getByRole("button", { name: "Show live log" }));
    expect(await screen.findByText("safe deterministic tail")).toBeTruthy();
    expect(onStreamJobLog).toHaveBeenCalledWith("job-source-1", expect.any(Object));

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(onCancelJob).toHaveBeenCalledWith("job-source-1"));
  });

  it("keeps the empty state honest when no run exists", async () => {
    render(
      <SourceRunMonitor
        sourceId="source-gmail"
        demo={false}
        onListJobs={async () => []}
      />
    );
    expect(await screen.findByText(/No agent run has been recorded/)).toBeTruthy();
    expect(screen.getByText("no active run")).toBeTruthy();
  });
});
