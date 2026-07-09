import { describe, expect, it } from "vitest";
import type { AnchorRecord } from "../types";
import { installVisualPrimitiveRegistry, regionPayloadByKey, resolvePrimitiveForSlot, resolvedPrimitiveDiagnostics, validateVisualGrammar } from "./visualPrimitives";
import { createDefaultKernel } from "../world/registries/RegistryKernel";

const record: AnchorRecord = {
  stack: [],
  interface: {
    views: { available: ["quadrants"], default: "quadrants" },
    missions: { providers: [], weather_contrib: false, quiet: false },
    create: { catalog: [], arrangement: "by_quadrant", obligations_first: true, obligations: [], disabled_reason: "" },
    intake: { forms: [] },
    score: { loops: [], no_leaderboard: true },
    regions: { active: true, visual_pack: "region_operations" },
    has_quadrants: true,
    has_relations: false
  },
  identity: { landmark: "", motif: "none", ambient: "none", horizon_label: "title", horizon_text: "Root", context: "demo" },
  visual_grammar: {
    schema_version: "wiki.visual_grammar.v1",
    default_pack: "evidence_first",
    packs: {
      evidence_first: {
        slots: {
          "region.card": "region_card",
          "region.rail": "attention_rail",
          "fallback.card": "region_work_card"
        }
      }
    }
  },
  derived: {
    missions: [],
    warnings: [],
    region_groups: {
      schema_version: "wiki.region_groups.v1",
      anchor: "root",
      groups: [
        {
          id: "quadrant:pratica",
          kind: "quadrant",
          label_key: "pratica",
          purpose: "verify",
          visual_role: "quadrant",
          member_ids: ["a"],
          summary: { total: 1, shown: 1, hidden: 0, stale: 0, proposal: 0, risk: 0, raw: 1, unsourced: 0, open_actions: 0, source_backed: 1 },
          type_mix: [{ page_type: "source", family: "source", count: 1 }],
          attention_hints: [{ kind: "raw", count: 1 }],
          action_hints: [{ kind: "inspect_sources", label_key: "region.action.inspectSources", count: 1 }],
          visual: {
            grammar_id: "wiki.visual_grammar.v1",
            pack_id: "evidence_first",
            slots: { "region.card": "region_card", "fallback.card": "region_work_card" },
            emphasis: ["attention"]
          }
        }
      ]
    }
  }
};

describe("visual primitive registry", () => {
  it("indexes region payloads by label and id", () => {
    const map = regionPayloadByKey(record);
    expect(map.get("pratica")?.summary.raw).toBe(1);
    expect(map.get("quadrant:pratica")?.visual.pack_id).toBe("evidence_first");
  });

  it("resolves slots through the region and falls back safely", () => {
    const region = regionPayloadByKey(record).get("pratica");
    expect(resolvePrimitiveForSlot(record, region, "fallback.card").id).toBe("region_work_card");
    expect(resolvePrimitiveForSlot(record, region, "region.rail").id).toBe("attention_rail");
  });

  it("exposes diagnostics for the Blocks dock", () => {
    const diagnostics = resolvedPrimitiveDiagnostics(record);
    expect(diagnostics.find((entry) => entry.slot === "region.card")?.primitive).toBe("region_card");
    expect(diagnostics.every((entry) => entry.purpose.length > 0)).toBe(true);
  });

  it("installs the closed primitive vocabulary into the runtime registry", () => {
    const kernel = createDefaultKernel();
    installVisualPrimitiveRegistry(kernel);
    expect(kernel.visualPrimitives.require("region_work_card").dataField).toContain("action_hints");
    expect(() => kernel.visualPrimitives.require("arbitrary_css")).toThrow(/Unknown visual primitive/);
  });

  it("rejects unknown packs, slots and incompatible primitive placement", () => {
    const invalid = structuredClone(record);
    invalid.visual_grammar!.default_pack = "made_up";
    invalid.visual_grammar!.packs.made_up = { slots: { "reader.badge": "attention_rail", "bad.slot": "unknown" } };
    expect(validateVisualGrammar(invalid)).toEqual(expect.arrayContaining([
      "unknown visual pack 'made_up'",
      "unknown visual slot 'bad.slot'",
      "unknown visual primitive 'unknown'",
      "primitive 'attention_rail' cannot render in slot 'reader.badge'"
    ]));
  });
});
