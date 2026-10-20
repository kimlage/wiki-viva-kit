// @vitest-environment jsdom
// Operator callbacks are mocked. No HTTP/source/account/executor is invoked.
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { configureLanguage } from "../data/i18n";
import type { IngestionPlan, SnapshotBundle } from "../types";
import { IntakeDock } from "./IntakeDock";

const bundle = { freshness: { by_context: { example: {}, other: {} } } } as unknown as SnapshotBundle;
const plan: IngestionPlan = { ok: true, source: "notes/event.md", context: "example", triage: { ok: true }, stages: [], action_preview: { status: "reuse", reason: "explicit_revision_bound_action", execution_ready: false, writes: false,
  task_ref: { repo_id: "fictional", action_id: "same-fictional-action" }, owner_ref: "fictional-owner", coordinator: "research",
    blockers: ["waiting_human"], source_checks: { corporate: "unknown", tasks: "unknown" } } };
beforeEach(() => configureLanguage("en")); afterEach(cleanup);

it("renders a read-only linked-action plan without copying or dispatching", async () => {
  const copy = vi.fn(); const preview = vi.fn().mockResolvedValue(plan);
  render(<IntakeDock bundle={bundle} initialSrc="notes/event.md" intakeCopy={copy} buildIngestionPlan={preview} onNotice={vi.fn()} onClose={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Preview linked action" }));
  await waitFor(() => expect(screen.getByText("same-fictional-action")).toBeTruthy());
  expect(preview).toHaveBeenCalledWith("notes/event.md", "example");
  expect(copy).not.toHaveBeenCalled();
  expect(screen.getByText("waiting_human")).toBeTruthy();
  expect(screen.getByText("corporate: Unknown")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /execute|grant|dispatch/i })).toBeNull();
});

it("discards a late result after the source/account context selection changes", async () => {
  let finish: (value: IngestionPlan) => void = () => {};
  const preview = vi.fn().mockReturnValue(new Promise<IngestionPlan>((resolve) => { finish = resolve; }));
  render(<IntakeDock bundle={bundle} initialSrc="notes/event.md" intakeCopy={vi.fn()} buildIngestionPlan={preview} onNotice={vi.fn()} onClose={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Preview linked action" }));
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "other" } });
  await act(async () => { finish(plan); });
  expect(screen.queryByText("same-fictional-action")).toBeNull();
});
