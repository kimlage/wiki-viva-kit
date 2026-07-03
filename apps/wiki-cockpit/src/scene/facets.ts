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
