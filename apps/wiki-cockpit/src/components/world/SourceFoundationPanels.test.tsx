// @vitest-environment jsdom

// R5/R7 — sources-view HUD context panels. The honesty assertions here are
// contractual: every printed number is a TRUE payload/census total, every
// control carries an accessible name.

import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { t } from "../../data/i18n";
import type { GapMarkerSpec, SourceGapSummary } from "../../renderers/scene/parts/source-foundation";
import type { SourceFoundationPayload, SourceFoundationStation, SourceFoundationStream } from "../../types";
import {
  gapActionText,
  persistSourcesFirstRunDismissed,
  SOURCES_FIRST_RUN_STORAGE_KEY,
  SourceGapsPanel,
  SourcesFirstRunCard,
  sourcesFirstRunDismissed,
  sourcesSummaryModel,
  SourcesSummaryPanel,
  suggestedAttentionStation
} from "./SourceFoundationPanels";

afterEach(cleanup);

function station(overrides: Partial<SourceFoundationStation> & { station_id: string }): SourceFoundationStation {
  return {
    kind: "source",
    canonical_page_id: overrides.station_id.replace("station:", ""),
    path: "memorias/fonte.md",
    title: overrides.station_id,
    context: "financas",
    platform: "csv",
    owner_ref: "",
    config_page_id: null,
    channel_station_id: null,
    recipe_state: "valid",
    sync_state: "ok",
    lifecycle_state: "active",
    adoption_state: "adopted",
    pipeline_stage: "complete",
    pending_stream_count: 0,
    next_due_days: null,
    stream_ids: [],
    pipeline_ids: [],
    emission_ids: [],
    target_page_ids: [],
    diagnostic_codes: [],
    ...overrides
  };
}

function stream(id: string, sourceId: string, breached: boolean): SourceFoundationStream {
  return {
    stream_id: `stream:${sourceId}:${id}`,
    source_id: sourceId,
    recipe_stream_id: id,
    label: id,
    selected: true,
    privacy: "private_self",
    cadence_days: 7,
    cursor_age_days: breached ? 12 : 2,
    freshness_state: breached ? "stale" : "fresh",
    breached,
    target_page_ids: [],
    filter_keys: [],
    skip_reason_code: ""
  };
}

function payload(): SourceFoundationPayload {
  return {
    schema_version: "wiki_web_source_foundation.v1",
    repo_id: "test",
    revision: "r1",
    generated_at: "2026-07-17T00:00:00Z",
    topology_sha256: "0".repeat(64),
    summary: {
      sources: 3,
      channels: 0,
      streams: 4,
      pipelines: 0,
      emissions: 0,
      targets: 0,
      gaps: 3,
      blocked_sources: 1,
      pending_streams: 2
    },
    stations: [
      station({
        station_id: "source-a",
        title: "Fonte A",
        recipe_state: "missing",
        pending_stream_count: 2,
        diagnostic_codes: ["source_recipe_missing", "source_never_synced"]
      }),
      station({ station_id: "source-b", title: "Fonte B" }),
      station({ station_id: "source-c", title: "Fonte C", pending_stream_count: 1, diagnostic_codes: ["source_blocked"] })
    ],
    streams: [stream("s1", "source-a", true), stream("s2", "source-a", false), stream("s3", "source-c", true), stream("s4", "source-b", false)],
    pipelines: [],
    emissions: [],
    targets: [],
    diagnostics: []
  };
}

function marker(id: string, code: string, count: number, sourceId: string | null): GapMarkerSpec {
  return {
    id,
    code,
    position: [0, 0, 0],
    color: "#ff9d66",
    symbol: "▲",
    count,
    text: code,
    aria: `${code} — ${count}`,
    sourceId
  };
}

function gapSummary(): SourceGapSummary {
  return {
    total: 5,
    markerTotal: 3,
    worldMarkerCount: 2,
    stationCount: 2,
    groups: [
      {
        code: "source_never_synced",
        severity: "error",
        label: t("source_foundation.diagnostics.source_never_synced"),
        markerCount: 2,
        occurrenceCount: 3,
        markers: [
          { ...marker("gap:1", "source_never_synced", 2, "source-a"), severity: "error" },
          { ...marker("gap:2", "source_never_synced", 1, "source-c"), severity: "error" }
        ]
      },
      {
        code: "some_future_code",
        severity: "info",
        label: "Future diagnostic",
        markerCount: 1,
        occurrenceCount: 2,
        markers: [{ ...marker("gap:3", "some_future_code", 2, null), severity: "info" }]
      }
    ]
  };
}

describe("sourcesSummaryModel (R5)", () => {
  it("computes TRUE payload counts — pending, overdue, blocked, no-recipe", () => {
    expect(sourcesSummaryModel(payload())).toEqual({ pending: 2, overdue: 2, blocked: 1, noRecipe: 1 });
  });
});

describe("suggestedAttentionStation (R7)", () => {
  it("ranks by diagnostic pressure then pending streams, deterministically", () => {
    expect(suggestedAttentionStation(payload())).toEqual({ canonical_page_id: "source-a", title: "Fonte A" });
  });

  it("is null without a payload or without any attention station", () => {
    expect(suggestedAttentionStation(undefined)).toBeNull();
    const quiet = payload();
    quiet.stations = quiet.stations.map((entry) => ({ ...entry, diagnostic_codes: [], pending_stream_count: 0 }));
    expect(suggestedAttentionStation(quiet)).toBeNull();
  });
});

describe("gapActionText (R5)", () => {
  it("maps known diagnostic codes to their suggested action and unknown codes to the generic one", () => {
    expect(gapActionText("source_recipe_missing")).toBe(t("source_foundation.gaps.action.source_recipe_missing"));
    expect(gapActionText("totally_unknown")).toBe(t("source_foundation.gaps.action.generic"));
    // Never a raw dictionary key.
    expect(gapActionText("totally_unknown")).not.toContain("source_foundation.gaps.action.totally_unknown");
  });
});

describe("SourcesSummaryPanel (R5)", () => {
  it("prints the four TRUE counts, toggles the source_state lens and opens the gaps panel", () => {
    const onToggleLens = vi.fn();
    const onOpenGaps = vi.fn();
    const { container } = render(
      <SourcesSummaryPanel payload={payload()} gapTotal={5} lensActive={false} onToggleLens={onToggleLens} onOpenGaps={onOpenGaps} />
    );
    const panel = container.querySelector("[data-sources-summary]")!;
    expect(panel.getAttribute("aria-label")).toBe(t("source_foundation.summary.aria"));
    const rowCount = (key: string) =>
      Number(panel.querySelector(`[data-sources-summary-row="${key}"] strong`)?.textContent);
    expect(rowCount("pending")).toBe(2);
    expect(rowCount("overdue")).toBe(2);
    expect(rowCount("blocked")).toBe(1);
    expect(rowCount("noRecipe")).toBe(1);

    fireEvent.click(panel.querySelector('[data-sources-summary-row="overdue"]')!);
    expect(onToggleLens).toHaveBeenCalledTimes(1);

    const gaps = panel.querySelector("[data-sources-summary-gaps]")!;
    expect(gaps.textContent).toBe(t("source_foundation.gaps.chip", { n: 5 }));
    fireEvent.click(gaps);
    expect(onOpenGaps).toHaveBeenCalledTimes(1);
  });

  it("marks the active lens on every row (aria-pressed) without hiding any count", () => {
    const { container } = render(
      <SourcesSummaryPanel payload={payload()} gapTotal={null} lensActive onToggleLens={vi.fn()} onOpenGaps={vi.fn()} />
    );
    const rows = [...container.querySelectorAll("[data-sources-summary-row]")];
    expect(rows).toHaveLength(4);
    rows.forEach((row) => expect(row.getAttribute("aria-pressed")).toBe("true"));
    // No census yet → no gaps chip pretending a number exists.
    expect(container.querySelector("[data-sources-summary-gaps]")).toBeNull();
  });
});

describe("SourceGapsPanel (R5)", () => {
  it("lists the severity-ranked groups with TRUE occurrence counts that sum to the total", () => {
    const summary = gapSummary();
    const { container } = render(<SourceGapsPanel summary={summary} onSeeOnMap={vi.fn()} onClose={vi.fn()} />);
    const panel = container.querySelector("[data-gaps-panel]")!;
    expect(panel.getAttribute("data-gap-total")).toBe("5");
    expect(panel.getAttribute("aria-label")).toBe(t("source_foundation.gaps.panelAria"));
    const rows = [...panel.querySelectorAll("[data-gap-group]")];
    expect(rows.map((row) => row.getAttribute("data-gap-group"))).toEqual(["source_never_synced", "some_future_code"]);
    const printed = rows.map((row) => Number(row.querySelector(".sourceGapsRowHead strong")?.textContent));
    expect(printed).toEqual([3, 2]);
    expect(printed.reduce((sum, value) => sum + value, 0)).toBe(summary.total);
    // Every row carries a suggested action (generic for unknown codes).
    expect(rows[0].textContent).toContain(t("source_foundation.gaps.action.source_never_synced"));
    expect(rows[1].textContent).toContain(t("source_foundation.gaps.action.generic"));
  });

  it("fires 'see on map' with the group's WORST diagnostic and closes on demand", () => {
    const onSeeOnMap = vi.fn();
    const onClose = vi.fn();
    const summary = gapSummary();
    const { container } = render(<SourceGapsPanel summary={summary} onSeeOnMap={onSeeOnMap} onClose={onClose} />);
    fireEvent.click(container.querySelector('[data-gap-see-map="source_never_synced"]')!);
    expect(onSeeOnMap).toHaveBeenCalledWith(summary.groups[0].markers[0]);
    fireEvent.click(container.querySelector("header button")!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("names every control (no unnamed derived control)", () => {
    const { container } = render(<SourceGapsPanel summary={gapSummary()} onSeeOnMap={vi.fn()} onClose={vi.fn()} />);
    [...container.querySelectorAll("button")].forEach((control) => {
      const name = control.getAttribute("aria-label") ?? control.textContent ?? "";
      expect(name.trim().length).toBeGreaterThan(0);
    });
  });
});

describe("SourcesFirstRunCard (R7)", () => {
  it("renders the three bullets with the suggested first click and both dismiss paths", () => {
    const onOpenSuggestion = vi.fn();
    const onDismiss = vi.fn();
    const { container } = render(
      <SourcesFirstRunCard
        suggestion={{ canonical_page_id: "source-a", title: "Fonte A" }}
        onOpenSuggestion={onOpenSuggestion}
        onDismiss={onDismiss}
      />
    );
    const card = container.querySelector("[data-sources-first-run]")!;
    expect(card.getAttribute("aria-label")).toBe(t("source_foundation.firstRun.title"));
    expect(card.querySelectorAll("ul > li")).toHaveLength(3);

    fireEvent.click(card.querySelector('[data-first-run-open="source-a"]')!);
    expect(onOpenSuggestion).toHaveBeenCalledWith("source-a");

    fireEvent.click(card.querySelector("[data-first-run-never]")!);
    expect(onDismiss).toHaveBeenCalledWith({ never: true });
  });

  it("persists the never-again choice via localStorage and fails closed on storage errors", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => void values.set(key, value)
    };
    expect(sourcesFirstRunDismissed(storage)).toBe(false);
    persistSourcesFirstRunDismissed(storage);
    expect(values.get(SOURCES_FIRST_RUN_STORAGE_KEY)).toBe("dismissed");
    expect(sourcesFirstRunDismissed(storage)).toBe(true);
    // A throwing storage (private mode) must not crash — and must NOT nag
    // forever either way: dismissed() fails closed to true.
    const broken = { getItem: () => { throw new Error("blocked"); } };
    expect(sourcesFirstRunDismissed(broken as unknown as Storage)).toBe(true);
    const brokenSet = { setItem: () => { throw new Error("blocked"); } };
    expect(() => persistSourcesFirstRunDismissed(brokenSet as unknown as Storage)).not.toThrow();
  });
});
