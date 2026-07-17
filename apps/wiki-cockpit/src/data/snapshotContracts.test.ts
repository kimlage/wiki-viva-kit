import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { SourceFoundationPayload } from "../types";
import { isPageEntity } from "../world/contracts";
import type { PageEntityIndex } from "../world/contracts";
import {
  SOURCE_FOUNDATION_DERIVED_ID_PATTERN,
  SOURCE_FOUNDATION_VERSION,
  experiencePackContractErrors,
  sourceFoundationContractErrors,
  temporalGraphContractErrors
} from "./snapshotContracts";

const temporalVersions = {
  temporal_graph: "wiki_temporal_graph.v1",
  temporal_event: "wiki_temporal_event.v1"
};

function emptyTemporalGraph() {
  const fingerprint = "a".repeat(64);
  const range = {
    from: null,
    to: null,
    from_precision: null,
    to_precision: null,
    event_count: 0,
    dated_count: 0,
    undated_count: 0,
    basis: "full_result"
  };
  return {
    schema_version: "wiki_temporal_graph.v1",
    event_schema_version: "wiki_temporal_event.v1",
    repo_id: "public-demo",
    revision: `sha256:${fingerprint}`,
    generated_at: "2026-07-11T12:00:00Z",
    event_count: 0,
    total_count: 0,
    returned_count: 0,
    truncated: false,
    next_cursor: null,
    page: { offset: 0, limit: 0, remaining_count: 0, fingerprint },
    range,
    returned_range: { ...range, basis: "returned_page" },
    summary: {
      scope: "full_result",
      event_count: 0,
      by_kind: {},
      by_context: {},
      conflict_count: 0,
      imprecise_count: 0,
      diagnostic_count: 0
    },
    diagnostics: [],
    events: []
  };
}

function temporalEvent() {
  return {
    schema_version: "wiki_temporal_event.v1",
    event_id: "evt_snapshot_recorded_0123456789abcdef01234567",
    kind: "snapshot_recorded",
    subject_refs: ["system:wiki-viva"],
    context_refs: ["context:system"],
    occurred_at: null,
    recorded_at: "2026-07-11T12:00:00Z",
    valid_from: null,
    valid_to: null,
    created_at: null,
    due_at: null,
    completed_at: null,
    verified_at: null,
    ingested_at: null,
    superseded_at: null,
    precision: { recorded_at: "instant" },
    actor: null,
    source_refs: [],
    evidence_refs: [],
    caused_by: [],
    supersedes: [],
    before: {},
    after: {},
    confidence: "confirmed",
    visibility: "private",
    origin: { adapter: "frontend_fixture.v1" },
    temporal_conflicts: [],
    anchor: { field: "recorded_at", value: "2026-07-11T12:00:00Z", precision: "instant" }
  };
}

function populatedTemporalGraph() {
  const fingerprint = "b".repeat(64);
  const event = temporalEvent();
  const range = {
    from: event.anchor.value,
    to: event.anchor.value,
    from_precision: event.anchor.precision,
    to_precision: event.anchor.precision,
    event_count: 1,
    dated_count: 1,
    undated_count: 0,
    basis: "full_result"
  };
  return {
    schema_version: "wiki_temporal_graph.v1",
    event_schema_version: "wiki_temporal_event.v1",
    repo_id: "public-demo",
    revision: `sha256:${fingerprint}`,
    generated_at: "2026-07-11T12:00:00Z",
    event_count: 1,
    total_count: 1,
    returned_count: 1,
    truncated: false,
    next_cursor: null,
    page: { offset: 0, limit: 1, remaining_count: 0, fingerprint },
    range,
    returned_range: { ...range, basis: "returned_page" },
    summary: {
      scope: "full_result",
      event_count: 1,
      by_kind: { snapshot_recorded: 1 },
      by_context: { "context:system": 1 },
      conflict_count: 0,
      imprecise_count: 0,
      diagnostic_count: 0
    },
    diagnostics: [],
    events: [event]
  };
}

describe("source foundation contract (§19.3)", () => {
  const shippedPayload = (): SourceFoundationPayload =>
    JSON.parse(
      readFileSync(resolve(__dirname, "../../public/sample-snapshot/source_foundation.json"), "utf8")
    ) as SourceFoundationPayload;
  const versions = { source_foundation: SOURCE_FOUNDATION_VERSION };

  it("accepts the shipped sample topology exactly as built by the backend", () => {
    const payload = shippedPayload();
    expect(payload.stations.length).toBeGreaterThan(0);
    expect(sourceFoundationContractErrors(payload, versions)).toEqual([]);
  });

  it("rejects an unknown version, the degraded error marker and malformed primitive ids", () => {
    const payload = shippedPayload();
    expect(
      sourceFoundationContractErrors({ ...payload, schema_version: "wiki_web_source_foundation.v2" }, versions)
    ).toContain("source foundation schema_version is unsupported");
    expect(
      sourceFoundationContractErrors(payload, { source_foundation: "wiki_web_source_foundation.v2" })
    ).toContain("manifest source foundation version is unsupported");
    expect(sourceFoundationContractErrors({ error: "source_foundation_unavailable" }, versions)).toContain(
      "source foundation payload is an error marker"
    );
    const malformed = {
      ...payload,
      stations: [{ ...payload.stations[0], station_id: "not-a-derived-id" }]
    };
    expect(sourceFoundationContractErrors(malformed, versions)).toContain(
      "source foundation stations[0] is malformed"
    );
    // A station whose canonical page ref is itself a derived id is a lie.
    const derivedPage = {
      ...payload,
      stations: [{ ...payload.stations[0], canonical_page_id: "station:fake" }]
    };
    expect(sourceFoundationContractErrors(derivedPage, versions)).toContain(
      "source foundation stations[0] is malformed"
    );
  });

  it("never leaks payload values into error messages", () => {
    const payload = shippedPayload();
    const poisoned = {
      ...payload,
      topology_sha256: "TOKEN-sk-1234567890",
      streams: [{ ...payload.streams[0], stream_id: "https://secret.example/export?token=abc" }]
    };
    const errors = sourceFoundationContractErrors(poisoned, versions);
    expect(errors.length).toBeGreaterThan(0);
    errors.forEach((error) => {
      expect(error).not.toContain("TOKEN-sk-1234567890");
      expect(error).not.toContain("secret.example");
    });
  });

  it("keeps derived ids out of the page entity universe", () => {
    const payload = shippedPayload();
    const index: PageEntityIndex = new Map([
      ["source-agenda", { id: "source-agenda", pageType: "source" }]
    ]);
    payload.stations.forEach((station) => {
      expect(SOURCE_FOUNDATION_DERIVED_ID_PATTERN.test(station.station_id)).toBe(true);
      expect(isPageEntity(index, station.station_id)).toBe(false);
    });
    payload.diagnostics.forEach((diagnostic) => {
      expect(isPageEntity(index, diagnostic.gap_id)).toBe(false);
    });
  });
});

describe("snapshot capability contract negotiation", () => {
  it("accepts the supported temporal envelope and rejects future or malformed payloads", () => {
    expect(temporalGraphContractErrors(emptyTemporalGraph(), temporalVersions)).toEqual([]);
    expect(temporalGraphContractErrors(
      { ...emptyTemporalGraph(), schema_version: "wiki_temporal_graph.v2" },
      { ...temporalVersions, temporal_graph: "wiki_temporal_graph.v2" }
    ).some((error) => error.includes("unsupported"))).toBe(true);
    expect(temporalGraphContractErrors({ ...emptyTemporalGraph(), events: {} }, temporalVersions)).toContain(
      "temporal graph events must be an array"
    );
    expect(temporalGraphContractErrors({
      ...emptyTemporalGraph(),
      event_count: 2,
      total_count: 2,
      returned_count: 1,
      truncated: true,
      next_cursor: "cursor",
      page: { offset: 0, limit: 1, remaining_count: 1, fingerprint: "a".repeat(64) },
      events: []
    }, temporalVersions)).toContain("static temporal graph must be complete and non-truncated");
  });

  it("rejects equivalent temporal envelope, summary, diagnostic, event and cross-field mutations", () => {
    expect(temporalGraphContractErrors(populatedTemporalGraph(), temporalVersions)).toEqual([]);
    const namespaced = populatedTemporalGraph();
    namespaced.events[0].kind = "study-research.learning-captured";
    Object.assign(namespaced.events[0], { lane: "source" });
    Object.assign(namespaced.summary, {
      by_kind: { "study-research.learning-captured": 1 } as Record<string, number>
    });
    expect(temporalGraphContractErrors(namespaced, temporalVersions)).toEqual([]);
    for (const kind of ["action_state_canonicalized", "action_contract_updated"]) {
      const statePreserving = populatedTemporalGraph();
      statePreserving.events[0].kind = kind;
      Object.assign(statePreserving.summary, {
        by_kind: { [kind]: 1 } as Record<string, number>
      });
      expect(temporalGraphContractErrors(statePreserving, temporalVersions)).toEqual([]);
    }
    const cases: { label: string; mutate: (payload: ReturnType<typeof populatedTemporalGraph>) => void }[] = [
      { label: "extra envelope key", mutate: (payload) => { Object.assign(payload, { invented: true }); } },
      { label: "missing page fingerprint", mutate: (payload) => { delete (payload.page as Partial<typeof payload.page>).fingerprint; } },
      { label: "range count drift", mutate: (payload) => { payload.range.dated_count = 0; } },
      { label: "returned range basis drift", mutate: (payload) => { payload.returned_range.basis = "full_result"; } },
      { label: "empty summary", mutate: (payload) => { Object.assign(payload, { summary: {} }); } },
      { label: "summary kind drift", mutate: (payload) => { payload.summary.by_kind.snapshot_recorded = 2; } },
      {
        label: "malformed diagnostic",
        mutate: (payload) => {
          Object.assign(payload, { diagnostics: [{ code: "temporal_adapter_rejected" }] });
          payload.summary.diagnostic_count = 1;
        }
      },
      { label: "unknown event kind", mutate: (payload) => { payload.events[0].kind = "invented_event"; } },
      { label: "unknown event lane", mutate: (payload) => { Object.assign(payload.events[0], { lane: "invented" }); } },
      { label: "invalid ref", mutate: (payload) => { payload.events[0].subject_refs = ["not a typed ref"]; } },
      { label: "dangling cause", mutate: (payload) => { Object.assign(payload.events[0], { caused_by: ["event:missing-event"] }); } },
      {
        label: "invalid date",
        mutate: (payload) => {
          payload.events[0].recorded_at = "2026-02-30";
          payload.events[0].precision.recorded_at = "day";
          payload.events[0].anchor.value = "2026-02-30";
          payload.events[0].anchor.precision = "day";
        }
      },
      { label: "precision mismatch", mutate: (payload) => { payload.events[0].precision.recorded_at = "day"; } },
      { label: "anchor mismatch", mutate: (payload) => { payload.events[0].anchor.field = "occurred_at"; } },
      { label: "extra event key", mutate: (payload) => { Object.assign(payload.events[0], { invented: true }); } }
    ];
    for (const fixture of cases) {
      const payload = structuredClone(populatedTemporalGraph());
      fixture.mutate(payload);
      expect(temporalGraphContractErrors(payload, temporalVersions).length, fixture.label).toBeGreaterThan(0);
    }
  });

  it("accepts composed pack slots and fails closed on unsupported or malformed catalogs", () => {
    const composition = {
      schema_version: "wiki_experience_pack_composition.v1",
      core_version: "8.0.0",
      packs: [{ id: "study-research", version: "0.1.0" }],
      block_packages: ["quadrant_lenses"],
      slots: {
        views: [{ pack: "study-research", slot: "view.knowledge", contribution: "study-research.concept-graph", mode: "append" }],
        commands: [],
        operations: [],
        timelines: []
      },
      presentation: {
        default_locale: "en",
        locales: {
          en: { "study-research": "Study and Research", "study-research.concept-graph": "Concept graph" },
          "pt-BR": { "study-research": "Estudos e pesquisa", "study-research.concept-graph": "Grafo de conceitos" }
        }
      },
      composition_sha256: "0".repeat(64)
    };
    const versions = { experience_pack_composition: "wiki_experience_pack_composition.v1" };
    expect(experiencePackContractErrors(composition, versions)).toEqual([]);
    expect(experiencePackContractErrors(composition, { experience_pack_composition: "wiki_experience_pack_composition.v2" })
      .some((error) => error.includes("unsupported"))).toBe(true);
    expect(experiencePackContractErrors({ ...composition, slots: { views: "bad" } }, versions).length).toBeGreaterThan(0);

    const invalidCompositions = [
      {
        ...composition,
        packs: [composition.packs[0], composition.packs[0]]
      },
      {
        ...composition,
        packs: [{ id: "study-research", version: "0.1.0-rc.1" }]
      },
      {
        ...composition,
        presentation: { ...composition.presentation, locales: { en: composition.presentation.locales.en } }
      },
      {
        ...composition,
        slots: {
          ...composition.slots,
          views: [{ ...composition.slots.views[0], pack: "missing-pack", contribution: "missing-pack.view" }]
        }
      },
      {
        ...composition,
        slots: {
          ...composition.slots,
          views: [{ ...composition.slots.views[0], contribution: "other-pack.view" }]
        }
      },
      {
        ...composition,
        slots: {
          ...composition.slots,
          views: [composition.slots.views[0], { ...composition.slots.views[0] }]
        }
      },
      {
        ...composition,
        slots: {
          ...composition.slots,
          views: [
            { ...composition.slots.views[0], slot: "view.zeta", contribution: "study-research.zeta" },
            { ...composition.slots.views[0], slot: "view.alpha", contribution: "study-research.alpha" }
          ]
        }
      },
      {
        ...composition,
        slots: {
          ...composition.slots,
          views: [
            { ...composition.slots.views[0], contribution: "study-research.alpha", mode: "exclusive" },
            { ...composition.slots.views[0], contribution: "study-research.beta", mode: "append" }
          ]
        }
      }
    ];
    for (const invalid of invalidCompositions) {
      expect(experiencePackContractErrors(invalid, versions).length).toBeGreaterThan(0);
    }
  });
});
