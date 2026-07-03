import { describe, expect, it } from "vitest";
import { SCENE_FACETS, sceneFacetOf } from "./facets";

describe("scene facets (frontend mirror of wiki_core/facets.py)", () => {
  it("exposes exactly the four lenses in canonical order", () => {
    expect([...SCENE_FACETS]).toEqual(["intencao", "percepcao", "pratica", "relacoes"]);
  });

  it("buckets by page_type first", () => {
    expect(sceneFacetOf("decision", undefined)).toBe("intencao");
    expect(sceneFacetOf("insight", undefined)).toBe("percepcao");
    expect(sceneFacetOf("action", undefined)).toBe("pratica");
    expect(sceneFacetOf("person", undefined)).toBe("relacoes");
    expect(sceneFacetOf("meeting", undefined)).toBe("relacoes");
  });

  it("falls back to the typed edge when the page_type is unknown", () => {
    // context_note is not in the map → edge decides.
    expect(sceneFacetOf("context_note", "source_ref")).toBe("pratica");
    expect(sceneFacetOf("context_note", "decision")).toBe("intencao");
    expect(sceneFacetOf(undefined, "claim")).toBe("percepcao");
  });

  it("treats structural neighbors as no lens (null)", () => {
    // Hierarchy and plain links carry no facet — they belong outside the lenses.
    expect(sceneFacetOf("context_note", "moc_parent")).toBeNull();
    expect(sceneFacetOf("context_note", "markdown_link")).toBeNull();
    expect(sceneFacetOf("root_index", undefined)).toBeNull();
    expect(sceneFacetOf(undefined, undefined)).toBeNull();
  });

  it("page_type wins over a conflicting edge", () => {
    // A decision reached by a structural link is still an Intention neighbor.
    expect(sceneFacetOf("decision", "markdown_link")).toBe("intencao");
  });
});
