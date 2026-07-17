// Source-foundation renderer specs (plan §10, §16.4–16.7, §19): ports keep
// the selected/outline/breached grammar with honest hidden counts and patch
// the SourceDock (never the page selection); lanes stay inspection with
// content/deep_read distinguishable by symbol AND ARIA; provenance conduits
// bundle with true member counts and never invent a trunk; flow bundles
// preserve many-to-many direction with a textual fallback; band guides sit at
// the exact structural levels; every color/symbol is reused from the overlay
// token vocabulary; and NONE of it exists outside the foundation profile.

import { describe, expect, it } from "vitest";
import { configureLanguage, t } from "../../../data/i18n";
import { SEMANTIC_VISUAL_TOKENS } from "../../../data/visualEncoding";
import type { LayoutNode } from "../../../scene/layout";
import { computeWorldLayout } from "../../../scene/perspectives";
import type {
  SourceFoundationWorldRequest,
  SourcePipelineLane,
  WorldLayout,
  WorldRequest
} from "../../../scene/perspectives";
import type {
  GraphEdge,
  GraphNode,
  SourceFoundationPayload,
  SourceFoundationStation,
  SourceFoundationStream
} from "../../../types";
import { SOURCE_FOUNDATION_LEVELS, SOURCE_FOUNDATION_WITHIN_BAND_LIFT } from "../../../world/contracts";
import {
  CONDUIT_SPLIT_BUDGET,
  FOUNDATION_BAND_OPACITY,
  conduitSpecs,
  flowBundleSpecs,
  flowSeverityColor,
  foundationBandOpacity,
  foundationPlaneGuides,
  foundationProposalStems,
  gapMarkerSpecs,
  gapSeverityToken,
  governancePlateSpecs,
  isFoundationProfile,
  laneRenderSpecs,
  pipelineStageFraction,
  portAriaText,
  portBreachToken,
  portFocusPatch,
  portRenderGroups,
  PIPELINE_KIND_SYMBOLS,
  PIPELINE_STAGE_ORDER
} from "./source-foundation";

configureLanguage("en");

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

// The §19.4 fixture shape, extended with a deep_read pipeline, a multi-owner
// event and a source-subject diagnostic so every renderer concern shows up.
function fixture(options: { hideConfigNode?: boolean; invalidRecipe?: boolean } = {}): {
  nodes: GraphNode[];
  edges: GraphEdge[];
  payload: SourceFoundationPayload;
} {
  const nodes: GraphNode[] = [
    node("world-root", "system", { page_type: "root_entity" }),
    node("source-a", "documentos", { page_type: "source" }),
    node("source-b", "documentos", { page_type: "source" }),
    node("source-c", "projetos", { page_type: "source" }),
    node("channel-inbox", "documentos", { page_type: "input_channel" }),
    ...(options.hideConfigNode ? [] : [node("config-a", "documentos", { page_type: "source_config" })]),
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
      pipelines: 2,
      emissions: 5,
      targets: 3,
      gaps: 3,
      blocked_sources: 0,
      pending_streams: 1
    },
    stations: [
      station("source-a", {
        channel_station_id: "channel:channel-inbox",
        config_page_id: "config-a",
        recipe_state: options.invalidRecipe ? "invalid" : "valid",
        stream_ids: ["stream:source-a:s1", "stream:source-a:s2"],
        pipeline_ids: ["pipeline:source-a:content", "pipeline:source-a:deep_read"],
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
      stream("source-a", "s2", { selected: false, breached: true, freshness_state: "stale" }),
      ...Array.from({ length: 8 }, (_, index) => stream("source-b", `s${index}`))
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
      },
      {
        pipeline_id: "pipeline:source-a:deep_read",
        source_id: "source-a",
        kind: "deep_read",
        cadence_days: 30,
        stream_ids: ["stream:source-a:s1"],
        current_stage: "indexed",
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
        emission_id: "emission:ab00000000000000000",
        source_id: "source-a",
        stream_id: null,
        event_page_id: "event-shared",
        proposal_page_ids: [],
        target_page_id: null,
        relation_type: "source_emission",
        observed_at: "2026-06-16",
        closure_state: "unknown",
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

function foundationLayout(options: Parameters<typeof fixture>[0] = {}): WorldLayout {
  const { nodes, edges, payload } = fixture(options);
  const request: SourceFoundationWorldRequest = {
    perspective: "sources",
    nodes,
    edges,
    centerId: "world-root",
    maxNodes: 60,
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

function layoutNode(id: string, overrides: Partial<LayoutNode>): LayoutNode {
  return {
    id,
    path: `memories/documentos/${id}.md`,
    title: id,
    context: "documentos",
    page_type: "context_note",
    freshness_state: "fresh",
    approved_state: "approved",
    risk_flags: [],
    source_ref_count: 0,
    inbound_links: 0,
    outbound_links: 0,
    ageDays: 1,
    overdueRatio: 0,
    isHub: false,
    isRoot: false,
    position: [0, 0, 0],
    scale: 0.2,
    ...overrides
  };
}

function bareFoundationLayout(overrides: Partial<WorldLayout>): WorldLayout {
  return {
    perspective: "sources",
    level: 0,
    radial: "orbit",
    nodes: [],
    wedges: [],
    wedgeKind: "group",
    guides: [],
    groups: [],
    clusterStars: [],
    beacons: [],
    rInner: 1,
    rOuter: 5.75,
    deadlineF: 0.66,
    unknownR: null,
    totals: { total: 0, shown: 0, hidden: 0 },
    truncated: 0,
    planeProfile: {
      active: "foundation",
      levels: { ...SOURCE_FOUNDATION_LEVELS },
      cameraHemisphere: "lower",
      transitionPath: "outer_arc",
      occlusionPolicy: "foundation-first",
      labelPolicy: "camera-facing"
    },
    foundationPrimitives: [],
    ...overrides
  };
}

describe("foundation profile gating (§10.1/§16.4)", () => {
  it("produces zero specs outside the foundation profile", () => {
    const layout = upperLayout();
    expect(isFoundationProfile(layout)).toBe(false);
    expect(foundationPlaneGuides(layout)).toEqual([]);
    expect(conduitSpecs(layout)).toEqual([]);
    expect(foundationProposalStems(layout)).toEqual([]);
    const groups = portRenderGroups(layout);
    expect(groups.solid.length + groups.outline.length + groups.overflow.length).toBe(0);
    expect(laneRenderSpecs(layout)).toEqual([]);
    expect(flowBundleSpecs(layout)).toEqual([]);
    expect(gapMarkerSpecs(layout)).toEqual([]);
    expect(governancePlateSpecs(layout)).toEqual([]);
  });

  it("activates on the resolved foundation layout", () => {
    expect(isFoundationProfile(foundationLayout())).toBe(true);
  });
});

describe("per-band plane guides (§10.12)", () => {
  it("puts one guide per band at the exact structural level", () => {
    const layout = foundationLayout();
    const guides = foundationPlaneGuides(layout);
    expect(guides.map((guide) => guide.plane).sort()).toEqual(["core", "foundation", "knowledge", "provenance"]);
    guides.forEach((guide) => {
      expect(guide.y).toBe(SOURCE_FOUNDATION_LEVELS[guide.plane]);
      expect(guide.radius).toBeGreaterThan(0);
    });
  });

  it("labels every band through i18n in both languages", () => {
    const layout = foundationLayout();
    for (const language of ["en", "pt"] as const) {
      configureLanguage(language);
      foundationPlaneGuides(layout).forEach((guide) => {
        expect(t(guide.labelKey)).not.toBe(guide.labelKey);
      });
    }
    configureLanguage("en");
  });
});

describe("occlusion policy per band (§10.10)", () => {
  it("keeps the plan's opacity ranges and raises contrast on selection", () => {
    expect(FOUNDATION_BAND_OPACITY.foundation.base).toBe(1);
    expect(FOUNDATION_BAND_OPACITY.provenance.base).toBeGreaterThanOrEqual(0.75);
    expect(FOUNDATION_BAND_OPACITY.provenance.base).toBeLessThanOrEqual(0.9);
    expect(FOUNDATION_BAND_OPACITY.knowledge.base).toBeGreaterThanOrEqual(0.35);
    expect(FOUNDATION_BAND_OPACITY.knowledge.base).toBeLessThanOrEqual(0.65);
    expect(foundationBandOpacity("knowledge", true)).toBeGreaterThan(foundationBandOpacity("knowledge"));
    expect(foundationBandOpacity("core")).toBeLessThanOrEqual(1);
    // Selection raises contrast, it never teleports/moves anything: the
    // helper returns opacity only.
    expect(foundationBandOpacity("knowledge", true)).toBeLessThanOrEqual(1);
  });
});

describe("stream ports (§10.4/§16.5)", () => {
  it("splits selected/solid from unselected/outline and keeps the honest +N port", () => {
    const layout = foundationLayout();
    const groups = portRenderGroups(layout);
    expect(groups.solid.map((port) => port.id)).toContain("stream:source-a:s1");
    expect(groups.outline.map((port) => port.id)).toContain("stream:source-a:s2");
    // source-b has 8 streams over the 6-port budget: 5 shown + one aggregate
    // carrying the TRUE hidden count.
    const overflow = groups.overflow.find((port) => port.sourceIds[0] === "source-b");
    expect(overflow).toBeTruthy();
    expect(overflow!.hiddenCount).toBe(3);
    expect(groups.solid.filter((port) => port.sourceIds[0] === "source-b")).toHaveLength(5);
    // Breach stays an overlay symbol on the SAME position (never displaced):
    const breached = groups.breached.find((port) => port.id === "stream:source-a:s2");
    expect(breached).toBeTruthy();
    const outlineTwin = groups.outline.find((port) => port.id === "stream:source-a:s2");
    expect(outlineTwin!.position).toEqual(breached!.position);
  });

  it("focuses the SourceDock and never patches a page selection", () => {
    const layout = foundationLayout();
    const groups = portRenderGroups(layout);
    const patch = portFocusPatch(groups.solid[0]!);
    expect(patch).toEqual({ dock: "source", src: groups.solid[0]!.sourceIds[0] });
    expect("pageId" in patch).toBe(false);
    const overflow = groups.overflow.find((port) => port.sourceIds[0] === "source-b")!;
    expect(portFocusPatch(overflow)).toEqual({ dock: "source", src: "source-b" });
  });

  it("reuses the freshness stale token for breach and speaks honest ARIA", () => {
    expect(portBreachToken()).toBe(SEMANTIC_VISUAL_TOKENS.freshness.states.stale);
    const layout = foundationLayout();
    const groups = portRenderGroups(layout);
    const breached = groups.breached.find((port) => port.id === "stream:source-a:s2")!;
    const aria = portAriaText(breached);
    expect(aria).toContain("cadence breached");
    expect(aria).toContain("not selected");
    const selectedAria = portAriaText(groups.solid.find((port) => port.id === "stream:source-a:s1")!);
    expect(selectedAria).not.toContain("cadence breached");
    const overflow = groups.overflow.find((port) => port.sourceIds[0] === "source-b")!;
    expect(portAriaText(overflow)).toContain("3");
  });
});

describe("pipeline lanes (§10.5/§16.5)", () => {
  it("keeps content and deep_read distinguishable by symbol and ARIA", () => {
    const layout = foundationLayout();
    const lanes = laneRenderSpecs(layout);
    const content = lanes.find((lane) => lane.laneKind === "content")!;
    const deepRead = lanes.find((lane) => lane.laneKind === "deep_read")!;
    expect(content.symbol).toBe(PIPELINE_KIND_SYMBOLS.content);
    expect(deepRead.symbol).toBe(PIPELINE_KIND_SYMBOLS.deep_read);
    expect(content.symbol).not.toBe(deepRead.symbol);
    expect(content.aria).not.toBe(deepRead.aria);
    expect(content.aria).toContain("complete");
    expect(deepRead.aria).toContain("indexed");
  });

  it("expresses cadence as a discrete tick count and stage as an arc fraction", () => {
    const layout = foundationLayout();
    const lanes = laneRenderSpecs(layout);
    const content = lanes.find((lane) => lane.laneKind === "content")!;
    expect(content.tickCount).toBe(7);
    expect(Number.isInteger(content.tickCount)).toBe(true);
    expect(content.stageFraction).toBe(1);
    expect(pipelineStageFraction("configured")).toBe(0);
    expect(pipelineStageFraction(PIPELINE_STAGE_ORDER[4])).toBeCloseTo(4 / 8, 6);
    // Unknown stages hide the marker instead of faking progress.
    expect(pipelineStageFraction("weird_stage")).toBeNull();
  });

  it("colors failure through the quality token, ingestion otherwise", () => {
    const errorLane: SourcePipelineLane = {
      kind: "pipeline-lane",
      id: "pipeline:x:content",
      pipelineId: "pipeline:x:content",
      laneKind: "content",
      stage: "failed",
      tickCount: 3,
      radius: 0.62,
      sourceIds: ["x"],
      pageIds: [],
      position: [1, SOURCE_FOUNDATION_LEVELS.foundation, 0],
      bounds: { radius: 0.62 },
      labelKey: "source_foundation.pipeline.content",
      severity: "error"
    };
    const layout = bareFoundationLayout({ foundationPrimitives: [errorLane] });
    const [spec] = laneRenderSpecs(layout);
    expect(spec.color).toBe(SEMANTIC_VISUAL_TOKENS.quality.states.flagged.color);
    const healthy = laneRenderSpecs(foundationLayout()).find((lane) => lane.laneKind === "content")!;
    expect(healthy.color).not.toBe(SEMANTIC_VISUAL_TOKENS.quality.states.flagged.color);
  });
});

describe("provenance conduits (§10.6/§10.7)", () => {
  it("builds a trunk per producing station and keeps many-to-many members", () => {
    const layout = foundationLayout();
    const conduits = conduitSpecs(layout);
    const conduitA = conduits.find((conduit) => conduit.stationId === "source-a")!;
    const conduitB = conduits.find((conduit) => conduit.stationId === "source-b")!;
    expect(conduitA.members.map((member) => member.id)).toEqual(
      expect.arrayContaining(["event-1", "event-shared", "proposal-1"])
    );
    // event-shared has TWO owning sources: it appears under both towers.
    expect(conduitB.members.map((member) => member.id)).toContain("event-shared");
    // No provenance, no trunk: source-c produced no event/proposal page.
    expect(conduits.find((conduit) => conduit.stationId === "source-c")).toBeUndefined();
    // The trunk is vertical over its station and stays inside the
    // foundation→provenance corridor — it never reaches the knowledge band.
    conduits.forEach((conduit) => {
      expect(conduit.top[0]).toBe(conduit.base[0]);
      expect(conduit.top[2]).toBe(conduit.base[2]);
      expect(conduit.top[1]).toBeGreaterThan(SOURCE_FOUNDATION_LEVELS.foundation);
      expect(conduit.top[1]).toBeLessThan(SOURCE_FOUNDATION_LEVELS.knowledge - 1);
      expect(conduit.memberCount).toBe(conduit.members.length + conduit.bundledCount);
    });
  });

  it("bundles beyond the split budget with the exact remaining count", () => {
    const stationNode = layoutNode("source-x", {
      isHub: true,
      plane: "foundation",
      foundationRole: "source-station",
      position: [2, SOURCE_FOUNDATION_LEVELS.foundation, 0]
    });
    const members = Array.from({ length: CONDUIT_SPLIT_BUDGET + 5 }, (_, index) =>
      layoutNode(`event-${String(index).padStart(2, "0")}`, {
        plane: "provenance",
        foundationRole: "provenance-page",
        sourceIds: ["source-x"],
        position: [2, SOURCE_FOUNDATION_LEVELS.provenance, index * 0.2]
      })
    );
    const layout = bareFoundationLayout({ nodes: [stationNode, ...members] });
    const [conduit] = conduitSpecs(layout);
    expect(conduit.members).toHaveLength(CONDUIT_SPLIT_BUDGET);
    expect(conduit.bundledCount).toBe(5);
    expect(conduit.memberCount).toBe(CONDUIT_SPLIT_BUDGET + 5);
  });
});

describe("flow bundles / multi-source tethers (§10.7/§16.7)", () => {
  it("keeps one tether per (source, target) relation with real direction", () => {
    const layout = foundationLayout();
    const specs = flowBundleSpecs(layout);
    const multi = specs.filter((spec) => spec.pageIds.includes("note-multi"));
    expect(multi.map((spec) => spec.sourceIds[0]).sort()).toEqual(["source-a", "source-b"]);
    specs.forEach((spec) => {
      // Direction derives from the real emission: foundation station → target.
      const towardTarget = Math.hypot(
        spec.arrowAt[0] - spec.to[0],
        spec.arrowAt[1] - spec.to[1],
        spec.arrowAt[2] - spec.to[2]
      );
      const fromDistance = Math.hypot(
        spec.arrowAt[0] - spec.from[0],
        spec.arrowAt[1] - spec.from[1],
        spec.arrowAt[2] - spec.from[2]
      );
      expect(towardTarget).toBeLessThan(fromDistance);
      // The control point clears the dense core by pushing radially outward.
      const mid = [(spec.from[0] + spec.to[0]) / 2, (spec.from[2] + spec.to[2]) / 2];
      expect(Math.hypot(spec.control[0], spec.control[2])).toBeGreaterThan(Math.hypot(mid[0], mid[1]) - 1e-9);
    });
  });

  it("maps closure severity to existing token colors only", () => {
    expect(flowSeverityColor("none")).toBe(SEMANTIC_VISUAL_TOKENS.evidence.states.linked.color);
    expect(flowSeverityColor("info")).toBe(SEMANTIC_VISUAL_TOKENS.evidence.states.unknown.color);
    expect(flowSeverityColor("warning")).toBe(SEMANTIC_VISUAL_TOKENS.actions.states.blocked.color);
    expect(flowSeverityColor("error")).toBe(SEMANTIC_VISUAL_TOKENS.actions.states.blocked.color);
  });

  it("raises opacity for the selected page without moving anything", () => {
    const layout = foundationLayout();
    const base = flowBundleSpecs(layout).find((spec) => spec.pageIds.includes("note-multi"))!;
    const selected = flowBundleSpecs(layout, "note-multi").find((spec) => spec.pageIds.includes("note-multi"))!;
    expect(selected.opacity).toBeGreaterThan(base.opacity);
    expect(selected.from).toEqual(base.from);
    expect(selected.to).toEqual(base.to);
    expect(selected.control).toEqual(base.control);
  });

  it("keeps the textual member-count fallback for bundled emissions", () => {
    const layout = bareFoundationLayout({
      foundationPrimitives: [
        {
          kind: "flow-bundle",
          id: "flow:source-x:note-y",
          sourceIds: ["source-x"],
          pageIds: ["note-y"],
          from: [2, SOURCE_FOUNDATION_LEVELS.foundation, 0],
          to: [1, SOURCE_FOUNDATION_LEVELS.knowledge, 1],
          position: [1.5, -1.6, 0.5],
          bounds: { radius: 0.12 },
          labelKey: "source_foundation.flow.emission",
          severity: "none",
          traceCount: 3,
          emissionIds: ["emission:e1", "emission:e2", "emission:e3"]
        }
      ]
    });
    const [spec] = flowBundleSpecs(layout);
    expect(spec.traceCount).toBe(3);
    expect(spec.countLabelAt).not.toBeNull();
    const single = flowBundleSpecs(foundationLayout()).find((item) => item.traceCount === 1);
    expect(single?.countLabelAt ?? null).toBeNull();
  });
});

describe("typed gap markers (§9.8/§16.5)", () => {
  it("resolves the safe message key and keeps the honest count", () => {
    const layout = foundationLayout();
    const specs = gapMarkerSpecs(layout);
    const neverSynced = specs.find((spec) => spec.code === "source_never_synced")!;
    expect(neverSynced.text).toBe("Source never synced");
    expect(neverSynced.text).not.toContain("source_foundation.");
    expect(neverSynced.count).toBe(2);
    expect(neverSynced.aria).toContain("2");
  });

  it("routes station-subject gaps to their source and leaves others announce-only", () => {
    const layout = foundationLayout();
    const specs = gapMarkerSpecs(layout);
    expect(specs.find((spec) => spec.code === "source_never_synced")!.sourceId).toBe("source-c");
    expect(specs.find((spec) => spec.code === "target_without_emission")!.sourceId).toBeNull();
  });

  it("uses existing severity tokens", () => {
    expect(gapSeverityToken("error")).toBe(SEMANTIC_VISUAL_TOKENS.quality.states.flagged);
    expect(gapSeverityToken("warning")).toBe(SEMANTIC_VISUAL_TOKENS.quality.states.warning);
    expect(gapSeverityToken("info")).toBe(SEMANTIC_VISUAL_TOKENS.attention.states.quiet);
    expect(gapSeverityToken("none")).toBe(SEMANTIC_VISUAL_TOKENS.attention.states.quiet);
  });
});

describe("governance plates (§10.11/§16.5)", () => {
  it("represents an off-screen config with quality tokens and the REAL page id", () => {
    const layout = foundationLayout({ hideConfigNode: true });
    const [plate] = governancePlateSpecs(layout);
    expect(plate).toBeTruthy();
    expect(plate.canonicalEntityId).toBe("config-a");
    expect(plate.severity).toBe("none");
    expect(plate.color).toBe(SEMANTIC_VISUAL_TOKENS.quality.states.clear.color);
    expect(plate.aria).toContain("No deterministic flags");
  });

  it("expresses recipe invalidity through the quality warning token — no new channel", () => {
    const layout = foundationLayout({ hideConfigNode: true, invalidRecipe: true });
    const [plate] = governancePlateSpecs(layout);
    expect(plate.severity).toBe("warning");
    expect(plate.color).toBe(SEMANTIC_VISUAL_TOKENS.quality.states.warning.color);
    expect(plate.aria).toContain("Quality warning");
  });

  it("emits no plate when the config page is a visible governance node", () => {
    expect(governancePlateSpecs(foundationLayout())).toEqual([]);
  });
});

describe("within-band proposal stems (§10.12)", () => {
  it("anchors stems at the band level and never crosses the bounded lift", () => {
    const layout = foundationLayout();
    const stems = foundationProposalStems(layout);
    const proposal = stems.find((stem) => stem.id === "proposal-1")!;
    expect(proposal.from[1]).toBe(SOURCE_FOUNDATION_LEVELS.provenance);
    stems.forEach((stem) => {
      expect(Math.abs(stem.to[1] - stem.from[1])).toBeLessThanOrEqual(SOURCE_FOUNDATION_WITHIN_BAND_LIFT + 1e-9);
      expect(stem.from[0]).toBe(stem.to[0]);
      expect(stem.from[2]).toBe(stem.to[2]);
    });
    // Only proposals get stems — the core anchor never grows a fake one.
    expect(stems.find((stem) => stem.id === "world-root")).toBeUndefined();
    expect(stems).toHaveLength(1);
  });
});
