// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { NavigationIntent, SnapshotLoadResult } from "../application/ports";
import type { PageRecord } from "../types";
import { navigate } from "../router";
import { ActionBoard } from "./ActionBoard";

const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");
afterEach(() => {
  cleanup(); window.history.replaceState(null, "", "/"); vi.unstubAllGlobals();
  if (originalScroll) Object.defineProperty(HTMLElement.prototype, "scrollIntoView", originalScroll);
  else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
});
const pages = ["first", "second"].map(id => ({ id, title: `Task ${id}`, path: `memories/${id}.md`, page_type: "action", context: "research", content_sha256: "a".repeat(64), work: { state: "open", priority: "normal", next_action: "Read evidence" } } as unknown as PageRecord));
function setup() {
  const operator = { loadSnapshotBundle: vi.fn().mockResolvedValue({ source: "/api/snapshot", runtime: { mode: "local_operator" }, bundle: { manifest: { repo: { language: "en" }, snapshot_id: "snapshot-a" }, pages: { pages }, git: { current_branch: "wiki/test" } } } as SnapshotLoadResult), loadPageContent: vi.fn().mockResolvedValue({ ok: true, body: "Evidence", frontmatter: {} }) };
  const navigation = { dispatch: vi.fn((intent: NavigationIntent) => { if (intent.type === "navigate") navigate(intent.target); }) };
  const save = vi.fn();
  return { operator, navigation, save };
}

it("brings a selected low card into view on narrow screens, persists selection and returns focus on close", async () => {
  window.history.replaceState(null, "", "/board");
  vi.stubGlobal("matchMedia", () => ({ matches: true }));
  const scroll = vi.fn(); Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scroll });
  const props = setup(); render(<ActionBoard {...props} />);
  const card = await screen.findByRole("button", { name: /Task second/ });
  fireEvent.click(card);
  const panel = await screen.findByRole("complementary", { name: "Page and evidence" });
  expect(document.activeElement).toBe(panel);
  expect(scroll).toHaveBeenCalledWith({ block: "start" });
  expect(window.location.search).toBe("?action=second");
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(window.location.search).toBe("");
  expect(document.activeElement).toBe(card);
  expect(props.save).not.toHaveBeenCalled();
});

it("restores selection on reload and browser back without writing or losing the fronts view", async () => {
  window.history.replaceState(null, "", "/board?view=fronts&action=first");
  const props = setup(); const view = render(<ActionBoard {...props} />);
  expect((await screen.findByRole("complementary", { name: "Page and evidence" })).getAttribute("data-page-id")).toBe("first");
  expect(screen.getByText(/Front projection unavailable/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(window.location.search).toBe("?view=fronts");
  act(() => window.history.back());
  await waitFor(() => expect(screen.getByRole("complementary", { name: "Page and evidence" }).getAttribute("data-page-id")).toBe("first"));
  view.unmount(); render(<ActionBoard {...props} />);
  expect((await screen.findByRole("complementary", { name: "Page and evidence" })).getAttribute("data-page-id")).toBe("first");
  expect(screen.queryByRole("region", { name: "Kanban" })).toBeNull();
  expect(props.save).not.toHaveBeenCalled();
});
