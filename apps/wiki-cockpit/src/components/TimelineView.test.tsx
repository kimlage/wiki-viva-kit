// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { configureLanguage, t } from "../data/i18n";
import type { PageRecord, TemporalEvent, TemporalGraphPayload } from "../types";
import { TimelineView } from "./TimelineView";

function temporalEvent(overrides: Partial<TemporalEvent>): TemporalEvent {
  return {
    schema_version: "wiki_temporal_event.v1",
    event_id: "evt-page",
    kind: "page_updated",
    subject_refs: ["page:page-one"],
    context_refs: ["context:study"],
    occurred_at: "2026-07-10T12:00:00Z",
    recorded_at: "2026-07-11T12:00:00Z",
    valid_from: null,
    valid_to: null,
    created_at: null,
    due_at: null,
    completed_at: null,
    verified_at: null,
    ingested_at: null,
    superseded_at: null,
    precision: { occurred_at: "instant", recorded_at: "instant" },
    actor: null,
    source_refs: [],
    evidence_refs: [],
    caused_by: [],
    supersedes: [],
    before: {},
    after: {},
    confidence: "confirmed",
    visibility: "public",
    origin: { adapter: "page" },
    temporal_conflicts: [],
    anchor: { field: "occurred_at", value: "2026-07-10T12:00:00Z", precision: "instant" },
    ...overrides
  };
}

const events = [
  temporalEvent({}),
  temporalEvent({
    event_id: "evt-action",
    kind: "action_state_changed",
    subject_refs: ["page:action-one"],
    occurred_at: "2026-07",
    recorded_at: "2026-07-09",
    precision: { occurred_at: "month", recorded_at: "day" },
    before: { state: "open" },
    after: { state: "completed" },
    anchor: { field: "occurred_at", value: "2026-07", precision: "month" }
  }),
  temporalEvent({
    event_id: "evt-undated",
    kind: "receipt_recorded",
    subject_refs: ["page:receipt-one"],
    occurred_at: null,
    recorded_at: null,
    precision: {},
    confidence: "uncertain",
    anchor: null
  })
];

function payload(overrides: Partial<TemporalGraphPayload> = {}): TemporalGraphPayload {
  return {
    schema_version: "wiki_temporal_graph.v1",
    event_schema_version: "wiki_temporal_event.v1",
    repo_id: "fixture",
    revision: "abc123",
    generated_at: "2026-07-11T15:00:00Z",
    event_count: 3,
    total_count: 3,
    returned_count: 3,
    truncated: false,
    next_cursor: null,
    page: { offset: 0, limit: 3, remaining_count: 0, fingerprint: "fixture" },
    range: { from: "2026-07", to: "2026-07-10T12:00:00Z", from_precision: "month", to_precision: "instant", event_count: 3, dated_count: 2, undated_count: 1, basis: "full_result" },
    returned_range: { from: "2026-07", to: "2026-07-10T12:00:00Z", from_precision: "month", to_precision: "instant", event_count: 3, dated_count: 2, undated_count: 1, basis: "returned_page" },
    summary: { scope: "full_result", event_count: 3, by_kind: {}, by_context: {}, conflict_count: 0, imprecise_count: 1, diagnostic_count: 0 },
    diagnostics: [],
    events,
    ...overrides
  };
}

const pages: PageRecord[] = [
  {
    id: "page-one", path: "memories/page-one.md", title: "Research note", page_type: "note", context: "study",
    visibility: "public", status: "", updated_at: "2026-07-10", stale_after_days: "30", freshness_state: "fresh",
    approved_state: "approved", risk_flags: [], source_refs: [], moc_parent: "", summary: ""
  },
  {
    id: "action-one", path: "memories/action-one.md", title: "Review evidence", page_type: "action", context: "study",
    visibility: "public", status: "", updated_at: "2026-07-10", stale_after_days: "30", freshness_state: "fresh",
    approved_state: "approved", risk_flags: [], source_refs: [], moc_parent: "", summary: ""
  }
];

const query = {
  timeFrom: "",
  timeTo: "",
  timeCursor: "",
  timeMode: "" as const,
  timeLanes: [] as string[],
  compareRevision: ""
};

afterEach(() => {
  cleanup();
  configureLanguage("en");
});

describe("TimelineView", () => {
  it("renders the complete static graph and keeps imprecise or missing time explicit", () => {
    configureLanguage("en");
    render(<TimelineView payload={payload()} pages={pages} query={query} onQueryChange={vi.fn()} onOpenPage={vi.fn()} />);

    expect(screen.getByRole("heading", { name: t("timeline.title") })).toBeTruthy();
    expect(screen.getAllByText("Research note").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Review evidence").length).toBeGreaterThan(0);
    expect(screen.getAllByText(t("timeline.time.missing")).length).toBeGreaterThan(0);
    expect(screen.getByText(/month precision/i)).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText(t("timeline.results.count", { shown: 3, filtered: 3, total: 3 }))).toBeTruthy();
  });

  it("writes recorded-time and lane selection through the canonical route callback", () => {
    const onQueryChange = vi.fn();
    render(<TimelineView payload={payload()} pages={pages} query={query} onQueryChange={onQueryChange} onOpenPage={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: t("timeline.mode.recorded") }));
    fireEvent.click(screen.getByRole("button", { name: new RegExp(t("timeline.lane.action")) }));
    expect(onQueryChange).toHaveBeenNthCalledWith(1, { timeMode: "recorded", timeCursor: null });
    expect(onQueryChange).toHaveBeenNthCalledWith(2, { timeLanes: ["action"], timeCursor: null });
  });

  it("filters by an honest date range and does not place undated events inside it", () => {
    render(<TimelineView
      payload={payload()}
      pages={pages}
      query={{ ...query, timeFrom: "2026-07-10", timeTo: "2026-07-10" }}
      onQueryChange={vi.fn()}
      onOpenPage={vi.fn()}
    />);
    expect(screen.getAllByText("Research note").length).toBeGreaterThan(0);
    expect(screen.queryByText(t("timeline.kind.receipt_recorded"))).toBeNull();
    // Month-precision July honestly overlaps July 10; the undated receipt does
    // not. The surface includes the imprecise event instead of fabricating a
    // day outside the requested window.
    expect(screen.getByText(t("timeline.results.count", { shown: 2, filtered: 2, total: 3 }))).toBeTruthy();
  });

  it("shares event selection, exposes before/after and opens the canonical page", () => {
    const onQueryChange = vi.fn();
    const onOpenPage = vi.fn();
    render(<TimelineView
      payload={payload()}
      pages={pages}
      query={{ ...query, timeCursor: "evt-action" }}
      onQueryChange={onQueryChange}
      onOpenPage={onOpenPage}
    />);
    expect(screen.getByText(t("timeline.state.before"))).toBeTruthy();
    expect(screen.getByText(t("timeline.state.after"))).toBeTruthy();
    expect(screen.getByText("completed")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: t("timeline.openPage") }));
    expect(onOpenPage).toHaveBeenCalledWith("action-one");
    fireEvent.click(screen.getByRole("button", { name: /Research note/ }));
    expect(onQueryChange).toHaveBeenCalledWith({ timeCursor: "evt-page" });
  });

  it("announces a declared partial page instead of presenting it as complete", () => {
    render(<TimelineView
      payload={payload({ returned_count: 2, truncated: true, next_cursor: "cursor-2", events: events.slice(0, 2) })}
      pages={pages}
      query={query}
      onQueryChange={vi.fn()}
      onOpenPage={vi.fn()}
    />);
    expect(screen.getByRole("alert").textContent).toContain("2 of 3");
    expect(screen.getByLabelText("2 loaded of 3 total events").textContent).toBe("2/3");
  });

  it("exposes rejected adapter events with safe diagnostic evidence", () => {
    render(<TimelineView
      payload={payload({
        summary: { scope: "full_result", event_count: 3, by_kind: {}, by_context: {}, conflict_count: 0, imprecise_count: 1, diagnostic_count: 1 },
        diagnostics: [{
          code: "temporal_adapter_rejected",
          adapter: "action_transition_receipt.v1",
          subject_ref: "page:action-one",
          error_codes: ["transition_receipt_has_noncanonical_state"]
        }]
      })}
      pages={pages}
      query={query}
      onQueryChange={vi.fn()}
      onOpenPage={vi.fn()}
    />);
    expect(screen.getByText("temporal_adapter_rejected")).toBeTruthy();
    expect(screen.getByText(/transition_receipt_has_noncanonical_state/)).toBeTruthy();
  });

  it("does not silently select the first event for a stale shared cursor", () => {
    const onQueryChange = vi.fn();
    const { container } = render(<TimelineView
      payload={payload()}
      pages={pages}
      query={{ ...query, timeCursor: "evt-outside", timeLanes: ["action"] }}
      onQueryChange={onQueryChange}
      onOpenPage={vi.fn()}
    />);
    expect(screen.getAllByText(t("timeline.inspector.stale")).length).toBeGreaterThanOrEqual(2);
    expect(container.querySelector('[aria-current="true"]')).toBeNull();
    expect(container.querySelectorAll('.timelineEvent[tabindex="0"]')).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: new RegExp(t("timeline.lane.action")) }));
    expect(onQueryChange).toHaveBeenCalledWith({ timeLanes: [], timeCursor: null });
  });

  it("reports a reversed date window as invalid instead of empty history", () => {
    render(<TimelineView
      payload={payload()}
      pages={pages}
      query={{ ...query, timeFrom: "2026-07-11", timeTo: "2026-07-10" }}
      onQueryChange={vi.fn()}
      onOpenPage={vi.fn()}
    />);
    expect(screen.getByRole("alert").textContent).toContain(t("timeline.range.invalid"));
  });

  it("uses one roving tab stop and arrow keys to move selection", () => {
    const onQueryChange = vi.fn();
    render(<TimelineView payload={payload()} pages={pages} query={query} onQueryChange={onQueryChange} onOpenPage={vi.fn()} />);
    const research = screen.getByRole("button", { name: /Research note/ });
    const review = screen.getByRole("button", { name: /Review evidence/ });
    expect(research.tabIndex).toBe(0);
    expect(review.tabIndex).toBe(-1);
    fireEvent.keyDown(research, { key: "ArrowDown" });
    expect(onQueryChange).toHaveBeenCalledWith({ timeCursor: "evt-action" });
  });

  it("opens a deep-linked late event without mounting every preceding row", () => {
    const manyEvents = Array.from({ length: 240 }, (_, index) => temporalEvent({
      event_id: `evt-${String(index).padStart(3, "0")}`,
      recorded_at: `2026-07-11T${String(index % 24).padStart(2, "0")}:00:00Z`
    }));
    const { container } = render(<TimelineView
      payload={payload({
        event_count: manyEvents.length,
        total_count: manyEvents.length,
        returned_count: manyEvents.length,
        page: { offset: 0, limit: manyEvents.length, remaining_count: 0, fingerprint: "many" },
        summary: { scope: "full_result", event_count: manyEvents.length, by_kind: {}, by_context: {}, conflict_count: 0, imprecise_count: 0, diagnostic_count: 0 },
        events: manyEvents
      })}
      pages={pages}
      query={{ ...query, timeCursor: "evt-239" }}
      onQueryChange={vi.fn()}
      onOpenPage={vi.fn()}
    />);
    expect(container.querySelectorAll(".timelineEvent")).toHaveLength(80);
    expect(screen.getByText(t("timeline.window.selectedOutside"))).toBeTruthy();
    expect(screen.getByText("evt-239")).toBeTruthy();
    expect(container.querySelectorAll('.timelineEvent[tabindex="0"]')).toHaveLength(1);
  });

  it("becomes inert and hidden underneath another primary surface", () => {
    const { container } = render(<TimelineView payload={payload()} pages={pages} query={query} inactive onQueryChange={vi.fn()} onOpenPage={vi.fn()} />);
    const surface = container.querySelector<HTMLElement>(".timelineSurface")!;
    expect(surface.inert).toBe(true);
    expect(surface.getAttribute("aria-hidden")).toBe("true");
  });
});
