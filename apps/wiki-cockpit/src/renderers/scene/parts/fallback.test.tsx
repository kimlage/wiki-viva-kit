// @vitest-environment jsdom

// Foundation 2D fallback + accessibility (plan §14, §19): the plan view swaps
// the circular map for four horizontal bands with connecting lines when the
// foundation profile is active (§14.2); SceneFallback grows navigable
// sections (Sources / Streams needing attention / Open provenance / Knowledge
// targets / Gaps) that fire the SAME semantic events as the 3D scene (§14.3);
// screen-reader names follow the §14.5 sentence patterns; nothing here is
// color-only (§14.7) and nothing animates (§14.6).

import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { configureLanguage, t } from "../../../data/i18n";
import type { GraphEdge, GraphNode, SourceFoundationPayload, SourceFoundationStation, SourceFoundationStream } from "../../../types";
import { computeWorldLayout } from "../../../scene/perspectives";
import type { SourceFoundationWorldRequest, SourceStreamPort, WorldLayout, WorldRequest } from "../../../scene/perspectives";
import { SOURCE_FOUNDATION_LEVELS } from "../../../world/contracts";
import type { GapMarkerSpec } from "./source-foundation";
import { sourceGapSummary } from "./source-foundation";
import { sceneCensus } from "./hud";
import {
  FOUNDATION_PLAN_BAND_ORDER,
  FallbackPlanView,
  SceneFallback,
  foundationFallbackSections,
  foundationPlanModel,
  foundationStreamAria
} from "./fallback";
import type { GitState } from "../../../types";

configureLanguage("en");
afterEach(() => {
  cleanup();
  configureLanguage("en");
});

const SNAPSHOT = "2026-07-01T00:00:00Z";

function node(id: string, context: string, overrides: Partial<GraphNode> & { stale_after_days?: string } = {}): GraphNode {
  return {
    id,
    path: `memories/${context}/${id}.md`,
    title: id,
    page_type: "context_note",
    context,
    freshness_state: "fresh",
    approved_state: "approved",
    risk_flags: [],
    metrics: { inbound_links: 0, outbound_links: 1, source_ref_count: 0 },
    updated_at: "2026-06-20",
    stale_after_days: "30",
    ...overrides
  } as GraphNode;
}

function station(id: string, overrides: Partial<SourceFoundationStation> = {}): SourceFoundationStation {
  return {
    station_id: `station:${id}`,
    kind: "source",
    canonical_page_id: id,
    path: `memories/documentos/${id}.md`,
    title: id,
    context: "documentos",
    platform: "Platform",
    owner_ref: "world-root",
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

function stream(sourceId: string, recipeStreamId: string, overrides: Partial<SourceFoundationStream> = {}): SourceFoundationStream {
  return {
    stream_id: `stream:${sourceId}:${recipeStreamId}`,
    source_id: sourceId,
    recipe_stream_id: recipeStreamId,
    label: recipeStreamId,
    selected: true,
    privacy: "private_self",
    cadence_days: 7,
    cursor_age_days: 2,
    freshness_state: "fresh",
    breached: false,
    target_page_ids: [],
    filter_keys: [],
    skip_reason_code: "",
    ...overrides
  };
}

// Compact §19.4-style chain: two channel-grouped sources plus a lone one, an
// overdue stream, an over-budget breached stream, an open shared event, a
// two-source target, a declared-only target and three typed gaps.
function fixture(): { nodes: GraphNode[]; edges: GraphEdge[]; payload: SourceFoundationPayload } {
  const nodes: GraphNode[] = [
    node("world-root", "system", { page_type: "root_entity" }),
    node("source-a", "documentos", { page_type: "source" }),
    node("source-b", "documentos", { page_type: "source" }),
    node("source-c", "projetos", { page_type: "source" }),
    node("channel-inbox", "documentos", { page_type: "input_channel" }),
    node("event-1", "documentos", { page_type: "ingestion_event" }),
    node("event-shared", "documentos", { page_type: "ingestion_event" }),
    node("proposal-1", "documentos", { page_type: "proposal", approved_state: "proposal" }),
    node("note-multi", "projetos"),
    node("note-single", "projetos"),
    node("insight-declared", "projetos")
  ];
  const edges: GraphEdge[] = [
    { source: "note-multi", target: "source-a", type: "source_ref", status: "valid", weight: 1 },
    { source: "note-multi", target: "source-b", type: "source_ref", status: "valid", weight: 1 },
    { source: "note-single", target: "source-c", type: "source_ref", status: "valid", weight: 1 }
  ];
  const payload: SourceFoundationPayload = {
    schema_version: "wiki_web_source_foundation.v1",
    repo_id: "fixture",
    revision: "rev-1",
    generated_at: SNAPSHOT,
    topology_sha256: "0".repeat(64),
    summary: {
      sources: 3,
      channels: 1,
      streams: 10,
      pipelines: 1,
      emissions: 4,
      targets: 3,
      gaps: 3,
      blocked_sources: 0,
      pending_streams: 1
    },
    stations: [
      station("source-a", {
        channel_station_id: "channel:channel-inbox",
        stream_ids: ["stream:source-a:s1", "stream:source-a:s2"],
        pipeline_ids: ["pipeline:source-a:content"],
        emission_ids: ["emission:a1000000000000000000"],
        target_page_ids: ["note-multi", "insight-declared"]
      }),
      station("source-b", {
        channel_station_id: "channel:channel-inbox",
        stream_ids: Array.from({ length: 8 }, (_, index) => `stream:source-b:s${index}`),
        emission_ids: ["emission:b1000000000000000000"],
        target_page_ids: ["note-multi"]
      }),
      station("source-c", {
        context: "projetos",
        emission_ids: ["emission:c1000000000000000000"],
        target_page_ids: ["note-single"]
      }),
      station("channel-inbox", {
        station_id: "channel:channel-inbox",
        kind: "input_channel",
        canonical_page_id: "channel-inbox"
      })
    ],
    streams: [
      stream("source-a", "s1", { target_page_ids: ["insight-declared"] }),
      // Overdue by 3 days: cursor 10 over a 7-day cadence (§14.5 stream name).
      stream("source-a", "s2", { selected: false, breached: true, freshness_state: "stale", cursor_age_days: 10 }),
      ...Array.from({ length: 7 }, (_, index) => stream("source-b", `s${index}`)),
      // Breached stream whose port falls over the per-station port budget —
      // it must still reach "streams needing attention" via a stand-in port.
      stream("source-b", "s7", { breached: true, freshness_state: "stale", cursor_age_days: 9 })
    ],
    pipelines: [
      {
        pipeline_id: "pipeline:source-a:content",
        source_id: "source-a",
        kind: "content",
        cadence_days: 7,
        stream_ids: ["stream:source-a:s1", "stream:source-a:s2"],
        current_stage: "complete",
        last_transition_at: "2026-06-15"
      }
    ],
    emissions: [
      {
        emission_id: "emission:a1000000000000000000",
        source_id: "source-a",
        stream_id: null,
        event_page_id: "event-1",
        proposal_page_ids: ["proposal-1"],
        target_page_id: "note-multi",
        relation_type: "source_ref",
        observed_at: "2026-06-15",
        closure_state: "accepted",
        evidence_refs: [],
        provenance_basis: "frontmatter"
      },
      {
        emission_id: "emission:b1000000000000000000",
        source_id: "source-b",
        stream_id: null,
        event_page_id: "event-shared",
        proposal_page_ids: [],
        target_page_id: "note-multi",
        relation_type: "source_ref",
        observed_at: "2026-06-15",
        closure_state: "pending",
        evidence_refs: [],
        provenance_basis: "frontmatter"
      },
      {
        emission_id: "emission:c1000000000000000000",
        source_id: "source-c",
        stream_id: null,
        event_page_id: null,
        proposal_page_ids: [],
        target_page_id: "note-single",
        relation_type: "source_ref",
        observed_at: "2026-06-15",
        closure_state: "accepted",
        evidence_refs: [],
        provenance_basis: "frontmatter"
      }
    ],
    targets: [
      {
        page_id: "note-multi",
        source_ids: ["source-a", "source-b"],
        event_page_ids: ["event-1", "event-shared"],
        emission_count: 2,
        accepted_count: 1,
        pending_count: 1,
        closure_state: "mixed",
        target_declared_by_stream_ids: []
      },
      {
        page_id: "note-single",
        source_ids: ["source-c"],
        event_page_ids: [],
        emission_count: 1,
        accepted_count: 1,
        pending_count: 0,
        closure_state: "accepted",
        target_declared_by_stream_ids: []
      },
      {
        page_id: "insight-declared",
        source_ids: ["source-a"],
        event_page_ids: [],
        emission_count: 0,
        accepted_count: 0,
        pending_count: 0,
        closure_state: "declared_only",
        target_declared_by_stream_ids: ["stream:source-a:s1"]
      }
    ],
    diagnostics: [
      {
        gap_id: `gap:target_without_emission:${"a".repeat(16)}`,
        code: "target_without_emission",
        severity: "warning",
        subject_ref: "insight-declared",
        related_refs: ["source-a"],
        message_key: "source_foundation.diagnostics.target_without_emission",
        count: 1
      },
      {
        gap_id: `gap:source_never_synced:${"d".repeat(16)}`,
        code: "source_never_synced",
        severity: "error",
        subject_ref: "source-c",
        related_refs: [],
        message_key: "source_foundation.diagnostics.source_never_synced",
        count: 2
      },
      {
        gap_id: `gap:multiple_sources_supported:${"c".repeat(16)}`,
        code: "multiple_sources_supported",
        severity: "info",
        subject_ref: "note-multi",
        related_refs: ["source-a", "source-b"],
        message_key: "source_foundation.diagnostics.multiple_sources_supported",
        count: 1
      }
    ]
  };
  return { nodes, edges, payload };
}

function foundationLayout(maxNodes = 60): WorldLayout {
  const { nodes, edges, payload } = fixture();
  const request: SourceFoundationWorldRequest = {
    perspective: "sources",
    nodes,
    edges,
    centerId: "world-root",
    maxNodes,
    snapshotAt: SNAPSHOT,
    sourceFoundation: payload
  };
  return computeWorldLayout(request);
}

function upperLayout(): WorldLayout {
  const { nodes, edges } = fixture();
  const request: WorldRequest = {
    perspective: "sources",
    nodes,
    edges,
    centerId: "world-root",
    maxNodes: 60,
    snapshotAt: SNAPSHOT
  };
  return computeWorldLayout(request);
}

const GIT: GitState = {
  available: true,
  default_branch: "main",
  current_branch: "main",
  branch_prefix: "wiki/",
  worktree: { clean: true, changed_files: [] },
  upstream: { remote: "origin", ahead: 0, behind: 0, name: "origin/main", last_fetch_at: null },
  proposal: { is_proposal_branch: false, theme: "", draft_pr_url: null, human_gate_state: "clean" }
};

function renderSceneFallback(
  layout: WorldLayout,
  payload: SourceFoundationPayload | undefined,
  handlers: {
    onNodeSelect?: (id: string) => void;
    onPortFocus?: (port: SourceStreamPort) => void;
    onGapInspect?: (marker: GapMarkerSpec) => void;
  } = {}
) {
  const { nodes, edges } = fixture();
  return render(
    <SceneFallback
      layout={layout}
      overlay="freshness"
      git={GIT}
      fallbackReason="reduced_motion"
      selectedPageId=""
      highlightedIds={new Set()}
      census={sceneCensus(nodes, edges, layout, "freshness")}
      makeHref={() => "#patch"}
      sourceFoundation={payload}
      onNodeSelect={handlers.onNodeSelect}
      onGroupSelect={() => undefined}
      onStarDrill={() => undefined}
      onPortFocus={handlers.onPortFocus}
      onGapInspect={handlers.onGapInspect}
    />
  );
}

describe("foundationPlanModel (§14.2)", () => {
  it("is null outside the foundation profile — the circular plan stays untouched", () => {
    expect(foundationPlanModel(upperLayout())).toBeNull();
  });

  it("lays the four bands in the §14.1 reading order with honest per-band counts", () => {
    const layout = foundationLayout();
    const model = foundationPlanModel(layout)!;
    expect(model.bands.map((band) => band.plane)).toEqual(FOUNDATION_PLAN_BAND_ORDER);
    expect(model.bands.map((band) => band.plane)).toEqual(["core", "knowledge", "provenance", "foundation"]);
    const counted = model.bands.reduce((sum, band) => sum + band.count, 0);
    expect(counted).toBe(layout.nodes.length);
    // Band order on screen: each band strictly below the previous one.
    for (let index = 1; index < model.bands.length; index += 1) {
      expect(model.bands[index].top).toBeGreaterThan(model.bands[index - 1].top);
    }
  });

  it("projects every node inside the band of its structural plane — state never crosses bands in 2D either", () => {
    const layout = foundationLayout();
    const model = foundationPlanModel(layout)!;
    layout.nodes.forEach((layoutNode) => {
      const point = model.points.get(layoutNode.id)!;
      const band = model.bands.find((candidate) => candidate.plane === layoutNode.plane)!;
      expect(point.y).toBeGreaterThanOrEqual(band.top);
      expect(point.y).toBeLessThanOrEqual(band.bottom);
    });
  });

  it("draws the source→provenance→knowledge→core chain from real relations only", () => {
    const layout = foundationLayout();
    const model = foundationPlanModel(layout)!;
    expect(model.links.length).toBeGreaterThan(0);
    const points = model.points;
    const stationPoint = points.get("source-a")!;
    const eventPoint = points.get("event-1")!;
    const targetPoint = points.get("note-multi")!;
    const corePoint = points.get("world-root")!;
    const hasLink = (a: { x: number; y: number }, b: { x: number; y: number }) =>
      model.links.some((link) => link.x1 === a.x && link.y1 === a.y && link.x2 === b.x && link.y2 === b.y);
    expect(hasLink(stationPoint, eventPoint)).toBe(true);
    expect(hasLink(stationPoint, targetPoint)).toBe(true);
    expect(hasLink(targetPoint, corePoint)).toBe(true);
    // The declared-only target has no emission, so no knowledge→core line.
    const declaredPoint = points.get("insight-declared")!;
    expect(hasLink(declaredPoint, corePoint)).toBe(false);
  });

  it("is deterministic for the same layout", () => {
    const a = foundationPlanModel(foundationLayout())!;
    const b = foundationPlanModel(foundationLayout())!;
    expect([...a.points.entries()]).toEqual([...b.points.entries()]);
    expect(a.links).toEqual(b.links);
    expect(a.bands).toEqual(b.bands);
  });
});

describe("foundationFallbackSections (§14.3/§14.5)", () => {
  it("is null outside the foundation profile", () => {
    expect(foundationFallbackSections(upperLayout(), fixture().payload)).toBeNull();
  });

  it("names sources with the §14.5 pattern: streams on time, overdue, recipe, stage, emitted pages", () => {
    const sections = foundationFallbackSections(foundationLayout(), fixture().payload)!;
    expect(sections.stations.items.map((entry) => entry.node.id).sort()).toEqual(["source-a", "source-b", "source-c"]);
    const sourceA = sections.stations.items.find((entry) => entry.node.id === "source-a")!;
    expect(sourceA.aria).toBe(
      "Source source-a; 1 of 2 streams on time; 1 streams overdue; recipe valid; pipeline at complete; 2 pages emitted"
    );
  });

  it("lists every breached stream — including one whose port fell over the port budget — with the §14.5 stream name", () => {
    const layout = foundationLayout();
    const sections = foundationFallbackSections(layout, fixture().payload)!;
    const ids = sections.streams.items.map((entry) => entry.port.streamId);
    expect(ids).toEqual(["stream:source-a:s2", "stream:source-b:s7"]);
    const overdue = sections.streams.items[0];
    expect(overdue.aria).toBe(
      "Stream s2; overdue by 3 days; cadence 7 days; privacy private_self; 0 target pages"
    );
    // The over-budget stream has no rendered port primitive, yet the entry
    // carries the same identity the port-focus event needs.
    const ports = (layout.foundationPrimitives ?? []).filter(
      (primitive): primitive is SourceStreamPort => primitive.kind === "stream-port"
    );
    expect(ports.some((port) => port.streamId === "stream:source-b:s7")).toBe(false);
    expect(sections.streams.items[1].port.sourceIds).toEqual(["source-b"]);
  });

  it("keeps 'open provenance' to pages of emissions that are really not closed", () => {
    const sections = foundationFallbackSections(foundationLayout(), fixture().payload)!;
    expect(sections.provenance.items.map((entry) => entry.node.id)).toEqual(["event-shared"]);
    expect(sections.provenance.items[0].aria).toContain(t("source_foundation.fallback.provenance.open"));
  });

  it("names knowledge targets with supporting sources and closure state", () => {
    const sections = foundationFallbackSections(foundationLayout(), fixture().payload)!;
    const byId = new Map(sections.targets.items.map((entry) => [entry.node.id, entry.aria]));
    expect(byId.get("note-multi")).toBe("Target note-multi; 2 supporting sources; closure mixed");
    expect(byId.get("insight-declared")).toContain("declared only");
  });

  it("carries the typed gaps as the SAME grouped census the HUD panel shows (R5 parity)", () => {
    const layout = foundationLayout();
    const sections = foundationFallbackSections(layout, fixture().payload)!;
    const census = sourceGapSummary(layout);
    // Same groups, same order, same TRUE occurrence counts as the HUD panel.
    expect(sections.gaps.items.map((group) => [group.code, group.occurrenceCount])).toEqual(
      census.groups.map((group) => [group.code, group.occurrenceCount])
    );
    expect(sections.gapTotal).toBe(census.total);
    const never = sections.gaps.items.find((group) => group.code === "source_never_synced")!;
    expect(never.label).toBe(t("source_foundation.diagnostics.source_never_synced"));
    expect(never.occurrenceCount).toBe(2);
  });

  it("reports stations hidden by the node budget through the cluster-star count", () => {
    const sections = foundationFallbackSections(foundationLayout(3), fixture().payload)!;
    expect(sections.stations.items.length + sections.stations.hidden).toBe(3);
    expect(sections.stations.hidden).toBeGreaterThan(0);
  });

  it("degrades honestly without the payload: no invented stream/recipe/closure facts", () => {
    const layout = foundationLayout();
    const sections = foundationFallbackSections(layout)!;
    const sourceA = sections.stations.items.find((entry) => entry.node.id === "source-a")!;
    expect(sourceA.aria).toBe("Source source-a");
    // Visible breached ports still surface; open provenance cannot be claimed.
    expect(sections.streams.items.map((entry) => entry.port.streamId)).toEqual(["stream:source-a:s2"]);
    expect(sections.provenance.items).toEqual([]);
  });

  it("localizes the section vocabulary in Portuguese (i18n parity)", () => {
    configureLanguage("pt");
    const sections = foundationFallbackSections(foundationLayout(), fixture().payload)!;
    const sourceA = sections.stations.items.find((entry) => entry.node.id === "source-a")!;
    expect(sourceA.aria).toBe(
      "Fonte source-a; 1 de 2 streams em dia; 1 streams vencidas; receita válida; pipeline em complete; 2 páginas emitidas"
    );
    expect(t("source_foundation.fallback.streamsAttention")).toBe("Streams precisando de atenção");
  });
});

describe("FallbackPlanView (§14.2)", () => {
  it("renders the four-band SVG (aria-hidden) under the foundation profile", () => {
    const layout = foundationLayout();
    const { container } = render(
      <FallbackPlanView layout={layout} overlay="freshness" selectedPageId="" highlightedIds={new Set()} />
    );
    const svg = container.querySelector("svg.fallbackPlan")!;
    expect(svg.getAttribute("aria-hidden")).toBe("true");
    expect(svg.getAttribute("data-plane-profile")).toBe("foundation");
    const labels = [...svg.querySelectorAll("text.planContextLabel")].map((element) => element.textContent ?? "");
    ["core", "knowledge", "provenance", "foundation"].forEach((plane) => {
      expect(labels.some((label) => label.startsWith(t(`source_foundation.band.${plane}`)))).toBe(true);
    });
    // Nodes keep the overlay encoding attributes (same colors as 3D).
    expect(svg.querySelectorAll("circle[data-overlay='freshness']").length).toBe(layout.nodes.length);
  });

  it("keeps the classic circular plan outside the foundation profile", () => {
    const { container } = render(
      <FallbackPlanView layout={upperLayout()} overlay="freshness" selectedPageId="" highlightedIds={new Set()} />
    );
    const svg = container.querySelector("svg.fallbackPlan")!;
    expect(svg.getAttribute("data-plane-profile")).toBe("knowledge");
  });
});

describe("SceneFallback foundation sections (§14.3/§14.4)", () => {
  it("renders the five navigable sections and fires the same semantic events as the 3D scene", () => {
    const layout = foundationLayout();
    const onNodeSelect = vi.fn();
    const onPortFocus = vi.fn();
    const onGapInspect = vi.fn();
    const { container } = renderSceneFallback(layout, fixture().payload, { onNodeSelect, onPortFocus, onGapInspect });
    const nav = container.querySelector(".fallbackFoundation")!;
    expect(nav.getAttribute("aria-label")).toBe(t("source_foundation.fallback.sections"));
    expect([...nav.querySelectorAll("[data-section]")].map((section) => section.getAttribute("data-section"))).toEqual([
      "sources",
      "streams",
      "provenance",
      "targets",
      "gaps"
    ]);

    const sourceLink = nav.querySelector('[data-section="sources"] a[data-world-target-id="source-a"]')!;
    fireEvent.click(sourceLink);
    expect(onNodeSelect).toHaveBeenCalledWith("source-a");

    const streamButton = nav.querySelector('[data-section="streams"] button')!;
    fireEvent.click(streamButton);
    expect(onPortFocus).toHaveBeenCalledTimes(1);
    expect((onPortFocus.mock.calls[0][0] as SourceStreamPort).streamId).toBe("stream:source-a:s2");

    const provenanceLink = nav.querySelector('[data-section="provenance"] a[data-world-target-id="event-shared"]')!;
    fireEvent.click(provenanceLink);
    expect(onNodeSelect).toHaveBeenCalledWith("event-shared");

    const gapButton = nav.querySelector('[data-section="gaps"] button')!;
    fireEvent.click(gapButton);
    expect(onGapInspect).toHaveBeenCalledTimes(1);

    // §14.7: breached streams pair symbol + full text, never color alone.
    expect(streamButton.querySelector(".fallbackFoundationSymbol")).not.toBeNull();
    expect(streamButton.getAttribute("aria-label")).toContain("Stream s2");
  });

  it("mounts no foundation nav outside the foundation profile", () => {
    const { container } = renderSceneFallback(upperLayout(), undefined);
    expect(container.querySelector(".fallbackFoundation")).toBeNull();
  });

  it("keeps every section control reachable and named (no derived control without an accessible name)", () => {
    const { container } = renderSceneFallback(foundationLayout(), fixture().payload);
    const controls = [...container.querySelectorAll(".fallbackFoundation a, .fallbackFoundation button")];
    expect(controls.length).toBeGreaterThan(0);
    controls.forEach((control) => {
      const name = control.getAttribute("aria-label") ?? control.textContent ?? "";
      expect(name.trim().length).toBeGreaterThan(0);
    });
  });
});

describe("foundationStreamAria (§14.5)", () => {
  it("falls back to the generic port ARIA when the payload stream is unknown", () => {
    const port: SourceStreamPort = {
      kind: "stream-port",
      id: "stream:x:y",
      streamId: "stream:x:y",
      sourceIds: ["x"],
      pageIds: [],
      position: [0, 0, 0],
      bounds: { radius: 0.09 },
      labelKey: "source_foundation.port.stream",
      severity: "warning",
      selected: false,
      breached: true,
      hiddenCount: 0
    };
    expect(foundationStreamAria(port)).toContain(t("source_foundation.port.breachedState"));
  });

  it("says 'never synced' for a never-observed stream instead of inventing an overdue age", () => {
    const neverStream = stream("source-a", "s9", { breached: false, freshness_state: "never", cursor_age_days: null });
    const port = {
      kind: "stream-port",
      id: neverStream.stream_id,
      streamId: neverStream.stream_id,
      sourceIds: ["source-a"],
      pageIds: [],
      position: [0, 0, 0] as [number, number, number],
      bounds: { radius: 0 },
      labelKey: "source_foundation.port.stream",
      severity: "none" as const,
      selected: true,
      breached: false,
      hiddenCount: 0
    } satisfies SourceStreamPort;
    expect(foundationStreamAria(port, neverStream)).toContain(t("source_foundation.fallback.stream.never"));
  });
});

// §14.6: the fallback carries no information in animation — the band SVG and
// the sections are static DOM. Guard that no element opts into CSS animation
// hooks from this module's markup.
describe("reduced motion (§14.6)", () => {
  it("renders no animated markup in the foundation fallback", () => {
    const { container } = renderSceneFallback(foundationLayout(), fixture().payload);
    expect(container.querySelector(".fallbackFoundation [style*='animation']")).toBeNull();
    expect(container.querySelector(".fallbackFoundation animate, .fallbackFoundation animateTransform")).toBeNull();
  });
});

// The §14.1 chain: SOURCE_FOUNDATION_LEVELS ordering backs the band order used
// here — if the levels ever change, the fallback reading order must follow.
describe("band order contract", () => {
  it("matches the structural levels top-down", () => {
    const ordered = [...FOUNDATION_PLAN_BAND_ORDER].sort(
      (a, b) => SOURCE_FOUNDATION_LEVELS[b] - SOURCE_FOUNDATION_LEVELS[a]
    );
    expect(ordered).toEqual(FOUNDATION_PLAN_BAND_ORDER);
  });
});
