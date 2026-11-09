// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { EffectCallback } from "react";
import type { NavigationIntent, SnapshotLoadResult } from "../application/ports";
import type { PageRecord } from "../types";
import { navigate } from "../router";

// Force a previously rendered effect to run between navigation intent and its
// state commit. This tests the order explicitly; it does not assert the CI
// scheduler actually executed this interleaving.
const focusSchedule = vi.hoisted(() => ({
  previous: null as EffectCallback | null,
  selected: {} as Record<string, EffectCallback>,
}));
vi.mock("react", async importOriginal => {
  const actual = await importOriginal<typeof import("react")>();
  return {
    ...actual,
    useEffect: (effect: EffectCallback, deps?: React.DependencyList) => {
      if (deps?.length === 4 && deps[0] === "" && deps[1] === false && String(effect).includes("detailFocusPending")) {
        focusSchedule.previous = effect;
      }
      if (deps?.length === 4 && typeof deps[0] === "string" && deps[0] && deps[1] === false && deps[3] !== null && String(effect).includes("detailFocusPending")) {
        focusSchedule.selected[deps[0]] ||= effect;
      }
      return actual.useEffect(effect, deps);
    },
  };
});
import { ActionBoard } from "./ActionBoard";

afterEach(() => {
  cleanup(); focusSchedule.previous = null; focusSchedule.selected = {};
  window.history.replaceState(null, "", "/"); vi.unstubAllGlobals();
});

it("does not consume a later visit to the same action with an old effect", async () => {
  window.history.replaceState(null, "", "/board");
  const pages = ["first", "second"].map(id => ({ id, title: `Synthetic ${id}`, path: `memories/${id}.md`, page_type: "action", context: "example", content_sha256: "a".repeat(64), work: { state: "open", priority: "normal", next_action: "Read evidence" } } as unknown as PageRecord));
  let finishRead!: (value: { ok: boolean; body: string; frontmatter: object }) => void;
  const pendingRead = new Promise<{ ok: boolean; body: string; frontmatter: object }>(resolve => { finishRead = resolve; });
  const operator = {
    loadSnapshotBundle: vi.fn().mockResolvedValue({ source: "/api/snapshot", runtime: { mode: "local_operator" }, bundle: { manifest: { repo: { language: "en" }, snapshot_id: "synthetic" }, pages: { pages }, git: { current_branch: "wiki/test" } } } as SnapshotLoadResult),
    loadPageContent: vi.fn().mockResolvedValueOnce({ ok: true, body: "First", frontmatter: {} }).mockResolvedValueOnce({ ok: true, body: "Second", frontmatter: {} }).mockReturnValueOnce(pendingRead),
  };
  let forcePrevious = false;
  const navigation = { dispatch: vi.fn((intent: NavigationIntent) => {
    if (forcePrevious) {
      expect(focusSchedule.selected.first).toBeTypeOf("function");
      focusSchedule.selected.first();
    }
    if (intent.type === "navigate") navigate(intent.target);
  }) };
  render(<ActionBoard operator={operator} navigation={navigation} save={vi.fn()} />);
  const first = await screen.findByRole("button", { name: /Synthetic first/ });
  const second = screen.getByRole("button", { name: /Synthetic second/ });
  fireEvent.click(first);
  await waitFor(() => expect(screen.getByRole("complementary").getAttribute("data-read-state")).toBe("ready"));
  fireEvent.click(second);
  await waitFor(() => expect(screen.getByRole("complementary").getAttribute("data-page-id")).toBe("second"));
  await waitFor(() => expect(screen.getByRole("complementary").getAttribute("data-read-state")).toBe("ready"));
  first.focus();
  forcePrevious = true;
  fireEvent.click(first);
  const panel = await screen.findByRole("complementary");
  expect(panel.getAttribute("data-read-state")).toBe("loading");
  expect(document.activeElement).toBe(first);
  await act(async () => finishRead({ ok: true, body: "New first", frontmatter: {} }));
  await waitFor(() => expect(document.activeElement).toBe(panel));
});

it("does not let a previous close effect consume a later selection's focus intent", async () => {
  window.history.replaceState(null, "", "/board");
  vi.stubGlobal("matchMedia", () => ({ matches: true }));
  const page = { id: "synthetic", title: "Synthetic action", path: "memories/synthetic.md", page_type: "action", context: "example", content_sha256: "a".repeat(64), work: { state: "open", priority: "normal", next_action: "Read evidence" } } as unknown as PageRecord;
  const operator = {
    loadSnapshotBundle: vi.fn().mockResolvedValue({ source: "/api/snapshot", runtime: { mode: "local_operator" }, bundle: { manifest: { repo: { language: "en" }, snapshot_id: "synthetic" }, pages: { pages: [page] }, git: { current_branch: "wiki/test" } } } as SnapshotLoadResult),
    loadPageContent: vi.fn().mockResolvedValue({ ok: true, body: "Synthetic evidence", frontmatter: {} }),
  };
  const navigation = { dispatch: vi.fn((intent: NavigationIntent) => {
    expect(focusSchedule.previous).toBeTypeOf("function");
    // Run the prior unselected render's actual focus effect before the new
    // selection commits. It must not consume the new selection's intent.
    focusSchedule.previous!();
    if (intent.type === "navigate") navigate(intent.target);
  }) };
  render(<ActionBoard operator={operator} navigation={navigation} save={vi.fn()} />);
  const card = await screen.findByRole("button", { name: /Synthetic action/ });
  fireEvent.click(card);
  const panel = await screen.findByRole("complementary", { name: "Page and evidence" });
  await waitFor(() => expect(document.activeElement).toBe(panel));
});
