import { describe, expect, it } from "vitest";
import { QUADRANT_CENTER_ANGLE, SCENE_FACETS, homeQuadrant, sceneFacetOf } from "./facets";

describe("scene facets (frontend mirror of wiki_core/facets.py)", () => {
  it("exposes exactly the four lenses in quadrant order q1..q4", () => {
    expect([...SCENE_FACETS]).toEqual(["intencao", "pratica", "relacoes", "sistemas"]);
  });

  it("buckets by page_type first — one lens per quadrant", () => {
    expect(sceneFacetOf("decision", undefined)).toBe("intencao");
    // Perception (insight/claim) is interior-individual (q1) -> Identity and intent.
    expect(sceneFacetOf("insight", undefined)).toBe("intencao");
    expect(sceneFacetOf("claim", undefined)).toBe("intencao");
    expect(sceneFacetOf("action", undefined)).toBe("pratica");
    expect(sceneFacetOf("person", undefined)).toBe("relacoes");
    expect(sceneFacetOf("meeting", undefined)).toBe("relacoes");
    // Sources/logs are exterior traces of the wiki's work (q2).
    expect(sceneFacetOf("source", undefined)).toBe("pratica");
    expect(sceneFacetOf("source_catalog", undefined)).toBe("pratica");
    expect(sceneFacetOf("source_registry", undefined)).toBe("pratica");
    expect(sceneFacetOf("system_log", undefined)).toBe("pratica");
    expect(sceneFacetOf("ingestion_event", undefined)).toBe("pratica");
    expect(sceneFacetOf("dashboard", undefined)).toBe("pratica");
    expect(sceneFacetOf("ontology_index", undefined)).toBe("pratica");
    // Systems and governance (q4) are coordination machinery.
    expect(sceneFacetOf("operational_rule", undefined)).toBe("sistemas");
    expect(sceneFacetOf("context_hub", undefined)).toBe("sistemas");
    expect(sceneFacetOf("process", undefined)).toBe("sistemas");
  });

  it("falls back to the typed edge when the page_type is unknown", () => {
    expect(sceneFacetOf("context_note", "source_ref")).toBe("pratica");
    expect(sceneFacetOf("context_note", "decision")).toBe("intencao");
    expect(sceneFacetOf(undefined, "claim")).toBe("intencao");
  });

  it("treats unknown neighbors as no lens (null)", () => {
    expect(sceneFacetOf("context_note", "moc_parent")).toBeNull();
    expect(sceneFacetOf("context_note", "markdown_link")).toBeNull();
    expect(sceneFacetOf("root_entity", undefined)).toBeNull();
    expect(sceneFacetOf(undefined, undefined)).toBeNull();
  });

  it("page_type wins over a conflicting edge", () => {
    expect(sceneFacetOf("decision", "markdown_link")).toBe("intencao");
  });
});

describe("homeQuadrant — a page's OWN quadrant (Quadrants perspective)", () => {
  it("keys on page_type only, never an edge; root/unknown = null (q0-core)", () => {
    // Mirrors wiki_core/facets.py test_home_quadrant_* exactly (front/back parity).
    expect(homeQuadrant("decision")).toBe("intencao");
    expect(homeQuadrant("action")).toBe("pratica");
    expect(homeQuadrant("person")).toBe("relacoes");
    expect(homeQuadrant("source")).toBe("pratica");
    expect(homeQuadrant("system_log")).toBe("pratica");
    expect(homeQuadrant("source_catalog")).toBe("pratica");
    expect(homeQuadrant("root_index")).toBe("pratica");
    expect(homeQuadrant("ontology_index")).toBe("pratica");
    expect(homeQuadrant("operational_rule")).toBe("sistemas");
    expect(homeQuadrant("context_hub")).toBe("sistemas");
    expect(homeQuadrant("root_entity")).toBeNull();
    expect(homeQuadrant("totally_unknown_type")).toBeNull();
    expect(homeQuadrant(undefined)).toBeNull();
  });

  it("a registry override wins (a wiki can editorially place a type)", () => {
    expect(homeQuadrant("context_note", { context_note: "relacoes" })).toBe("relacoes");
  });

  it("exposes four fixed Wilber/AQAL sector bearings, one per facet", () => {
    const angles = SCENE_FACETS.map((f) => QUADRANT_CENTER_ANGLE[f]);
    expect(angles).toHaveLength(4);
    expect(new Set(angles).size).toBe(4);
    expect(QUADRANT_CENTER_ANGLE.intencao).toBe((5 * Math.PI) / 4);
    expect(QUADRANT_CENTER_ANGLE.pratica).toBe((7 * Math.PI) / 4);
    expect(QUADRANT_CENTER_ANGLE.relacoes).toBe((3 * Math.PI) / 4);
    expect(QUADRANT_CENTER_ANGLE.sistemas).toBe(Math.PI / 4);
  });
});
