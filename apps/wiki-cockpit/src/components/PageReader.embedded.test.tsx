// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PageContent, SnapshotBundle } from "../types";
import { PageReader } from "./PageReader";

const bundle = {
  manifest: { snapshot_id: "synthetic-revision", integrity: { "content/item.json": "synthetic-hash" } },
  pages: { pages: [{ id: "item", path: "memories/item.md", title: "Synthetic item", page_type: "context_note",
    context: "example", visibility: "public", status: "", updated_at: "2026-10-05", stale_after_days: "30",
    freshness_state: "fresh", approved_state: "approved", risk_flags: [], source_refs: [], moc_parent: "", summary: "", summary_truncated: false }] },
  graph: { nodes: [], edges: [] }, actions: { actions: [] }, timeline: { events: [] }
} as unknown as SnapshotBundle;
const content: PageContent = { ok: true, body: "# Synthetic item\n\nCanonical synthetic body.", resolved_links: [], backlinks: [], source_refs: [] };
const props = { bundle, pageId: "item", demo: true, snapshotSource: "/sample-snapshot/scenarios/walking_skeleton",
  loadPageContent: vi.fn(async () => content), trail: [], packetIds: [], onNavigatePage: vi.fn(), onClose: vi.fn(), onTogglePacket: vi.fn() };

afterEach(() => { cleanup(); document.body.replaceChildren(); vi.clearAllMocks(); });

describe("inline canonical reader", () => {
  it("shares focus with map/search, while retaining the canonical snapshot-bound loading contract", async () => {
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    render(<PageReader {...props} embedded />);
    await screen.findByText("Canonical synthetic body.");
    const reader = screen.getByRole("complementary");
    expect(reader.getAttribute("aria-modal")).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
    expect(props.loadPageContent).toHaveBeenCalledWith("item", expect.objectContaining({
      demo: true, snapshotSource: props.snapshotSource, snapshotId: bundle.manifest.snapshot_id,
      integrity: bundle.manifest.integrity, signal: expect.any(AbortSignal)
    }));
    opener.remove();
  });

  it("does not wrap Tab at an inline reader boundary", async () => {
    render(<PageReader {...props} embedded />);
    await screen.findByText("Canonical synthetic body.");
    const first = screen.getByTitle("Show this page's template");
    first.focus();
    expect(fireEvent.keyDown(first, { key: "Tab", shiftKey: true })).toBe(true);
    expect(document.activeElement).toBe(first);
  });

  it("becomes a modal only when explicitly expanded, then restores the opener on collapse", async () => {
    render(<PageReader {...props} embedded />);
    await screen.findByText("Canonical synthetic body.");
    const expand = screen.getByRole("button", { name: "Comfortable reading (F)" });
    expand.focus();
    expect(fireEvent.keyDown(expand, { key: "f" })).toBe(false);
    const reader = screen.getByRole("dialog");
    expect(reader.getAttribute("aria-modal")).toBe("true");
    const first = screen.getByTitle("Show this page's template");
    first.focus();
    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Add to packet" }));
    fireEvent.click(screen.getByRole("button", { name: "Back to dock (F)" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(expand));
  });

  it("keeps the existing dialog behavior when the optional inline mode is absent", async () => {
    render(<PageReader {...props} />);
    await screen.findByText("Canonical synthetic body.");
    expect(screen.getByRole("dialog").getAttribute("aria-modal")).toBe("true");
    expect(document.activeElement).toBe(screen.getByRole("dialog"));
  });
});
