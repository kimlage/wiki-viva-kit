import { describe, expect, it } from "vitest";
import { QUADRANT_CENTER_ANGLE, SCENE_FACETS, homeQuadrant, sceneFacetOf } from "./facets";

describe("scene facets (frontend mirror of wiki_core/facets.py)", () => {
  it("exposes exactly the four lenses in quadrant order q1..q4", () => {
    expect([...SCENE_FACETS]).toEqual(["intencao", "pratica", "relacoes", "sistemas"]);
  });

  it("buckets by page_type first — one lens per quadrant", () => {
    expect(sceneFacetOf("decision", undefined)).toBe("intencao");
    // Perception (insight/claim) is interior-individual (q1) → Intention lens.
    expect(sceneFacetOf("insight", undefined)).toBe("intencao");
    expect(sceneFacetOf("claim", undefined)).toBe("intencao");
    expect(sceneFacetOf("action", undefined)).toBe("pratica");
    expect(sceneFacetOf("person", undefined)).toBe("relacoes");
    expect(sceneFacetOf("meeting", undefined)).toBe("relacoes");
    // Systems/processes (q4) are their own lens.
    expect(sceneFacetOf("process", undefined)).toBe("sistemas");
    expect(sceneFacetOf("source", undefined)).toBe("sistemas");
    expect(sceneFacetOf("dashboard", undefined)).toBe("sistemas");
  });

  it("falls back to the typed edge when the page_type is unknown", () => {
    expect(sceneFacetOf("context_note", "source_ref")).toBe("sistemas");
    expect(sceneFacetOf("context_note", "decision")).toBe("intencao");
    expect(sceneFacetOf(undefined, "claim")).toBe("intencao");
  });

  it("treats structural neighbors as no lens (null)", () => {
    expect(sceneFacetOf("context_note", "moc_parent")).toBeNull();
    expect(sceneFacetOf("context_note", "markdown_link")).toBeNull();
    expect(sceneFacetOf("root_index", undefined)).toBeNull();
    expect(sceneFacetOf(undefined, undefined)).toBeNull();
  });

  it("page_type wins over a conflicting edge", () => {
    expect(sceneFacetOf("decision", "markdown_link")).toBe("intencao");
  });
});

describe("homeQuadrant — a page's OWN quadrant (Quadrants perspective)", () => {
  it("keys on page_type only, never an edge; structural/unknown = null (q0-core)", () => {
    // Mirrors wiki_core/facets.py test_home_quadrant_* exactly (front/back parity).
    expect(homeQuadrant("decision")).toBe("intencao");
    expect(homeQuadrant("action")).toBe("pratica");
    expect(homeQuadrant("person")).toBe("relacoes");
    expect(homeQuadrant("source")).toBe("sistemas");
    expect(homeQuadrant("context_hub")).toBeNull();
    expect(homeQuadrant("root_index")).toBeNull();
    expect(homeQuadrant("totally_unknown_type")).toBeNull();
    expect(homeQuadrant(undefined)).toBeNull();
  });

  it("a registry override wins (a wiki can editorially place a type)", () => {
    expect(homeQuadrant("context_note", { context_note: "relacoes" })).toBe("relacoes");
  });

  it("exposes four fixed 90°-apart sector bearings, one per facet", () => {
    const angles = SCENE_FACETS.map((f) => QUADRANT_CENTER_ANGLE[f]);
    expect(angles).toHaveLength(4);
    // Every facet has a bearing and they are distinct.
    expect(new Set(angles).size).toBe(4);
    SCENE_FACETS.forEach((f) => expect(typeof QUADRANT_CENTER_ANGLE[f]).toBe("number"));
  });
});
