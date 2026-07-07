// Facets in the scene — the frontend mirror of wiki_core/facets.py. The Focus
// perspective buckets a page's neighbors into the four lenses, ONE PER QUADRANT
// (faithful AQAL 1:1): intencao=q1, pratica=q2, relacoes=q3, sistemas=q4. Pure,
// so the layout worker can use it. Labels live in i18n (facet.*).

export const SCENE_FACETS = ["intencao", "pratica", "relacoes", "sistemas"] as const;
export type SceneFacet = (typeof SCENE_FACETS)[number];

const PAGE_TYPE_FACET: Record<string, SceneFacet | null> = {
  // Identity and intent (q1, interior-individual) — intent AND perception.
  decision: "intencao",
  responsibility: "intencao",
  project: "intencao",
  initiative: "intencao",
  insight: "intencao",
  journal_entry: "intencao",
  claim: "intencao",
  perspective: "intencao",
  // Outputs and evidence (q2, exterior-individual) — observable traces, outputs, artifacts and evidence.
  action: "pratica",
  artifact: "pratica",
  evidence: "pratica",
  source: "pratica",
  source_catalog: "pratica",
  source_registry: "pratica",
  system_log: "pratica",
  ingestion_event: "pratica",
  dashboard: "pratica",
  root_index: "pratica",
  ontology_index: "pratica",
  // Culture and relations (q3, interior-collective) — people, lived roles and culture.
  person: "relacoes",
  role: "relacoes",
  meeting: "relacoes",
  holon: "relacoes",
  relationship_map: "relacoes",
  // Systems and governance (q4, exterior-collective) — coordination, governance and process infrastructure.
  operational_rule: "sistemas",
  context_hub: "sistemas",
  process: "sistemas",
  source_config: "sistemas",
  input_channel: "sistemas",
  input_stage: "sistemas",
  skill: "sistemas",
  tool: "sistemas",
  template_block: "sistemas",
  // The active root stays at the center of the quadrant map.
  root_entity: null
};

const EDGE_FACET: Record<string, SceneFacet | null> = {
  moc_parent: null,
  markdown_link: null,
  source_ref: "pratica",
  pr_impact: "sistemas",
  ingestion_chain: "sistemas",
  decision: "intencao",
  claim: "intencao",
  action: "pratica"
};

// Which lens a neighbor falls under, seen from the center. page_type wins;
// the typed edge is the fallback; null = active-root/unknown (shown outside the lenses).
export function sceneFacetOf(pageType: string | undefined, edgeType: string | undefined): SceneFacet | null {
  if (pageType && pageType in PAGE_TYPE_FACET) return PAGE_TYPE_FACET[pageType];
  if (edgeType && edgeType in EDGE_FACET) return EDGE_FACET[edgeType];
  return null;
}

// The quadrant a page LIVES IN, keyed by its OWN page_type (not a neighbor edge
// — that is the difference from sceneFacetOf). This drives the Quadrants
// perspective's spatial home. `overrides` (a wiki's per-type `home_quadrant:`
// from the template registry) wins; active-root/unknown types are null. Common
// catalog/log/source pages have explicit defaults so q0_core stays a center, not
// an unclassified page bucket.
export function homeQuadrant(
  pageType: string | undefined,
  overrides?: Record<string, SceneFacet | null>
): SceneFacet | null {
  if (pageType && overrides && pageType in overrides) return overrides[pageType];
  if (pageType && pageType in PAGE_TYPE_FACET) return PAGE_TYPE_FACET[pageType];
  return null;
}

// The AUTHORITATIVE per-page classification: the compiler's derived
// quadrant_assignments (block_stacks.json), which honor frontmatter
// home_quadrant/observed_quadrants, sub-lenses and the registry — inverted
// into a pageId → facet map. The static page-type map above is only the
// fallback for pages the compiler has not classified (e.g. bare worlds).
export type QuadrantHomes = Record<string, SceneFacet | null>;

export const FACET_BY_Q: Record<string, SceneFacet | null> = {
  q1: "intencao",
  q2: "pratica",
  q3: "relacoes",
  q4: "sistemas",
  q0_core: null
};

export function nodeQuadrant(
  nodeId: string,
  pageType: string | undefined,
  homes?: QuadrantHomes
): SceneFacet | null {
  if (homes && nodeId in homes) return homes[nodeId];
  return homeQuadrant(pageType);
}

export function quadrantHomesFromAssignments(assignments?: Record<string, string[]>): QuadrantHomes | undefined {
  if (!assignments) return undefined;
  const homes: QuadrantHomes = {};
  for (const [quadrant, ids] of Object.entries(assignments)) {
    const facet = FACET_BY_Q[quadrant] ?? null;
    for (const id of ids) homes[id] = facet;
  }
  return homes;
}

// Fixed sector-center bearing per quadrant (radians, one deterministic source
// for the layout, compass and minimap). The SVG minimap maps +x right and +z
// down, so Wilber/AQAL screen placement is: Q1 upper-left, Q2 upper-right,
// Q3 lower-left, Q4 lower-right.
export const QUADRANT_CENTER_ANGLE: Record<SceneFacet, number> = {
  intencao: (5 * Math.PI) / 4,
  pratica: (7 * Math.PI) / 4,
  relacoes: (3 * Math.PI) / 4,
  sistemas: Math.PI / 4
};
