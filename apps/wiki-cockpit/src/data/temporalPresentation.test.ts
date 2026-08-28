import { describe, expect, it } from "vitest";
import type { TemporalEvent } from "../types";
import {
  filterTemporalEvents,
  firstTemporalPageId,
  pageIdFromTemporalRef,
  temporalDisplayEntries,
  temporalLane,
  temporalValueForMode
} from "./temporalPresentation";

function event(overrides: Partial<TemporalEvent>): TemporalEvent {
  return {
    schema_version: "wiki_temporal_event.v1",
    event_id: "evt-example",
    kind: "page_updated",
    subject_refs: ["page:example"],
    context_refs: ["context:example"],
    occurred_at: "2026-07-11T15:00:00Z",
    recorded_at: "2026-07-11T16:00:00Z",
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
    origin: { adapter: "test" },
    temporal_conflicts: [],
    anchor: { field: "occurred_at", value: "2026-07-11T15:00:00Z", precision: "instant" },
    ...overrides
  };
}

describe("temporal presentation", () => {
  it("keeps semantic, occurred and recorded time as three strict selectable truths", () => {
    const item = event({});
    expect(temporalValueForMode(item, "event")).toBe("2026-07-11T15:00:00Z");
    expect(temporalValueForMode(item, "occurred")).toBe("2026-07-11T15:00:00Z");
    expect(temporalValueForMode(item, "recorded")).toBe("2026-07-11T16:00:00Z");
    expect(temporalValueForMode(event({ recorded_at: null }), "recorded")).toBeNull();
    expect(temporalValueForMode(event({ occurred_at: null, recorded_at: "2026-07-11", anchor: { field: "recorded_at", value: "2026-07-11", precision: "day" } }), "occurred")).toBeNull();
    expect(temporalValueForMode(event({
      occurred_at: null,
      created_at: "2026-07-09",
      anchor: { field: "created_at", value: "2026-07-09", precision: "day" }
    }), "event")).toBe("2026-07-09");
  });

  it("filters honest year/month/day precision without fabricating an instant", () => {
    const events = [
      event({ event_id: "evt-year", occurred_at: "2025", anchor: { field: "occurred_at", value: "2025", precision: "year" } }),
      event({ event_id: "evt-month", occurred_at: "2026-06", anchor: { field: "occurred_at", value: "2026-06", precision: "month" } }),
      event({ event_id: "evt-day", occurred_at: "2026-07-11", anchor: { field: "occurred_at", value: "2026-07-11", precision: "day" } })
    ];
    expect(filterTemporalEvents(events, { mode: "occurred", from: "2026-06-15" }).map((item) => item.event_id)).toEqual(["evt-day", "evt-month"]);
    expect(filterTemporalEvents(events, { mode: "occurred", from: "2026-06-01", to: "2026-06-30" }).map((item) => item.event_id)).toEqual(["evt-month"]);
  });

  it("orders canonical instants by microseconds instead of ISO punctuation", () => {
    const events = [
      event({
        event_id: "evt-seconds",
        occurred_at: "2026-07-11T15:00:00Z",
        anchor: { field: "occurred_at", value: "2026-07-11T15:00:00Z", precision: "instant" }
      }),
      event({
        event_id: "evt-fraction",
        occurred_at: "2026-07-11T15:00:00.100000Z",
        anchor: { field: "occurred_at", value: "2026-07-11T15:00:00.100000Z", precision: "instant" }
      }),
      event({
        event_id: "evt-micro-later",
        occurred_at: "2026-07-11T15:00:00.100001Z",
        anchor: { field: "occurred_at", value: "2026-07-11T15:00:00.100001Z", precision: "instant" }
      })
    ];

    expect(
      filterTemporalEvents(events, { mode: "occurred" }).map((item) => item.event_id)
    ).toEqual(["evt-micro-later", "evt-fraction", "evt-seconds"]);
  });

  it("uses explicit lanes and never silently drops undated events without a date filter", () => {
    const undated = event({ event_id: "evt-undated", kind: "receipt_recorded", occurred_at: null, recorded_at: null, anchor: null });
    const source = event({ event_id: "evt-source", kind: "source_ingested" });
    const packed = event({ event_id: "evt-packed", kind: "study-research.claim-recorded", lane: "page" });
    expect(temporalLane(undated)).toBe("receipt");
    expect(temporalLane(source)).toBe("source");
    expect(temporalLane(packed)).toBe("page");
    expect(filterTemporalEvents([undated, source], { mode: "occurred" })).toHaveLength(2);
    expect(filterTemporalEvents([undated, source], { mode: "occurred", lanes: ["source"] })).toEqual([source]);
  });

  it("resolves canonical page/source refs and prefers the event subject", () => {
    expect(pageIdFromTemporalRef("page:decision-1")).toBe("decision-1");
    expect(pageIdFromTemporalRef("source:source-1")).toBe("source-1");
    expect(pageIdFromTemporalRef("context:decision-1")).toBeNull();
    expect(firstTemporalPageId(event({
      subject_refs: ["context:system"],
      source_refs: ["page:source-1"],
      evidence_refs: ["page:evidence-1"]
    }))).toBe("source-1");
  });

  it("turns before/after scalar state into stable readable rows", () => {
    expect(temporalDisplayEntries({ state: "approved", count: 2, nested: { ok: true } })).toEqual([
      ["count", "2"],
      ["nested", '{"ok":true}'],
      ["state", "approved"]
    ]);
  });
});
