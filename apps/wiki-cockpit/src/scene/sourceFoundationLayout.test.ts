// Source-foundation layout tests (plan §19.4): role bands are exact, X/Z is
// deterministic, many-to-many provenance survives, the barycenter is stable,
// hidden counts are honest, config is a control (never a station), state and
// overlay metrics never move a node out of its band, and the same real page
// ids appear across views. The upper-profile ground guides never mount in the
// foundation profile (§10.12) — encoded as planeProfile + empty guides.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type {
  GraphEdge,
  GraphNode,
  SourceFoundationEmission,
  SourceFoundationPayload,
  SourceFoundationStation,
  SourceFoundationStream,
  SourceFoundationTarget
} from "../types";
import { SOURCE_FOUNDATION_LEVELS, SOURCE_FOUNDATION_WITHIN_BAND_LIFT } from "../world/contracts";
import { computeWorldLayout } from "./perspectives";
import type { SourceFoundationWorldRequest, SourceStreamPort, WorldRequest } from "./perspectives";

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

function emission(id: string, sourceId: string, overrides: Partial<SourceFoundationEmission> = {}): SourceFoundationEmission {
  return {
    emission_id: `emission:${id.padEnd(20, "0").slice(0, 20)}`,
    source_id: sourceId,
    stream_id: null,
    event_page_id: null,
    proposal_page_ids: [],
    target_page_id: null,
    relation_type: "source_ref",
    observed_at: "2026-06-15",
    closure_state: "accepted",
    evidence_refs: [],
    provenance_basis: "frontmatter",
    ...overrides
  };
}

function target(pageId: string, sourceIds: string[], overrides: Partial<SourceFoundationTarget> = {}): SourceFoundationTarget {
  return {
    page_id: pageId,
    source_ids: sourceIds,
    event_page_ids: [],
    emission_count: sourceIds.length,
    accepted_count: sourceIds.length,
    pending_count: 0,
    closure_state: "accepted",
    target_declared_by_stream_ids: [],
    ...overrides
  };
}

// A three-source world with a real input channel, a governance config, an
// open event, a proposal, one two-source knowledge page and loose perimeter
// pages — every §19.4 concern in one fixture.
function fixture(): { nodes: GraphNode[]; edges: GraphEdge[]; payload: SourceFoundationPayload } {
  const nodes: GraphNode[] = [
    node("world-root", "system", { page_type: "root_entity" }),
    node("source-a", "documentos", { page_type: "source" }),
    node("source-b", "documentos", { page_type: "source" }),
    node("source-c", "projetos", { page_type: "source" }),
    node("channel-inbox", "documentos", { page_type: "input_channel" }),
    node("config-a", "documentos", { page_type: "source_config" }),
    node("source-registry", "sistema", { page_type: "source_registry" }),
    node("event-1", "documentos", { page_type: "ingestion_event" }),
    node("event-2", "documentos", { page_type: "ingestion_event" }),
    node("proposal-1", "documentos", { page_type: "proposal", approved_state: "proposal" }),
    node("note-multi", "projetos"),
    node("note-single", "projetos"),
    node("insight-declared", "projetos"),
    node("loose-1", "casa"),
    node("loose-2", "casa"),
    node("loose-3", "casa")
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
        stream_ids: ["stream:source-a:s1", "stream:source-a:s2"],
        pipeline_ids: ["pipeline:source-a:content"],
        emission_ids: ["emission:a1000000000000000000", "emission:a2000000000000000000"],
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
      }
    ],
    emissions: [
      emission("a1", "source-a", { event_page_id: "event-1", target_page_id: "note-multi", closure_state: "accepted" }),
      emission("a2", "source-a", { proposal_page_ids: ["proposal-1"], target_page_id: null, closure_state: "pending" }),
      emission("b1", "source-b", { target_page_id: "note-multi", closure_state: "pending" }),
      emission("c1", "source-c", { target_page_id: "note-single", closure_state: "accepted" }),
      emission("e2", "source-b", { event_page_id: "event-2", target_page_id: null, closure_state: "unknown" })
    ],
    targets: [
      target("note-multi", ["source-a", "source-b"], { accepted_count: 1, pending_count: 1, closure_state: "mixed" }),
      target("note-single", ["source-c"]),
      target("insight-declared", ["source-a"], {
        emission_count: 0,
        accepted_count: 0,
        pending_count: 0,
        closure_state: "declared_only",
        target_declared_by_stream_ids: ["stream:source-a:s1"]
      })
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
        gap_id: `gap:event_without_closure:${"b".repeat(16)}`,
        code: "event_without_closure",
        severity: "warning",
        subject_ref: "event-2",
        related_refs: [],
        message_key: "source_foundation.diagnostics.event_without_closure",
        count: 1
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

function request(over: Partial<SourceFoundationWorldRequest> = {}): SourceFoundationWorldRequest {
  const { nodes, edges, payload } = fixture();
  return {
    perspective: "sources",
    nodes,
    edges,
    centerId: "world-root",
    maxNodes: 60,
    snapshotAt: SNAPSHOT,
    sourceFoundation: payload,
    ...over
  };
}

function nodeById(layout: ReturnType<typeof computeWorldLayout>, id: string) {
  const found = layout.nodes.find((item) => item.id === id);
  expect(found, `expected node ${id} in layout`).toBeTruthy();
  return found!;
}

describe("source foundation layout", () => {
  it("places every role in its exact band and never lets state cross bands", () => {
    const layout = computeWorldLayout(request());

    const core = nodeById(layout, "world-root");
    expect(core.isRoot).toBe(true);
    expect(core.plane).toBe("core");
    expect(core.foundationRole).toBe("core-anchor");
    expect(core.position).toEqual([0, SOURCE_FOUNDATION_LEVELS.core, 0]);

    const expectations: [string, string, string][] = [
      ["source-a", "foundation", "source-station"],
      ["source-b", "foundation", "source-station"],
      ["source-c", "foundation", "source-station"],
      ["channel-inbox", "foundation", "channel-station"],
      ["config-a", "foundation", "governance-control"],
      ["source-registry", "foundation", "governance-control"],
      ["event-1", "provenance", "provenance-page"],
      ["event-2", "provenance", "provenance-page"],
      ["proposal-1", "provenance", "provenance-page"],
      ["note-multi", "knowledge", "knowledge-page"],
      ["note-single", "knowledge", "knowledge-page"],
      ["insight-declared", "knowledge", "knowledge-page"],
      ["loose-1", "knowledge", "knowledge-page"]
    ];
    expectations.forEach(([id, plane, role]) => {
      const item = nodeById(layout, id);
      expect(item.plane, id).toBe(plane);
      expect(item.foundationRole, id).toBe(role);
    });
    // Band invariance: EVERY node sits within the bounded lift of its band —
    // including proposal-1, whose global +0.5 float is re-expressed (§10.12).
    layout.nodes.forEach((item) => {
      const level = SOURCE_FOUNDATION_LEVELS[item.plane!];
      expect(Math.abs(item.position[1] - level), item.id).toBeLessThanOrEqual(SOURCE_FOUNDATION_WITHIN_BAND_LIFT + 1e-9);
    });
    const proposal = nodeById(layout, "proposal-1");
    expect(proposal.position[1]).toBeCloseTo(SOURCE_FOUNDATION_LEVELS.provenance + SOURCE_FOUNDATION_WITHIN_BAND_LIFT, 4);
    // The upper-profile ground guides never mount here: no guides are emitted
    // and the plane profile carries the foundation-first occlusion policy.
    expect(layout.guides).toEqual([]);
    expect(layout.planeProfile).toEqual({
      active: "foundation",
      levels: SOURCE_FOUNDATION_LEVELS,
      cameraHemisphere: "lower",
      transitionPath: "outer_arc",
      occlusionPolicy: "foundation-first",
      labelPolicy: "camera-facing"
    });
  });

  it("is deterministic in X/Z: reversed input order produces identical output", () => {
    const base = request();
    const first = computeWorldLayout(base);
    const reversed = computeWorldLayout({
      ...base,
      nodes: [...base.nodes].reverse(),
      edges: [...base.edges].reverse(),
      sourceFoundation: {
        ...base.sourceFoundation,
        stations: [...base.sourceFoundation.stations].reverse(),
        streams: [...base.sourceFoundation.streams].reverse(),
        emissions: [...base.sourceFoundation.emissions].reverse(),
        targets: [...base.sourceFoundation.targets].reverse(),
        diagnostics: [...base.sourceFoundation.diagnostics].reverse()
      }
    });
    expect(JSON.stringify(first)).toEqual(JSON.stringify(reversed));
  });

  it("preserves many-to-many provenance and places multi-source pages at a stable weighted barycenter", () => {
    const layout = computeWorldLayout(request());
    const multi = nodeById(layout, "note-multi");
    expect(multi.sourceIds).toEqual(["source-a", "source-b"]);
    expect(multi.traceCount).toBe(2);

    const bundles = (layout.foundationPrimitives ?? []).filter((primitive) => primitive.kind === "flow-bundle");
    const multiBundles = bundles.filter((bundle) => bundle.pageIds.includes("note-multi"));
    expect(multiBundles.map((bundle) => bundle.id).sort()).toEqual([
      "flow:source-a:note-multi",
      "flow:source-b:note-multi"
    ]);

    // accepted (weight 2, source-a) vs pending (weight 1, source-b).
    const stationA = nodeById(layout, "source-a");
    const stationB = nodeById(layout, "source-b");
    const expectedX = (stationA.position[0] * 2 + stationB.position[0]) / 3;
    const expectedZ = (stationA.position[2] * 2 + stationB.position[2]) / 3;
    expect(multi.position[0]).toBeCloseTo(expectedX, 3);
    expect(multi.position[2]).toBeCloseTo(expectedZ, 3);
  });

  it("keeps config and registry as governance controls, never emitter stations", () => {
    const layout = computeWorldLayout(request());
    const config = nodeById(layout, "config-a");
    expect(config.foundationRole).toBe("governance-control");
    expect(config.sourceIds).toEqual(["source-a"]);
    const primitives = layout.foundationPrimitives ?? [];
    // No ports, lanes or emission bundles ever attach to a governance page.
    expect(
      primitives.filter(
        (primitive) => primitive.kind !== "governance-plate" && primitive.sourceIds.includes("config-a")
      )
    ).toEqual([]);
    // The config is visible as a page node, so no duplicate plate primitive.
    expect(primitives.filter((primitive) => primitive.kind === "governance-plate")).toEqual([]);
  });

  it("reports honest hidden counts and gives stations priority over everything else", () => {
    const tight = computeWorldLayout(request({ maxNodes: 5 }));
    expect(tight.totals.total).toBe(16);
    expect(tight.totals.shown + tight.totals.hidden).toBe(tight.totals.total);
    const starSum = tight.clusterStars.reduce((sum, star) => sum + star.count, 0);
    expect(starSum).toBe(tight.totals.hidden);
    // Budget 5 = center + 3 stations + 1: stations always land first.
    ["source-a", "source-b", "source-c"].forEach((id) => nodeById(tight, id));

    // Port budget: source-b has 8 streams -> 5 real ports + one aggregate
    // carrying the TRUE hidden stream count.
    const layout = computeWorldLayout(request());
    const ports = (layout.foundationPrimitives ?? []).filter(
      (primitive): primitive is SourceStreamPort => primitive.kind === "stream-port" && primitive.sourceIds.includes("source-b")
    );
    expect(ports).toHaveLength(6);
    const overflow = ports.find((port) => port.streamId === null);
    expect(overflow?.hiddenCount).toBe(3);
    expect(ports.filter((port) => port.streamId !== null)).toHaveLength(5);
  });

  it("never moves positions when overlay metrics or freshness tone change", () => {
    const base = request();
    const first = computeWorldLayout(base);
    const recolored = computeWorldLayout({
      ...base,
      nodes: base.nodes.map((item) => ({
        ...item,
        overlay_metrics: {
          attention: { state: "high", count: 9, value: 9 },
          freshness: { state: "stale", count: 9, value: 9 },
          actions: { state: "open", count: 9, value: 9 },
          ownership: { state: "owned", count: 1, value: 1 },
          evidence: { state: "gap", count: 0, value: 0 },
          quality: { state: "risk", count: 3, value: 3 }
        } as GraphNode["overlay_metrics"]
      }))
    });
    const positions = (layout: ReturnType<typeof computeWorldLayout>) =>
      Object.fromEntries(layout.nodes.map((item) => [item.id, item.position]));
    expect(positions(recolored)).toEqual(positions(first));
  });

  it("exposes only real page ids as nodes; derived primitive ids never collide or become pages", () => {
    const base = request();
    const layout = computeWorldLayout(base);
    const graphIds = new Set(base.nodes.map((item) => item.id));
    layout.nodes.forEach((item) => expect(graphIds.has(item.id), item.id).toBe(true));

    const primitiveIds = (layout.foundationPrimitives ?? []).map((primitive) => primitive.id);
    expect(new Set(primitiveIds).size).toBe(primitiveIds.length);
    primitiveIds.forEach((id) => {
      expect(graphIds.has(id), id).toBe(false);
      expect(/^(?:station|channel|stream|pipeline|emission|gap|port|flow):/.test(id), id).toBe(true);
    });

    // Same page ids across views: the quadrants projection of the same world
    // reuses the same identities — the view morphs geometry, not the universe.
    const quadrants = computeWorldLayout({ ...base, perspective: "quadrants" } as WorldRequest);
    quadrants.nodes
      .filter((item) => !item.isGroup)
      .forEach((item) => expect(graphIds.has(item.id), item.id).toBe(true));
  });

  it("marks the typed gaps as a ring of markers with safe codes and honest counts", () => {
    const layout = computeWorldLayout(request());
    const gaps = (layout.foundationPrimitives ?? []).filter((primitive) => primitive.kind === "gap-marker");
    expect(gaps.map((gap) => gap.kind === "gap-marker" && gap.code).sort()).toEqual([
      "event_without_closure",
      "multiple_sources_supported",
      "target_without_emission"
    ]);
    gaps.forEach((gap) => {
      expect(gap.labelKey.startsWith("source_foundation.diagnostics.")).toBe(true);
      if (gap.kind === "gap-marker") expect(gap.count).toBeGreaterThanOrEqual(1);
    });
  });

  it("falls back to the unchanged v8 sources layout when the payload is absent", () => {
    const { nodes, edges } = fixture();
    const legacyRequest: WorldRequest = {
      perspective: "sources",
      nodes,
      edges,
      centerId: "world-root",
      maxNodes: 60,
      snapshotAt: SNAPSHOT
    };
    const legacy = computeWorldLayout(legacyRequest);
    expect(legacy.planeProfile).toBeUndefined();
    expect(legacy.foundationPrimitives).toBeUndefined();
    expect(legacy.groups.map((group) => group.key)).toEqual([
      "source-emitters",
      "emitted-evidence",
      "unconsolidated"
    ]);
    expect(nodeById(legacy, "world-root").position).toEqual([0, 0, 0]);
  });

  it("lays out the shipped demo snapshot without ever leaving the band contract", () => {
    const read = <T,>(name: string): T =>
      JSON.parse(readFileSync(resolve(__dirname, `../../public/sample-snapshot/${name}`), "utf8")) as T;
    const graph = read<{ nodes: GraphNode[]; edges: GraphEdge[] }>("graph.json");
    const payload = read<SourceFoundationPayload>("source_foundation.json");
    const layout = computeWorldLayout({
      perspective: "sources",
      nodes: graph.nodes,
      edges: graph.edges,
      maxNodes: 160,
      snapshotAt: SNAPSHOT,
      sourceFoundation: payload
    });
    expect(layout.planeProfile?.active).toBe("foundation");
    expect(layout.totals.shown + layout.totals.hidden).toBe(layout.totals.total);
    expect(layout.totals.total).toBe(graph.nodes.length);
    const starSum = layout.clusterStars.reduce((sum, star) => sum + star.count, 0);
    expect(starSum).toBe(layout.totals.hidden);
    const graphIds = new Set(graph.nodes.map((item) => item.id));
    layout.nodes.forEach((item) => {
      expect(graphIds.has(item.id), item.id).toBe(true);
      expect(item.plane, item.id).toBeTruthy();
      const level = SOURCE_FOUNDATION_LEVELS[item.plane!];
      expect(Math.abs(item.position[1] - level), item.id).toBeLessThanOrEqual(SOURCE_FOUNDATION_WITHIN_BAND_LIFT + 1e-9);
    });
    // Every station of the shipped payload with a real page lands as a station.
    const stationRoles = new Set(
      layout.nodes.filter((item) => item.foundationRole === "source-station").map((item) => item.id)
    );
    expect(stationRoles.size).toBeGreaterThan(0);
    stationRoles.forEach((id) => expect(payload.stations.some((entry) => entry.canonical_page_id === id)).toBe(true));
  });

  it("scopes the family:source drill to stations without inventing groups", () => {
    const layout = computeWorldLayout(request({ group: "family:source" }));
    expect(layout.groups).toEqual([]);
    expect(layout.nodes.map((item) => item.id).sort()).toEqual(["source-a", "source-b", "source-c", "world-root"]);
    expect(layout.totals).toEqual({ total: 4, shown: 4, hidden: 0 });
  });
});
