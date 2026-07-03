import { describe, expect, it } from "vitest";
import { SCENE_FACETS, sceneFacetOf } from "./facets";

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
