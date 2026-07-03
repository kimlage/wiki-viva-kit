// Facets in the scene — the frontend mirror of wiki_core/facets.py. The Focus
// perspective buckets a page's neighbors into the four lenses, ONE PER QUADRANT
// (faithful AQAL 1:1): intencao=q1, pratica=q2, relacoes=q3, sistemas=q4. Pure,
// so the layout worker can use it. Labels live in i18n (facet.*).

export const SCENE_FACETS = ["intencao", "pratica", "relacoes", "sistemas"] as const;
export type SceneFacet = (typeof SCENE_FACETS)[number];

const PAGE_TYPE_FACET: Record<string, SceneFacet | null> = {
  // Intention (q1, interior-individual) — intent AND perception.
  decision: "intencao",
  operational_rule: "intencao",
  responsibility: "intencao",
  project: "intencao",
  initiative: "intencao",
  insight: "intencao",
  journal_entry: "intencao",
  claim: "intencao",
  perspective: "intencao",
  // Practice (q2, exterior-individual) — own output/artifacts.
  action: "pratica",
  artifact: "pratica",
  evidence: "pratica",
  // Relations (q3, interior-collective) — people/roles/culture.
  person: "relacoes",
  role: "relacoes",
  meeting: "relacoes",
  holon: "relacoes",
  relationship_map: "relacoes",
  // Systems (q4, exterior-collective) — process/channel/tooling infrastructure.
  process: "sistemas",
  source: "sistemas",
  source_config: "sistemas",
  ingestion_event: "sistemas",
  input_channel: "sistemas",
  input_stage: "sistemas",
  dashboard: "sistemas",
  // Structural — not a lens.
  root_entity: null,
  root_index: null,
  context_hub: null,
  ontology_index: null,
  source_registry: null,
  source_catalog: null,
  system_log: null
};

const EDGE_FACET: Record<string, SceneFacet | null> = {
  moc_parent: null,
  markdown_link: null,
  source_ref: "sistemas",
  pr_impact: "sistemas",
  ingestion_chain: "sistemas",
  decision: "intencao",
  claim: "intencao",
  action: "pratica"
};

// Which lens a neighbor falls under, seen from the center. page_type wins;
// the typed edge is the fallback; null = structural (shown outside the lenses).
export function sceneFacetOf(pageType: string | undefined, edgeType: string | undefined): SceneFacet | null {
  if (pageType && pageType in PAGE_TYPE_FACET) return PAGE_TYPE_FACET[pageType];
  if (edgeType && edgeType in EDGE_FACET) return EDGE_FACET[edgeType];
  return null;
}

// The quadrant a page LIVES IN, keyed by its OWN page_type (not a neighbor edge
// — that is the difference from sceneFacetOf). This drives the Quadrants
// perspective's spatial home. `overrides` (a wiki's per-type `home_quadrant:`
// from the template registry) wins; structural/unknown types are null — they
// honestly have no AQAL quadrant and render in the central q0-core, never forced
// into a real quadrant.
export function homeQuadrant(
  pageType: string | undefined,
  overrides?: Record<string, SceneFacet | null>
): SceneFacet | null {
  if (pageType && overrides && pageType in overrides) return overrides[pageType];
  if (pageType && pageType in PAGE_TYPE_FACET) return PAGE_TYPE_FACET[pageType];
  return null;
}

// Fixed sector-center bearing per quadrant (radians, one deterministic source
// for the layout, compass and minimap). Evenly spaced from NE, CCW. Visual
// bearing is tunable in the scene; the CONTRACT is that these four are constant
// and 90° apart.
export const QUADRANT_CENTER_ANGLE: Record<SceneFacet, number> = {
  intencao: Math.PI / 4,
  pratica: (3 * Math.PI) / 4,
  relacoes: (5 * Math.PI) / 4,
  sistemas: (7 * Math.PI) / 4
};
